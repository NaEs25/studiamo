// --- Studiamo Core Module ---

// Escapes a string for safe interpolation into HTML markup built via template literals.
// Required anywhere user- or third-party-supplied text (titles, descriptions, etc.) is
// interpolated into an innerHTML/insertAdjacentHTML string rather than set via textContent.
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function parseDate(dateStr) {
    if (!dateStr) return new Date();
    let clean = dateStr;
    if (!clean.endsWith('Z') && !clean.includes('+')) {
        if (clean.includes('.')) {
            clean = clean.split('.')[0];
        }
        clean = clean + 'Z';
    }
    return new Date(clean);
}

// Global state variables
let activeUsername = localStorage.getItem('active_username') || 'default_user';
let currentUserStats = { xp: 0, level: 1, streak: 0, badges: [] };
let activeQuizSession = null;
let currentQuestionIndex = 0;

const _pendingGETs = new Map();

// Central API communication utility
async function fetchAPI(url, options = {}) {
    const isGET = !options.method || options.method.toUpperCase() === 'GET';
    if (isGET && _pendingGETs.has(url)) {
        return _pendingGETs.get(url);
    }

    if (!options.headers) {
        options.headers = {};
    }
    options.headers['x-username'] = activeUsername;

    const fetchPromise = (async () => {
        try {
            const response = await fetch(url, options);
            // Auth is the httponly yb_session cookie now, not a client-held password, // a 401 here means that cookie is missing or expired, and no client-side
            // retry can fix that. Send the user back to log in.
            if (response.status === 401 && !url.includes('/api/users/verify')) {
                window.location.href = '/login';
                return;
            }
            // 402 Payment Required : the paid-access gate (dependencies.require_app_access).
            // Raised when a subscription lapses mid-session: the paywall was never shown
            // because the user had access at page load, so without this every request would
            // fail silently and leave an empty shell of an app with no explanation until a
            // manual refresh. Showing the modal here explains it immediately.
            //
            // Still falls through to the throw below so each caller handles its own failure;
            // this only adds the explanation. notifyPaymentRequired() (not openPaywall) is
            // deliberate: it no-ops when the modal is already open, so a burst of concurrent
            // 402s cannot reset a user who is reading the beta offer back to step one.
            if (response.status === 402 && typeof notifyPaymentRequired === 'function') {
                notifyPaymentRequired();
            }
            if (!response.ok) {
                let msg = 'API Call failed';
                try {
                    const err = await response.json();
                    if (typeof err.detail === 'string') {
                        msg = err.detail;
                    } else if (Array.isArray(err.detail)) {
                        msg = err.detail.map(d => d.msg || JSON.stringify(d)).join(', ');
                    } else if (err.detail) {
                        msg = JSON.stringify(err.detail);
                    } else if (err.message) {
                        msg = err.message;
                    }
                } catch (e) {}
                throw new Error(msg);
            }
            return await response.json();
        } catch (e) {
            console.error(`API Error [${url}]:`, e);
            throw e;
        } finally {
            if (isGET) _pendingGETs.delete(url);
        }
    })();

    if (isGET) _pendingGETs.set(url, fetchPromise);
    return fetchPromise;
}

// Error UI helper
function showErrorBanner(msg) {
    const banner = document.getElementById('api-error-banner');
    if (banner) {
        banner.querySelector('p').textContent = msg;
        banner.classList.remove('hidden');
        setTimeout(() => banner.classList.add('hidden'), 8000);
    }
}

// --- Task & Backlog Manager ---
class ImportBacklogManager {
    constructor() {
        this.tasks = [];
        this.pollingTimer = null;
        this.uiTimer = null;
        this.taskStartTimes = new Map();
        this.isDrawerOpen = localStorage.getItem('import_drawer_open') === 'true';
        this.expandedDetails = new Set();
    }

    async poll() {
        const prevStatuses = new Map(this.tasks.map(t => [t.id, t.status]));
        try {
            const data = await fetchAPI('/api/videos/import-tasks');
            if (Array.isArray(data)) {
                let statusChanged = false;
                let justCompleted = 0;
                let justFailed = 0;
                const now = Date.now();
                for (const t of data) {
                    const prev = prevStatuses.get(t.id);
                    if (prev && (prev === 'pending' || prev === 'processing') && (t.status === 'completed' || t.status === 'failed')) {
                        statusChanged = true;
                        if (t.status === 'completed') justCompleted++;
                        else justFailed++;
                    }
                    if (t.status === 'processing' && !this.taskStartTimes.has(t.id)) {
                        this.taskStartTimes.set(t.id, now);
                    }
                }

                // Success is announced here, on the actual completion transition, // POST /api/videos only enqueues the task and returns immediately, so
                // toasting there claimed "imported successfully" while the import was
                // still running (and even when it went on to fail).
                if (typeof showToast === 'function') {
                    if (justCompleted === 1) {
                        showToast("Video imported successfully!", "saved");
                    } else if (justCompleted > 1) {
                        showToast(`${justCompleted} imports finished!`, "saved");
                    }
                    if (justFailed === 1) {
                        showToast("An import failed: see the import list for details.", "failed", 4000);
                    } else if (justFailed > 1) {
                        showToast(`${justFailed} imports failed: see the import list.`, "failed", 4000);
                    }
                }

                this.tasks = data;
                this.render();

                if (statusChanged) {
                    if (typeof loadGoals === 'function') loadGoals();
                    if (typeof loadDashboard === 'function') loadDashboard();
                }
            }
        } catch (e) {
            console.error("Failed polling import tasks:", e);
        }

        const activeCount = this.tasks.filter(t => t.status === 'pending' || t.status === 'processing').length;
        if (activeCount > 0) {
            if (!this.pollingTimer) {
                this.pollingTimer = setInterval(() => this.poll(), 3000);
            }
            if (!this.uiTimer) {
                this.uiTimer = setInterval(() => this.renderProgressOnly(), 500);
            }
        } else {
            if (this.pollingTimer) {
                clearInterval(this.pollingTimer);
                this.pollingTimer = null;
            }
            if (this.uiTimer) {
                clearInterval(this.uiTimer);
                this.uiTimer = null;
            }
        }
    }

    // Time-based fake progress: the backend reports only pending/processing/completed,
    // so the bar animates toward an expected finish time instead of real progress.
    //
    // Targets are calibrated against real completion times (see the import_timings
    // table). Overshooting is the safe direction: a bar that reaches the cap early
    // freezes there until the task ends, which reads as "stuck", whereas one still
    // climbing simply jumps to done. The old values (22 default, 16 short) sat below
    // the fastest import ever recorded (~22s), so the bar stalled on every import.
    // The per-length buckets are provisional , duration was never recorded until
    // now, so refine them once import_timings has data.
    //
    // Used by both render() and renderProgressOnly(); they must agree, or the bar
    // jumps the first time the 500ms tick recomputes it.
    computeProgressPct(task, now) {
        if (task.status === 'pending') {
            return 0;
        }
        const clientStart = this.taskStartTimes.get(task.id) || now;
        const elapsedSec = Math.max(0, (now - clientStart) / 1000);

        let targetDurationSec = 38;
        if (task.duration_seconds && task.duration_seconds > 0) {
            if (task.duration_seconds > 900) targetDurationSec = 48;
            else if (task.duration_seconds > 300) targetDurationSec = 40;
            else targetDurationSec = 32;
        }

        const idHash = String(task.id).split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
        const maxHoldCap = 86 + (idHash % 9); // Varies dynamically between 86% and 94%

        return Math.min(maxHoldCap, Math.max(5, Math.floor((elapsedSec / targetDurationSec) * maxHoldCap)));
    }

    renderProgressOnly() {
        const processingTasks = this.tasks.filter(t => t.status === 'processing');
        if (processingTasks.length === 0) return;
        const now = Date.now();
        processingTasks.forEach(task => {
            const progressPct = this.computeProgressPct(task, now);

            const barEl = document.getElementById(`task-progress-bar-${task.id}`);
            const textEl = document.getElementById(`task-progress-text-${task.id}`);
            if (barEl) barEl.style.width = `${progressPct}%`;
            if (textEl) textEl.textContent = `${progressPct}%`;
        });
    }

    toggleDetails(taskId) {
        if (this.expandedDetails.has(taskId)) {
            this.expandedDetails.delete(taskId);
        } else {
            this.expandedDetails.add(taskId);
        }
        this.render();
    }

    toggleDrawer(forceState = null) {
        if (forceState !== null) {
            this.isDrawerOpen = forceState;
        } else {
            this.isDrawerOpen = !this.isDrawerOpen;
        }
        localStorage.setItem('import_drawer_open', this.isDrawerOpen);
        this.render();
    }

    render() {
        const badge = document.getElementById('import-widget-badge');
        const badgeCount = document.getElementById('import-badge-count');
        const badgeLabel = document.getElementById('import-badge-label');
        const spinner = document.getElementById('import-badge-spinner');
        const staticIcon = document.getElementById('import-badge-static-icon');
        const tasksList = document.getElementById('import-tasks-list');
        const panel = document.getElementById('import-widget-panel');

        if (!badge || !tasksList) return;

        // Hide Tasks pill widget when user is not on default main tabs (e.g., during Quiz, Study Studio, or Video Player)
        const activeOverlay = document.querySelector('div[id^="overlay-"]:not(.hidden)');
        const miniPlayer = document.getElementById('studio-mini-player');
        const miniPlayerVisible = miniPlayer && !miniPlayer.classList.contains('hidden');
        if (activeOverlay || miniPlayerVisible) {
            badge.classList.add('hidden');
            badge.classList.remove('flex');
            if (panel) panel.classList.add('hidden');
            return;
        }

        const activeTasks = this.tasks.filter(t => t.status === 'pending' || t.status === 'processing');
        const activeCount = activeTasks.length;
        const totalCount = this.tasks.length;

        if (totalCount === 0) {
            this.isDrawerOpen = false;
            localStorage.setItem('import_drawer_open', 'false');
            badge.classList.add('hidden');
            badge.classList.remove('flex');
            if (panel) panel.classList.add('hidden');
            tasksList.innerHTML = '<p class="text-xs text-stone-400 text-center py-4">No active or recent background tasks</p>';
            return;
        }

        if (this.isDrawerOpen) {
            // Hide floating pill badge when panel drawer is open to prevent overlapping
            badge.classList.add('hidden');
            badge.classList.remove('flex');
            if (panel) panel.classList.remove('hidden');
        } else {
            // Hide panel when drawer is minimized
            if (panel) panel.classList.add('hidden');
            badge.classList.remove('hidden');
            badge.classList.add('flex');
            if (badgeCount) badgeCount.textContent = activeCount > 0 ? activeCount : totalCount;

            if (activeCount > 0) {
                if (spinner) spinner.classList.remove('hidden');
                if (staticIcon) staticIcon.classList.add('hidden');
                if (badgeLabel) badgeLabel.textContent = 'Importing...';
            } else {
                if (spinner) spinner.classList.add('hidden');
                if (staticIcon) staticIcon.classList.remove('hidden');
                if (badgeLabel) badgeLabel.textContent = 'Tasks';
            }
        }

        const now = Date.now();
        tasksList.innerHTML = this.tasks.map(task => {
            let iconLucide = 'film';
            if (task.task_type === 'document') iconLucide = 'file-text';
            if (task.task_type === 'notes') iconLucide = 'file-edit';
            if (task.task_type === 'goal_recommendations') iconLucide = 'compass';
            if (task.task_type === 'goal_quiz') iconLucide = 'brain';

            let thumbUrl = task.thumbnail_url;
            if (!thumbUrl && task.youtube_id) {
                thumbUrl = `https://img.youtube.com/vi/${task.youtube_id}/mqdefault.jpg`;
            }

            let mediaPreviewHTML = '';
            if (thumbUrl && !thumbUrl.includes('document-icon') && !thumbUrl.includes('notes-icon')) {
                mediaPreviewHTML = `
                    <img src="${thumbUrl}" class="w-9 h-7 object-cover rounded-md border border-[#e7dfd3] bg-stone-100 shrink-0 shadow-2xs" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'p-1.5 bg-amber-500/10 border border-amber-500/20 rounded-md shrink-0 text-amber-700\\'><i data-lucide=\\'${iconLucide}\\' class=\\'w-3.5 h-3.5\\'></i></div>';">
                `;
            } else {
                mediaPreviewHTML = `
                    <div class="p-1.5 bg-amber-500/10 border border-amber-500/20 rounded-md shrink-0 text-amber-700">
                        <i data-lucide="${iconLucide}" class="w-3.5 h-3.5"></i>
                    </div>
                `;
            }

            let actionBtnHTML = '';
            let statusTextHTML = '';

            if (task.status === 'pending') {
                statusTextHTML = `
                    <div class="w-full space-y-1 mt-1">
                        <div class="flex items-center justify-between text-[10px] text-stone-500 font-medium">
                            <span class="text-amber-800/90 font-semibold">Queued (Waiting for slot)...</span>
                            <span id="task-progress-text-${task.id}" class="font-mono text-stone-400 font-medium">Waiting</span>
                        </div>
                        <div class="w-full bg-stone-100 rounded-full h-1 overflow-hidden border border-stone-200/60">
                            <div id="task-progress-bar-${task.id}" class="bg-stone-300 h-full rounded-full" style="width: 0%"></div>
                        </div>
                    </div>
                `;
            } else if (task.status === 'processing') {
                const progressPct = this.computeProgressPct(task, now);
                const stageLabel = task.progress_stage || 'Processing AI Quizzes & SRS...';

                statusTextHTML = `
                    <div class="w-full space-y-1 mt-1">
                        <div class="flex items-center justify-between text-[10px] text-stone-500 font-medium">
                            <span class="truncate max-w-[200px]" title="${stageLabel}">${stageLabel}</span>
                            <span id="task-progress-text-${task.id}" class="font-mono text-amber-700 font-semibold shrink-0 ml-1">${progressPct}%</span>
                        </div>
                        <div class="w-full bg-stone-200/80 rounded-full h-1 overflow-hidden">
                            <div id="task-progress-bar-${task.id}" class="bg-amber-600 h-full transition-all duration-300 ease-out rounded-full" style="width: ${progressPct}%"></div>
                        </div>
                    </div>
                `;
            } else if (task.status === 'completed') {
                statusTextHTML = '';
                if (task.video_id) {
                    actionBtnHTML = `
                        <button onclick="openTaskStudioAndDismiss('${task.id}', ${task.video_id})" class="text-[10px] bg-[#fbbf24] hover:bg-[#f59e0b] text-[#78350f] font-extrabold px-3 py-1 rounded-lg transition flex items-center space-x-1 shadow-xs cursor-pointer">
                            <span>Open</span>
                            <i data-lucide="arrow-right" class="w-2.5 h-2.5"></i>
                        </button>
                    `;
                }
            } else if (task.status === 'failed') {
                actionBtnHTML = `
                    <button onclick="retryImportTask('${task.id}')" class="text-[10px] bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 font-bold px-2.5 py-1 rounded-lg transition flex items-center space-x-1 cursor-pointer">
                        <i data-lucide="rotate-cw" class="w-2.5 h-2.5"></i>
                        <span>Retry</span>
                    </button>
                `;
                statusTextHTML = `
                    <div class="text-[10px] bg-red-50 text-red-700 p-2 rounded-lg border border-red-200 mt-1">
                        <p class="font-bold text-red-800">Import Failed</p>
                        <p class="text-[10px] text-red-600 break-words leading-tight whitespace-normal mt-0.5">${escapeHtml(task.error_message) || 'Error occurred during processing.'}</p>
                    </div>
                `;
            }

            return `
                <div class="bg-white border border-[#e7dfd3] p-2.5 rounded-xl flex flex-col space-y-1 shadow-xs text-stone-900 group">
                    <div class="flex items-center justify-between space-x-2">
                        <div class="flex items-center space-x-2 min-w-0 flex-grow">
                            ${mediaPreviewHTML}
                            <span class="font-bold text-xs text-stone-900 truncate" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</span>
                        </div>
                        <div class="flex items-center space-x-1.5 shrink-0">
                            ${actionBtnHTML}
                            <button onclick="dismissImportTask('${task.id}')" class="p-1 hover:bg-stone-100 text-stone-400 hover:text-stone-700 rounded-md transition cursor-pointer" title="Dismiss">
                                <i data-lucide="x" class="w-3.5 h-3.5"></i>
                            </button>
                        </div>
                    </div>
                    ${statusTextHTML}
                </div>
            `;
        }).join('');

        renderIcons();
    }
}

const globalImportBacklog = new ImportBacklogManager();

function toggleImportBacklogDrawer(forceState = null) {
    globalImportBacklog.toggleDrawer(forceState);
}

function toggleTaskStepDetails(taskId) {
    globalImportBacklog.toggleDetails(taskId);
}

async function retryImportTask(taskId) {
    try {
        if (typeof showToast === 'function') {
            showToast("Retrying import task...", "loading", 2000);
        }
        await fetchAPI(`/api/videos/import-tasks/${taskId}/retry`, { method: 'POST' });
        globalImportBacklog.poll();
        if (typeof loadGoals === 'function') loadGoals();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        if (typeof showToast === 'function') {
            showToast("Failed to retry task: " + e.message, "failed");
        } else {
            alert("Failed to retry task: " + e.message);
        }
    }
}

async function dismissImportTask(taskId) {
    try {
        await fetchAPI(`/api/videos/import-tasks/${taskId}`, { method: 'DELETE' });
        globalImportBacklog.poll();
    } catch (e) {
        console.error("Failed to dismiss task:", e);
    }
}

function openTaskStudioAndDismiss(taskId, videoId) {
    if (taskId) {
        dismissImportTask(taskId);
    }
    if (videoId && typeof navigateToVideoInGoals === 'function') {
        navigateToVideoInGoals(videoId);
    } else if (videoId && typeof openStudyStudio === 'function') {
        openStudyStudio(videoId);
    }
}

// Loader UI helpers
let _currentActiveLoaderVideoId = null;

function showLoader(title, desc, videoId = null) {
    if (videoId) _currentActiveLoaderVideoId = videoId;
    globalImportBacklog.poll();
}

function showLoaderDone(title, desc, videoId = null) {
    if (videoId) _currentActiveLoaderVideoId = videoId;
    globalImportBacklog.poll();
}

function hideLoader(force = false, doneTitle = null, doneDesc = null, videoId = null) {
    globalImportBacklog.poll();
}

function minimizeLoader() {
    globalImportBacklog.toggleDrawer(false);
}

function restoreLoader() {
    globalImportBacklog.toggleDrawer(true);
}

function onLoaderPillClick() {
    if (_currentActiveLoaderVideoId) {
        const vid = _currentActiveLoaderVideoId;
        if (typeof openStudyStudio === 'function') {
            openStudyStudio(vid);
        } else if (typeof switchTab === 'function') {
            switchTab('dashboard');
        }
    }
}

function renderIcons() {
    if (typeof lucide !== 'undefined' && lucide.createIcons) {
        lucide.createIcons();
    }
}

// Shared thumbnail renderer for videos/PDFs/notes: real image for YouTube videos,
// an icon badge for uploaded documents so PDFs/notes never fall back to a static SVG file.
function renderMediaThumbHTML(video, opts) {
    opts = opts || {};
    const sizeClasses = opts.sizeClasses || 'w-16 h-10';
    const clickAttr = opts.onClick ? `onclick="${opts.onClick}"` : '';
    const title = opts.title || '';

    if (video && video.youtube_id && video.thumbnail_url) {
        return `<img src="${video.thumbnail_url}" ${clickAttr}
                class="${sizeClasses} object-cover rounded-lg border border-[#e7dfd3] bg-stone-100 shrink-0 cursor-pointer hover:opacity-80 transition"
                onerror="this.src='/static/images/notes-icon.svg'"
                title="${title}">`;
    }

    const isPdfDoc = video && !video.youtube_id && video.title && video.title.toLowerCase().endsWith('.pdf');
    const iconLucide = isPdfDoc ? 'file-text' : 'file-edit';
    return `<div ${clickAttr}
            class="${sizeClasses} flex items-center justify-center rounded-lg border border-amber-500/20 bg-amber-500/10 text-amber-700 shrink-0 cursor-pointer hover:opacity-80 transition"
            title="${title}"><i data-lucide="${iconLucide}" class="w-5 h-5"></i></div>`;
}

let windowAppConfig = { app_mode: 'selfhosted', is_cloud: false, is_selfhosted: true };

async function loadSystemConfig() {
    try {
        const res = await fetch('/api/config');
        if (res.ok) {
            windowAppConfig = await res.json();
            window.appConfig = windowAppConfig;
            if (windowAppConfig.app_mode) {
                document.documentElement.dataset.appMode = windowAppConfig.app_mode;
                if (document.body) document.body.dataset.appMode = windowAppConfig.app_mode;
            }
        }
    } catch (e) {
        console.warn('System config load error:', e);
    }
}

// Exposed so callers that genuinely need app_mode (billing.js) can await the fetch instead
// of racing it. This listener is registered before app.js's, so the promise exists by the
// time app.js runs.
document.addEventListener('DOMContentLoaded', () => {
    window.systemConfigReady = loadSystemConfig();
    globalImportBacklog.poll();

    // Re-check hide/show whenever any overlay (id^="overlay-") or the Study Studio
    // mini-player toggles its "hidden" class, instead of relying on every overlay's
    // open/close code to remember to call render() itself: that's how this widget
    // ended up stuck on top of the Quiz and Study Studio overlays before.
    const overlayVisibilityObserver = new MutationObserver((mutations) => {
        for (const m of mutations) {
            const el = m.target;
            if (el.id === 'studio-mini-player' || (el.id && el.id.startsWith('overlay-'))) {
                globalImportBacklog.render();
                return;
            }
        }
    });
    overlayVisibilityObserver.observe(document.body, {
        attributes: true,
        attributeFilter: ['class'],
        subtree: true,
    });
});

// Bind core helpers to global window scope for inline event handlers
window.parseDate = parseDate;
window.fetchAPI = fetchAPI;
window.showErrorBanner = showErrorBanner;
window.showLoader = showLoader;
window.showLoaderDone = showLoaderDone;
window.hideLoader = hideLoader;
window.minimizeLoader = minimizeLoader;
window.restoreLoader = restoreLoader;
window.onLoaderPillClick = onLoaderPillClick;
window.renderIcons = renderIcons;
window.toggleImportBacklogDrawer = toggleImportBacklogDrawer;
window.toggleTaskStepDetails = toggleTaskStepDetails;
window.retryImportTask = retryImportTask;
window.dismissImportTask = dismissImportTask;
window.openTaskStudioAndDismiss = openTaskStudioAndDismiss;
window.globalImportBacklog = globalImportBacklog;

