// --- Studiamo Master Entry Point ---

function switchTab(tabId) {
    localStorage.setItem('active_studiamo_tab', tabId);
    document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));

    const activePanel = document.getElementById(`tab-${tabId}`);
    if (activePanel) {
        activePanel.classList.remove('hidden');
    }

    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

    const activeNav = document.getElementById(`nav-${tabId}`);
    if (activeNav) activeNav.classList.add('active');

    if (tabId === 'dashboard') {
        loadDashboard();
    } else if (tabId === 'goals') {
        if (typeof loadGoals === 'function') loadGoals();
    } else if (tabId === 'stats') {
        if (typeof loadStats === 'function') loadStats();
    } else if (tabId === 'settings') {
        if (typeof loadSettings === 'function') loadSettings();
    }

}


async function loadDashboard() {
    try {
        const data = await fetchAPI('/api/dashboard');
        
        currentUserStats = data.user || currentUserStats;
        updateHeaderStats();
        if (data.user && typeof captureTimezoneIfMissing === 'function') {
            captureTimezoneIfMissing(data.user.timezone);
        }
        
        if (typeof renderGoalBoxes === 'function' && data.goals) {
            renderGoalBoxes(data.goals);
        }

        if (data.chompy) maybeShowChompyAway(data.chompy.eaten_unseen || []);

        const emptyGoalsHero = document.getElementById('dashboard-empty-goals');
        const dueHero = document.getElementById('due-quizzes-hero');
        const duePanel = document.getElementById('due-quizzes-panel');
        const dailyRecsPanel = document.getElementById('daily-recommendations-panel');
        const upcomingPanel = document.getElementById('upcoming-quizzes-panel');

        if (!data.goals || data.goals.length === 0) {
            if (emptyGoalsHero) emptyGoalsHero.classList.remove('hidden');
            if (dueHero) dueHero.classList.add('hidden');
            if (duePanel) duePanel.classList.add('hidden');
            if (dailyRecsPanel) dailyRecsPanel.classList.add('hidden');
            if (upcomingPanel) upcomingPanel.classList.add('hidden');
            return;
        } else {
            if (emptyGoalsHero) emptyGoalsHero.classList.add('hidden');
            if (dailyRecsPanel) dailyRecsPanel.classList.remove('hidden');
        }
        
        const seenVideos = {};
        const getActiveQuizInfo = (q) => {
            if (q.quiz_type === 'video') {
                const linkedVideo = data.videos.find(v => v.id === q.video_id);
                if (!linkedVideo || linkedVideo.is_archived || linkedVideo.is_paused || linkedVideo.is_watchlist) {
                    return null;
                }
                if (q.importance_level !== linkedVideo.importance_rating) {
                    return null;
                }
                if (seenVideos[q.video_id]) {
                    return null;
                }
                seenVideos[q.video_id] = true;
                return { title: linkedVideo.title, quiz: q, video: linkedVideo };
            }
            return null;
        };

        const activeQuizzes = (data.quizzes || [])
            .map(getActiveQuizInfo)
            // A mastered quiz has no real next review (its next_review_at is a far-future
            // sentinel, see grade_quiz), so it belongs in neither the due nor upcoming panel.
            .filter(info => info !== null && !info.quiz.mastered);

        // is_due and days_until_due come from the server, computed in the user's time zone:
        // a review is due for its whole local day, not from the hour stored with it.
        // Closest to being eaten by Chompy first, so the list starts where it matters most.
        const eatenOrder = q => (q.days_until_eaten === null || q.days_until_eaten === undefined) ? 99 : q.days_until_eaten;
        const dueQuizzes = activeQuizzes
            .filter(info => info.quiz.is_due === true)
            .sort((a, b) => eatenOrder(a.quiz) - eatenOrder(b.quiz));
        const upcomingQuizzes = activeQuizzes
            .filter(info => info.quiz.is_due !== true)
            .sort((a, b) => parseDate(a.quiz.next_review_at) - parseDate(b.quiz.next_review_at));
            
        renderChompyBelt(dueQuizzes, data.user ? data.user.day_progress : 0);

        const dueList = document.getElementById('due-quizzes-list');
        if (duePanel && dueList) {
            if (dueQuizzes.length > 0) {
                dueList.innerHTML = dueQuizzes.map(renderDueCard).join('');
                duePanel.classList.remove('hidden');
            } else {
                duePanel.classList.add('hidden');
            }
        }

        const upcomingCount = document.getElementById('upcoming-quizzes-count');
        if (upcomingCount) {
            upcomingCount.textContent = upcomingQuizzes.length;
            upcomingCount.classList.toggle('hidden', upcomingQuizzes.length === 0);
        }
        const upcomingList = document.getElementById('upcoming-quizzes-list');
        if (upcomingPanel && upcomingList) {
            if (upcomingQuizzes.length > 0) {
                upcomingList.innerHTML = upcomingQuizzes.map(item => {
                    const q = item.quiz;
                    const daysAhead = q.days_until_due || 1;
                    const relativeStr = daysAhead === 1 ? 'tomorrow' : `in ${daysAhead} days`;
                    const formattedDate = parseDate(q.next_review_at).toLocaleDateString([], { month: 'short', day: 'numeric' });
                    const vidId = item.video ? item.video.id : null;
                    const clickAction = vidId ? `onclick="navigateToVideoInGoals(${vidId})"` : '';
                    const thumbHTML = renderMediaThumbHTML(item.video, {
                        sizeClasses: 'w-12 h-8',
                        title: 'View Video in Goals'
                    });
                    return `
                        <div class="flex justify-between items-center bg-stone-100 border border-stone-200 rounded-xl p-3 text-xs gap-3">
                            <div class="flex items-center space-x-3 min-w-0 ${vidId ? 'cursor-pointer' : ''}" ${clickAction}>
                                ${thumbHTML}
                                <span class="block truncate font-semibold text-stone-900 hover:text-amber-300 transition max-w-[240px]">${escapeHtml(item.title)}</span>
                            </div>
                            <div class="flex items-center space-x-2 shrink-0">
                                <span class="text-[10px] bg-amber-500/10 border border-amber-200 text-amber-700 font-bold px-2 py-0.5 rounded-full shrink-0" title="${formattedDate}">
                                    ${relativeStr}
                                </span>
                            </div>
                        </div>
                    `;
                }).join('');
                upcomingPanel.classList.remove('hidden');
            } else {
                upcomingList.innerHTML = `<p class="text-xs text-stone-500 text-center py-4">No upcoming quizzes scheduled.</p>`;
                upcomingPanel.classList.remove('hidden');
            }
        }

        window._videoCardCache = {};
        [...(data.videos || []), ...(data.archived || [])].forEach(v => {
            window._videoCardCache[v.id] = v;
        });
        
        renderIcons();
        if (typeof loadDailyRecommendations === 'function') loadDailyRecommendations();
    } catch (e) {
        console.error("Dashboard loading failed:", e);
    } finally {
        document.getElementById('home-due-skeleton')?.classList.add('hidden');
    }
}

window._dailyRecsDrafts = window._dailyRecsDrafts || {};

// Whether each recommended video's card shows the goal it was suggested for.
const SHOW_REC_GOAL_BADGE = false;

// One delegated listener for every rec card action. The card carries its values in escaped
// data- attributes, so a video title (which a third party chooses) is only ever read back
// through dataset and never becomes part of a script string.
function handleRecommendationClick(event) {
    const actionEl = event.target.closest('[data-rec-action]');
    if (!actionEl) return;
    const card = actionEl.closest('[data-rec-yt]');
    if (!card) return;

    const { recYt: ytId, recTitle: title, recGoal: goalId, recPos: lastPos } = card.dataset;
    switch (actionEl.dataset.recAction) {
        case 'play': {
            // Once the iframe is in, a click on the wrapper's edge must not restart playback.
            if (actionEl.id === `media-wrapper-${ytId}` && actionEl.querySelector('iframe')) return;
            playRecommendedVideo(ytId, `media-wrapper-${ytId}`, title, goalId, lastPos);
            break;
        }
        case 'toggle-actions': {
            const open = actionEl.getAttribute('aria-expanded') !== 'true';
            actionEl.setAttribute('aria-expanded', String(open));
            actionEl.setAttribute('aria-label', open ? 'Hide actions for this video' : 'Show actions for this video');
            document.getElementById(actionEl.getAttribute('aria-controls'))?.classList.toggle('hidden', !open);
            break;
        }
        case 'queue':
            queueRecommendationPreview(ytId, title, goalId);
            break;
        case 'view-queue':
            navigateToVideoInGoals(Number(actionEl.dataset.recVideo));
            break;
        case 'studio':
            openRecommendationInStudio(ytId, title, goalId);
            break;
        case 'dismiss':
            dismissRecommendation(ytId);
            break;
    }
}

// --- Inline Video Player & Auto-Save Position Tracking ---
let _activeInlineYTPlayer = null;
let _activeInlineSaveInterval = null;
let _activeInlineVideoId = null;
let _activeInlineYtId = null;

function saveActiveInlinePosition() {
    if (!_activeInlineVideoId) return;
    let pos = 0;
    if (_activeInlineYTPlayer && typeof _activeInlineYTPlayer.getCurrentTime === 'function') {
        try {
            const t = _activeInlineYTPlayer.getCurrentTime();
            if (typeof t === 'number' && t > 0) pos = t;
        } catch (e) {}
    }
    if (pos <= 0) return;

    if (window._videoCardCache && window._videoCardCache[_activeInlineVideoId]) {
        window._videoCardCache[_activeInlineVideoId].last_position_seconds = pos;
    }

    try {
        const formData = new FormData();
        formData.append('position', pos.toFixed(1));
        fetchAPI(`/api/videos/${_activeInlineVideoId}/position`, { method: 'POST', body: formData });
    } catch (e) {
        console.warn("Failed to auto-save inline video position:", e);
    }
}
window.saveActiveInlinePosition = saveActiveInlinePosition;

function stopActiveInlineTracker() {
    if (_activeInlineSaveInterval) {
        clearInterval(_activeInlineSaveInterval);
        _activeInlineSaveInterval = null;
    }
    if (_activeInlineVideoId) {
        saveActiveInlinePosition();
    }
    _activeInlineYTPlayer = null;
    _activeInlineVideoId = null;
    _activeInlineYtId = null;
}
window.stopActiveInlineTracker = stopActiveInlineTracker;

window.addEventListener('beforeunload', () => {
    if (typeof saveActiveInlinePosition === 'function') {
        saveActiveInlinePosition();
    }
});

function playInlineVideo(ytId, wrapperId, startSec = 0, videoId = null) {
    stopActiveInlineTracker();

    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return;
    wrapper.onclick = null;
    wrapper.removeAttribute('onclick');
    wrapper.classList.remove('cursor-pointer');
    wrapper.classList.add('yt-downscale-wrapper');
    const iframeId = `inline-yt-${ytId}`;
    const startParam = startSec > 0 ? `&start=${Math.floor(startSec)}` : '';
    wrapper.innerHTML = `
        <iframe id="${iframeId}"
                class="w-full h-full border-0"
                src="https://www.youtube.com/embed/${ytId}?enablejsapi=1&autoplay=1&rel=0${startParam}"
                frameborder="0"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen>
        </iframe>
    `;

    _activeInlineYtId = ytId;
    _activeInlineVideoId = videoId;

    const setupInlinePlayer = () => {
        try {
            const iframe = document.getElementById(iframeId);
            if (!iframe) return;
            _activeInlineYTPlayer = new YT.Player(iframeId, {
                events: {
                    'onStateChange': (event) => {
                        if (event && (event.data === 2 || event.data === 0)) { // PAUSED or ENDED
                            saveActiveInlinePosition();
                        }
                    }
                }
            });
        } catch (e) {}
    };

    if (typeof ensureYouTubeAPI === 'function') {
        ensureYouTubeAPI(setupInlinePlayer);
    } else if (window.ensureYouTubeAPI) {
        window.ensureYouTubeAPI(setupInlinePlayer);
    }

    _activeInlineSaveInterval = setInterval(() => {
        saveActiveInlinePosition();
    }, 5000);
}
window.playInlineVideo = playInlineVideo;

async function playRecommendedVideo(ytId, wrapperId, title, goalId, lastPositionSeconds = 0) {
    const startSec = Math.floor(parseFloat(lastPositionSeconds) || 0);
    const existingVideoId = (window._dailyRecsDrafts && window._dailyRecsDrafts[ytId]) || null;
    playInlineVideo(ytId, wrapperId, startSec, existingVideoId);

    const res = await queueRecommendationPreview(ytId, title, goalId, true);
    if (res && res.video_id) {
        _activeInlineVideoId = res.video_id;
    }
}
window.playRecommendedVideo = playRecommendedVideo;

async function loadDailyRecommendations() {
    const grid = document.getElementById('daily-recommendations-grid');
    const panel = document.getElementById('daily-recommendations-panel');
    if (!grid) return;
    if (!grid.dataset.recClickBound) {
        grid.addEventListener('click', handleRecommendationClick);
        grid.dataset.recClickBound = '1';
    }

    try {
        const data = await fetchAPI('/api/daily-recommendations');
        if (panel) panel.classList.remove('hidden');

        if (!data || !data.recommendations || data.recommendations.length === 0) {
            const message = data && data.youtube_api_key_missing
                ? 'To enable recommendations, add a YouTube Data API v3 key (see the self-hosting setup guide for details).'
                : 'Create learning goals to receive curated daily video tutorials tailored to your study path.';
            grid.innerHTML = `
                <div class="col-span-full p-8 text-center bg-white border border-stone-200 rounded-2xl shadow-sm">
                    <i data-lucide="sparkles" class="w-8 h-8 text-amber-500 mx-auto mb-2"></i>
                    <h4 class="font-bold text-sm text-stone-900">Daily AI Recommendations</h4>
                    <p class="text-xs text-stone-500 mt-1">${message}</p>
                </div>
            `;
            if (typeof renderIcons === 'function') renderIcons();
            else if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }

        grid.innerHTML = data.recommendations.map(rec => {
            const ytId = rec.youtube_id || rec.id;
            const draftVideoId = rec.video_id || window._dailyRecsDrafts[ytId] || null;
            const isDraft = Boolean(isTemporaryVideo(rec) || (draftVideoId && window._dailyRecsDrafts[ytId]));
            const isQueued = Boolean(draftVideoId);
            const thumbUrl = rec.thumbnail_url || rec.thumbnail || (ytId ? `https://img.youtube.com/vi/${ytId}/hqdefault.jpg` : '/static/images/notes-icon.svg');
            const wrapperId = `media-wrapper-${ytId}`;

            let progressPercent = 0;
            const lastPos = parseFloat(rec.last_position_seconds) || 0;
            const durSec = parseFloat(rec.duration_seconds) || 0;
            if (lastPos > 0 && durSec > 0) {
                progressPercent = Math.min(100, Math.round((lastPos / durSec) * 100));
            }

            return `
                <div class="bg-white border border-stone-200/90 rounded-2xl overflow-hidden flex flex-col hover:border-amber-400 hover:shadow-md transition-all duration-200 relative group select-none"
                     data-rec-yt="${escapeHtml(ytId)}" data-rec-title="${escapeHtml(rec.title || '')}"
                     data-rec-goal="${escapeHtml(rec.goal_id || '')}" data-rec-pos="${lastPos}">
                    <!-- Inline Playable Media Wrapper -->
                    <div id="${escapeHtml(wrapperId)}" data-rec-action="play" class="w-full aspect-video relative overflow-hidden bg-stone-900 cursor-pointer group">
                        <img src="${escapeHtml(thumbUrl)}"
                             class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                             draggable="false"
                             onerror="this.src='/static/images/notes-icon.svg'">
                        
                        <!-- Goal Badge (Top-Left), hidden for now; set SHOW_REC_GOAL_BADGE to bring it back. -->
                        ${SHOW_REC_GOAL_BADGE ? `
                        <span class="absolute top-2 left-2 z-10 bg-amber-500/20 backdrop-blur-xs border border-amber-500/40 text-amber-900 text-[9px] font-extrabold px-2 py-0.5 rounded-md flex items-center space-x-1">
                            <i data-lucide="target" class="w-3 h-3 text-amber-900"></i>
                            <span class="truncate max-w-[120px]">${escapeHtml(rec.goal_title || 'AI Recommendation')}</span>
                        </span>
                        ` : ''}

                        <!-- Draft Badge (Top-Right) -->
                        ${isDraft ? `
                            <span class="absolute top-2 right-2 z-10 bg-amber-500/20 backdrop-blur-xs border border-amber-500/40 text-amber-900 text-[8px] font-extrabold uppercase px-1.5 py-0.5 rounded-md flex items-center space-x-1">
                                <i data-lucide="clock" class="w-2.5 h-2.5 text-amber-900"></i>
                                <span>Draft Preview</span>
                            </span>
                        ` : ''}

                        <!-- Center Play Button Overlay -->
                        <div class="absolute inset-0 flex items-center justify-center bg-black/10 group-hover:bg-black/25 transition-colors">
                            <div class="w-10 h-10 bg-white/20 backdrop-blur-sm border border-white/60 rounded-full flex items-center justify-center shadow-lg transition-all duration-200 transform group-hover:scale-110 group-hover:bg-white/35">
                                <i data-lucide="play" class="w-4 h-4 fill-current ml-0.5 text-stone-900 drop-shadow"></i>
                            </div>
                        </div>

                        <!-- Views Badge (Bottom-Left, Compact) -->
                        ${rec.views && rec.views !== 'N/A' ? `
                            <span class="absolute bottom-2 left-2 z-10 bg-white/70 text-stone-900/80 text-[10px] font-extrabold px-1.5 py-0.5 rounded-md flex items-center space-x-1">
                                <i data-lucide="eye" class="w-3 h-3 text-stone-900/80"></i>
                                <span>${escapeHtml(rec.views)}</span>
                            </span>
                        ` : ''}

                        <!-- Duration Badge (Bottom-Right, Compact) -->
                        ${rec.duration && rec.duration !== 'N/A' ? `
                            <span class="absolute bottom-2 right-2 z-10 bg-white/70 text-stone-900/80 text-[10px] font-extrabold px-1.5 py-0.5 rounded-md flex items-center space-x-1">
                                <i data-lucide="clock" class="w-3 h-3 text-stone-900/80"></i>
                                <span>${escapeHtml(rec.duration)}</span>
                            </span>
                        ` : ''}

                        <!-- Watch Progress Bar -->
                        ${progressPercent > 0 ? `
                            <div class="absolute bottom-0 left-0 right-0 h-1.5 bg-stone-800/80 z-10 overflow-hidden">
                                <div class="h-full bg-amber-500 rounded-r" style="width: ${progressPercent}%;"></div>
                            </div>
                        ` : ''}
                    </div>

                    <!-- Details Body -->
                    <div class="p-3.5 flex flex-col gap-2.5 bg-white">
                        <!-- The title opens the action bar below, like a video description; playing
                             stays on the thumbnail. -->
                        <h4 class="font-bold text-sm text-stone-900 leading-snug">
                            <button type="button" data-rec-action="toggle-actions" aria-expanded="false"
                                    aria-controls="rec-actions-${escapeHtml(ytId)}" aria-label="Show actions for this video"
                                    class="rec-title-toggle w-full flex items-start justify-between gap-2 text-left min-h-[44px] -my-1.5 py-1.5 hover:text-amber-700 transition-colors">
                                <span class="line-clamp-2">${escapeHtml(rec.title)}</span>
                                <i data-lucide="chevron-down" class="rec-chevron w-4 h-4 shrink-0 mt-0.5 text-stone-500"></i>
                            </button>
                        </h4>

                        <!-- Action Bar -->
                        <div id="rec-actions-${escapeHtml(ytId)}" class="hidden flex items-center space-x-2">
                            ${isQueued ? `
                                <button id="btn-queue-${escapeHtml(ytId)}" data-rec-action="view-queue" data-rec-video="${escapeHtml(draftVideoId)}" class="btn-primary flex-grow py-2 px-3 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 active:scale-[0.98]">
                                    <i data-lucide="bookmark" class="w-3.5 h-3.5 fill-current"></i>
                                    <span>View in Queue</span>
                                </button>
                            ` : `
                                <button id="btn-queue-${escapeHtml(ytId)}" data-rec-action="queue" class="btn-primary flex-grow py-2 px-3 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 active:scale-[0.98]">
                                    <i data-lucide="bookmark" class="w-3.5 h-3.5"></i>
                                    <span>Add to Queue</span>
                                </button>
                            `}
                            <button data-rec-action="studio" class="p-2 bg-stone-100 hover:bg-amber-100 text-stone-700 hover:text-amber-900 border border-stone-200 rounded-xl transition flex items-center justify-center min-w-[38px] h-[38px] shadow-sm" title="Open Study Studio (Notes)">
                                <i data-lucide="book-open" class="w-4 h-4"></i>
                            </button>
                            <button data-rec-action="dismiss" class="p-2 bg-stone-100 hover:bg-red-100 text-stone-500 hover:text-red-700 border border-stone-200 rounded-xl transition flex items-center justify-center min-w-[38px] h-[38px] shadow-sm" title="Dismiss">
                                <i data-lucide="x" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        if (typeof renderIcons === 'function') renderIcons();
        else if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        console.error("Daily recommendations load failed:", e);
    }
}

// Takes a BARE video id, not a URL, it builds the watch?v= URL itself.
// Note the argument order differs from goals.js's previewRecommendedVideo(url, goalId, title);
// calling this one with (url, goalId) produced watch?v=<entire-encoded-URL>, which Gemini
// rejected with 400 INVALID_ARGUMENT, and silently dropped the goal link.
async function importRecommendedVideo(youtubeId, title, goalId) {
    const btn = document.getElementById(`btn-import-${youtubeId}`);
    const label = document.getElementById(`text-import-${youtubeId}`);
    if (btn) btn.disabled = true;
    if (label) label.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Importing...</span>`;
    if (typeof renderIcons === 'function') renderIcons();
    else if (typeof lucide !== 'undefined') lucide.createIcons();

    try {
        const formData = new FormData();
        formData.append('url', `https://www.youtube.com/watch?v=${youtubeId}`);
        formData.append('importance_rating', 3);
        if (goalId) formData.append('learning_goal_id', goalId);
        
        await fetchAPI('/api/videos', { method: 'POST', body: formData });
        // Only queued at this point , the completion toast fires from the import
        // backlog poll once the task actually finishes.
        if (typeof showToast === 'function') {
            showToast("Import started, you can keep working.", "saved");
        }
        if (typeof loadDashboard === 'function') loadDashboard();
        if (typeof loadGoals === 'function') loadGoals();
        if (window.globalImportBacklog) {
            window.globalImportBacklog.toggleDrawer(true);
            window.globalImportBacklog.poll();
        }
        loadDailyRecommendations();
    } catch (e) {
        showToast("Import failed: " + e.message, "failed");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Swaps a single rec card's primary button to "View in Queue" in place, without
// reloading the grid, a full reload would tear out an inline video mid-playback.
function markRecommendationQueued(youtubeId, videoId) {
    const btn = document.getElementById(`btn-queue-${youtubeId}`);
    if (!btn) return;
    btn.dataset.recAction = 'view-queue';
    btn.dataset.recVideo = String(videoId);
    btn.innerHTML = `<i data-lucide="bookmark" class="w-3.5 h-3.5 fill-current"></i><span>View in Queue</span>`;
    if (typeof renderIcons === 'function') renderIcons();
    else if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Saves a recommended video as a 24h temporary preview and adds it to the Study Queue,
// without opening Study Studio. Shared by the play and queue actions on a rec card.
// Pass silent=true from the inline play path so a background save doesn't reload the
// grid and tear out the iframe that just started playing.
async function queueRecommendationPreview(youtubeId, title, goalId, silent = false) {
    try {
        const formData = new FormData();
        formData.append('url', `https://www.youtube.com/watch?v=${youtubeId}`);
        formData.append('title', title);
        if (goalId) formData.append('goal_id', goalId);

        const res = await fetchAPI('/api/videos/preview', { method: 'POST', body: formData });
        if (res && res.video_id) {
            window._dailyRecsDrafts[youtubeId] = res.video_id;
            window._videoCardCache = window._videoCardCache || {};
            window._videoCardCache[res.video_id] = {
                id: res.video_id,
                youtube_id: youtubeId,
                title: title,
                learning_goal_id: goalId,
                is_temporary: 1,
                is_watchlist: 1,
                custom_notes: ''
            };
            if (silent) {
                markRecommendationQueued(youtubeId, res.video_id);
            } else {
                loadDailyRecommendations();
            }
        }
        return res;
    } catch (e) {
        console.error("Queue preview error:", e);
        if (typeof showToast === 'function') showToast("Could not add to queue: " + e.message, "failed");
        return null;
    }
}
window.queueRecommendationPreview = queueRecommendationPreview;

async function openRecommendationInStudio(youtubeId, title, goalId) {
    const res = await queueRecommendationPreview(youtubeId, title, goalId);
    if (res && res.video_id && typeof openStudyStudio === 'function') {
        openStudyStudio(res.video_id);
    }
}

async function dismissRecommendation(recId) {
    if (_activeInlineYtId === recId) {
        stopActiveInlineTracker();
    }
    try {
        const formData = new FormData();
        formData.append('youtube_id', recId);
        let res = await fetchAPI('/api/daily-recommendations/dismiss', { method: 'POST', body: formData });
        if (res && res.status === 'confirm') {
            // The preview of this video holds notes, and dismissing it removes them too.
            const confirmed = await showConfirm({
                title: 'Remove this video?',
                message: 'You have notes on this video. Removing it deletes the notes too.',
                confirmText: 'Remove',
                confirmClass: 'bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-xs shadow-sm transition',
                icon: 'trash-2'
            });
            if (!confirmed) return;
            formData.append('delete_notes', 'true');
            res = await fetchAPI('/api/daily-recommendations/dismiss', { method: 'POST', body: formData });
        }
        if (res && res.preview_removed) {
            delete window._dailyRecsDrafts[recId];
            if (typeof loadGoals === 'function') loadGoals();
            if (typeof loadDashboard === 'function') loadDashboard();
        }
        loadDailyRecommendations();
    } catch (e) {
        console.error("Dismiss failed:", e);
    }
}

async function refreshDailyRecommendations() {
    stopActiveInlineTracker();
    const btn = document.getElementById('btn-refresh-daily-recs');
    const icon = document.getElementById('icon-refresh-daily-recs');
    if (btn) btn.disabled = true;
    if (icon) icon.classList.add('animate-spin');

    try {
        await fetchAPI('/api/daily-recommendations/refresh', { method: 'POST' });
        await loadDailyRecommendations();
        if (typeof showToast === 'function') {
            showToast("Daily recommendations updated!", "saved", 2000);
        }
    } catch (e) {
        console.error("Daily recommendations refresh failed:", e);
        showToast("Failed to refresh recommendations: " + e.message, "failed");
    } finally {
        if (btn) btn.disabled = false;
        if (icon) icon.classList.remove('animate-spin');
    }
}

function updateStreakTimer() {
    const lastQuizAt = currentUserStats ? currentUserStats.last_quiz_at : null;
    const deadlineStr = currentUserStats ? currentUserStats.streak_deadline : null;

    const headerTimer = document.getElementById('header-streak-timer');
    const subtextEl = document.getElementById('stats-streak-subtext');

    const now = new Date();
    
    if (!lastQuizAt) {
        if (subtextEl) {
            subtextEl.textContent = 'Do 1 quiz to start your streak!';
            subtextEl.className = 'text-[11px] text-stone-500';
        }
        if (headerTimer) headerTimer.classList.add('hidden');
        return;
    }

    // The deadline is the server's (gamification.streak_deadline: midnight in the user's time
    // zone ending the day after the last quiz, so a quiz on day D survives through the end of
    // D+1). It is never
    // recomputed here. This used to be lastQuizAt + 24 rolling hours, the rule the backend had
    // already replaced for being wrong, and the two drifted for exactly as long as the number
    // lived in two places. With no deadline from the server, show nothing rather than a guess.
    if (!deadlineStr) {
        if (subtextEl) {
            subtextEl.textContent = '';
            subtextEl.className = 'text-[11px] text-stone-500';
        }
        if (headerTimer) headerTimer.classList.add('hidden');
        return;
    }

    const expireTime = parseDate(deadlineStr).getTime();
    const msLeft = expireTime - now.getTime();
    const hoursLeft = msLeft / (1000 * 60 * 60);

    if (msLeft <= 0) {
        // Expired!
        if (subtextEl) {
            subtextEl.textContent = 'Streak expired · Do 1 quiz to start!';
            subtextEl.className = 'text-[11px] text-stone-500';
        }
        if (headerTimer) headerTimer.classList.add('hidden');
        return;
    }

    if (hoursLeft <= 5) {
        // Warning mode: 5 hours or less remaining before the streak lapses
        const totalSecs = Math.floor(msLeft / 1000);
        const h = Math.floor(totalSecs / 3600);
        const m = Math.floor((totalSecs % 3600) / 60);
        const s = totalSecs % 60;

        const timeStr = `${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
        const shortTimeStr = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;

        if (subtextEl) {
            subtextEl.innerHTML = `<span class="text-amber-400 font-bold">Expires in ${timeStr}: Do 1 quiz!</span>`;
        }
        if (headerTimer) {
            headerTimer.textContent = shortTimeStr;
            headerTimer.classList.remove('hidden');
        }
    } else {
        // Safe mode (> 5 hours remaining)
        const totalSecs = Math.floor(msLeft / 1000);
        const h = Math.floor(totalSecs / 3600);
        const m = Math.floor((totalSecs % 3600) / 60);

        if (subtextEl) {
            subtextEl.innerHTML = `<span class="text-emerald-400 font-semibold">Protected for ${h}h ${m}m</span>`;
        }
        if (headerTimer) {
            headerTimer.classList.add('hidden');
        }
    }
}

// The streak the header last showed, null until the first server stats arrive, so the first
// render sets a baseline instead of animating.
let _headerStreakShown = null;

function updateHeaderStats() {
    const lvlEl = document.getElementById('header-level-val');
    if (lvlEl) lvlEl.textContent = currentUserStats.level || 1;
    
    const streakBadge = document.getElementById('top-streak-badge');
    const streakCount = document.getElementById('header-streak-count');
    
    if (streakBadge && streakCount) {
        const streak = currentUserStats.streak || 0;
        if (streak > 0) {
            streakCount.textContent = streak;
            streakBadge.classList.remove('hidden');
        } else {
            streakBadge.classList.add('hidden');
        }
        if (_headerStreakShown !== null && streak > _headerStreakShown) {
            playStatGrow(streakBadge.querySelector('.header-stat-icon'));
        }
        _headerStreakShown = streak;
    }

    updateStreakTimer();
}

window.updateStreakTimer = updateStreakTimer;

function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Restarts a CSS animation driven by a class: removing and re-adding it in the same frame would
// not replay it, so a forced reflow sits in between.
function restartAnimationClass(el, cls) {
    el.classList.remove(cls);
    void el.offsetWidth;
    el.classList.add(cls);
}

// Flame growth over the header streak icon (.header-stat-icon in style.css).
function playStatGrow(iconEl) {
    if (!iconEl || prefersReducedMotion()) return;
    restartAnimationClass(iconEl, 'is-growing');
    clearTimeout(iconEl._growTimer);
    iconEl._growTimer = setTimeout(() => iconEl.classList.remove('is-growing'), 1300);
}

// "New crystal!" dialog (partials/_crystal_earned.html). Resolves once it is closed, so the
// quiz flow can wait on it the way it waited on the confirm dialog before.
let _crystalEarnedResolve = null;

function showCrystalEarned(count) {
    return new Promise((resolve) => {
        const overlay = document.getElementById('overlay-crystal-earned');
        if (!overlay) { resolve(); return; }
        _crystalEarnedResolve = resolve;
        const msg = document.getElementById('crystal-earned-message');
        if (msg) msg.textContent = `That knowledge is locked in, Chompy can't eat it. You now have ${count} crystals.`;
        openOverlay('overlay-crystal-earned', closeCrystalEarned);
        const stage = overlay.querySelector('.crystal-stage');
        if (stage) restartAnimationClass(stage, 'is-playing');
        document.getElementById('btn-close-crystal-earned')?.focus();
    });
}

function closeCrystalEarned() {
    const overlay = document.getElementById('overlay-crystal-earned');
    overlay?.classList.add('hidden');
    overlay?.querySelector('.crystal-stage')?.classList.remove('is-playing');
    closeOverlay('overlay-crystal-earned');
    if (_crystalEarnedResolve) {
        const resolve = _crystalEarnedResolve;
        _crystalEarnedResolve = null;
        resolve();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-open-stats]').forEach((btn) => {
        btn.addEventListener('click', () => switchTab('stats'));
    });
    document.getElementById('btn-close-crystal-earned')?.addEventListener('click', closeCrystalEarned);
    document.getElementById('overlay-crystal-earned')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeCrystalEarned();
    });
    // The animation frames are CSS backgrounds, fetched only once an animation starts. Warm the
    // cache a little after load so the first play does not start on empty frames.
    if (!prefersReducedMotion()) {
        setTimeout(() => {
            ['streak-flame-grow.webp', 'crystal-grow.webp', 'crystal-shards.webp']
                .forEach((f) => { new Image().src = `/static/images/${f}`; });
        }, 3000);
    }
});

// Master initialization
window.addEventListener('DOMContentLoaded', () => {
    const savedUser = localStorage.getItem('active_username');
    if (savedUser) {
        document.cookie = `username=${savedUser}; path=/; max-age=31536000`;
    }

    if (typeof loadUserProfiles === 'function') loadUserProfiles();
    setInterval(updateStreakTimer, 1000);
    
    if (typeof checkConfig === 'function') checkConfig();
    if (typeof initImportTab === 'function') initImportTab();
    if (typeof initSettingsTab === 'function') initSettingsTab();
    if (typeof initSetupWizard === 'function') initSetupWizard();
    if (typeof initQuizEvents === 'function') initQuizEvents();
    if (typeof initGoalsModal === 'function') initGoalsModal();
    if (typeof initGoalsSearch === 'function') initGoalsSearch();
    if (typeof initGoalsActions === 'function') initGoalsActions();
    if (typeof initEditVideoEvents === 'function') initEditVideoEvents();
    if (typeof initFocusModalEvents === 'function') initFocusModalEvents();
    
    const savedTab = localStorage.getItem('active_studiamo_tab') || 'dashboard';
    switchTab(savedTab);
    // Reminder emails link to /#notifications (app/email_utils.py send_notification_email).
    if (window.location.hash === '#notifications' && typeof goToNotificationSettings === 'function') {
        goToNotificationSettings();
    }
    
    if (typeof checkOnboardingAndUpdates === 'function') {
        checkOnboardingAndUpdates();
    }

    // Awaits window.systemConfigReady internally, it needs app_mode to know whether
    // billing applies at all, and core.js fetches that asynchronously.
    if (typeof initPaywall === 'function') initPaywall();

    renderIcons();
});

function navigateToVideoInGoals(videoId) {
    if (!videoId) return;
    // An active search on the goals tab could hide the card this jumps to.
    if (typeof clearGoalsSearch === 'function') clearGoalsSearch();
    if (typeof switchTab === 'function') {
        switchTab('goals');
    }

    // loadGoals() (triggered by switchTab above) fetches and re-renders asynchronously, so
    // the card and window._videoCardCache may not exist yet on the first check, especially
    // right after an import. Poll for up to 3s rather than checking once and giving up.
    const deadline = Date.now() + 3000;
    const scrollToCard = () => {
        const cached = (window._videoCardCache && window._videoCardCache[videoId]) || null;
        const card = document.getElementById(`video-card-${videoId}`);
        if (!cached || !card) {
            if (Date.now() < deadline) setTimeout(scrollToCard, 150);
            return;
        }

        if (cached.is_watchlist === 1 || cached.is_watchlist === true) {
            const content = document.getElementById('content-watchlist');
            const chevron = document.getElementById('chevron-watchlist');
            if (content && content.classList.contains('hidden')) {
                content.classList.remove('hidden');
                if (chevron) chevron.classList.add('rotate-180');
                localStorage.setItem('accordion-open-watchlist', 'true');
            }
        } else if (cached.learning_goal_id) {
            const content = document.getElementById(`goal-materials-content-${cached.learning_goal_id}`);
            const chevron = document.getElementById(`goal-materials-chevron-${cached.learning_goal_id}`);
            if (content && content.classList.contains('hidden')) {
                content.classList.remove('hidden');
                if (chevron) chevron.classList.add('rotate-180');
                localStorage.setItem(`goal-materials-open-${cached.learning_goal_id}`, 'true');
            }
        } else {
            const content = document.getElementById('content-unassociated');
            const chevron = document.getElementById('chevron-unassociated');
            if (content && content.classList.contains('hidden')) {
                content.classList.remove('hidden');
                if (chevron) chevron.classList.add('rotate-180');
                localStorage.setItem('accordion-open-unassociated', 'true');
            }
        }

        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.add('ring-2', 'ring-amber-500', 'ring-offset-2');
        setTimeout(() => card.classList.remove('ring-2', 'ring-amber-500', 'ring-offset-2'), 2500);
    };
    setTimeout(scrollToCard, 350);
}

// Window bindings for inline HTML handlers
window.switchTab = switchTab;
window.loadDashboard = loadDashboard;
window.loadDailyRecommendations = loadDailyRecommendations;
window.refreshDailyRecommendations = refreshDailyRecommendations;
window.importRecommendedVideo = importRecommendedVideo;
window.dismissRecommendation = dismissRecommendation;
window.updateHeaderStats = updateHeaderStats;
window.navigateToVideoInGoals = navigateToVideoInGoals;


// ---- Chompy: "while you were away" --------------------------------------------------------

let _chompyAwayShown = false;
let _chompyAwayTimers = [];

function _chompyAwayShow(ids) {
    ['chompy-away-roll', 'chompy-away-full', 'chompy-away-tickle', 'chompy-away-footer']
        .forEach(id => document.getElementById(id).classList.toggle('hidden', !ids.includes(id)));
}

// Shown once per page load, and only when no other overlay (onboarding, paywall, what's new)
// has the screen; retried shortly after rather than stacked on top of one.
function maybeShowChompyAway(eaten, attempt = 0) {
    if (_chompyAwayShown || !eaten.length) return;
    const busy = Array.from(document.querySelectorAll('.app-overlay'))
        .some(el => el.id !== 'overlay-chompy-away' && !el.classList.contains('hidden'));
    if (busy) {
        if (attempt < 20) setTimeout(() => maybeShowChompyAway(eaten, attempt + 1), 3000);
        return;
    }
    _chompyAwayShown = true;
    _setChompyInfoOpen(false);

    const count = eaten.length;
    const title = document.getElementById('chompy-away-title');
    document.getElementById('chompy-away-bubble').textContent = `${count}x`;
    const done = () => {
        title.textContent = `Chompy ate ${count === 1 ? '1 quiz' : `${count} quizzes`} while you were away`;
    };

    if (count === 1) {
        // One quiz: tickle him to get it back.
        const v = eaten[0];
        title.textContent = `Chompy ate '${v.title || 'a quiz'}'`;
        document.getElementById('chompy-away-tickle-text').textContent =
            "Tickle him and he spits it back out. Finish the quiz and it's yours again.";
        const start = document.getElementById('chompy-away-start-btn');
        start.dataset.videoId = v.id;
        start.dataset.level = v.importance_rating || 3;
        start.classList.add('hidden');
        const btn = document.getElementById('chompy-away-tickle-btn');
        btn.classList.remove('hidden');
        btn.disabled = false;
        document.getElementById('chompy-away-tickle-img').src = CHOMPY_IMG.full;
        document.getElementById('chompy-away-tickle-speech').classList.add('hidden');
        // Loaded now, so the tickled pose is ready the moment the button is pressed.
        new Image().src = CHOMPY_IMG.tickled;
        _chompyAwayShow(['chompy-away-tickle']);
    } else if (count <= 4) {
        // Two to four: the notes roll into him (a GIF), then he sits there full with the count.
        title.textContent = 'While you were away...';
        _chompyAwayShow(['chompy-away-roll', 'chompy-away-footer']);
        _chompyAwayTimers.push(setTimeout(() => {
            done();
            _chompyAwayShow(['chompy-away-full', 'chompy-away-footer']);
            document.getElementById('chompy-away-bubble').classList.add('chompy-pop-in');
        }, 2200));
    } else {
        // More than four: just the count.
        done();
        _chompyAwayShow(['chompy-away-full', 'chompy-away-footer']);
    }

    openOverlay('overlay-chompy-away', closeChompyAway);
    if (typeof renderIcons === 'function') renderIcons();
}

function _setChompyInfoOpen(open) {
    document.getElementById('chompy-away-info-text').classList.toggle('hidden', !open);
    document.getElementById('chompy-away-info-btn').setAttribute('aria-expanded', String(open));
}

function closeChompyAway() {
    _chompyAwayTimers.forEach(clearTimeout);
    _chompyAwayTimers = [];
    const el = document.getElementById('overlay-chompy-away');
    if (el) {
        el.classList.add('hidden');
        closeOverlay('overlay-chompy-away');
    }
    fetchAPI('/api/chompy/seen', { method: 'POST' }).catch(e => console.warn('Chompy ack failed:', e));
}

// Starts the quiz of the one eaten video; finishing it wins the video back (grade_quiz).
function _winBackFromComeback(videoId, level) {
    closeChompyAway();
    if (typeof handleStudyButtonClick === 'function') handleStudyButtonClick(null, videoId, level);
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('chompy-away-close')?.addEventListener('click', closeChompyAway);
    document.getElementById('chompy-away-info-btn')?.addEventListener('click', (e) => {
        _setChompyInfoOpen(e.currentTarget.getAttribute('aria-expanded') !== 'true');
    });
    document.getElementById('chompy-away-later')?.addEventListener('click', closeChompyAway);
    // Tickling only plays his reaction; the quiz starts when the user asks for it.
    document.getElementById('chompy-away-tickle-btn')?.addEventListener('click', (e) => {
        const btn = e.currentTarget;
        const img = document.getElementById('chompy-away-tickle-img');
        const start = document.getElementById('chompy-away-start-btn');
        img.src = CHOMPY_IMG.tickled;
        img.classList.add('chompy-giggle');
        btn.disabled = true;
        document.getElementById('chompy-away-tickle-speech').classList.remove('hidden');
        document.getElementById('chompy-away-title').textContent = 'He spat it back out';
        document.getElementById('chompy-away-tickle-text').textContent =
            'Finish its quiz to win it back for good. Until then it stays paused.';
        _chompyAwayTimers.push(setTimeout(() => {
            img.classList.remove('chompy-giggle');
            btn.classList.add('hidden');
            start.classList.remove('hidden');
            start.focus();
        }, 900));
    });
    document.getElementById('chompy-away-start-btn')?.addEventListener('click', (e) => {
        const btn = e.currentTarget;
        _winBackFromComeback(Number(btn.dataset.videoId), Number(btn.dataset.level) || 3);
    });
});


// ---- Upcoming review schedule: collapsible, collapsed by default --------------------------

const _UPCOMING_EXPANDED_KEY = 'studiamo_upcoming_expanded';

function _setUpcomingExpanded(expanded) {
    const list = document.getElementById('upcoming-quizzes-list');
    const toggle = document.getElementById('upcoming-quizzes-toggle');
    const chevron = document.getElementById('upcoming-quizzes-chevron');
    if (list) list.classList.toggle('hidden', !expanded);
    if (toggle) toggle.setAttribute('aria-expanded', String(expanded));
    if (chevron) chevron.classList.toggle('rotate-180', expanded);
}

function initUpcomingToggle() {
    let expanded = false;
    try { expanded = localStorage.getItem(_UPCOMING_EXPANDED_KEY) === '1'; } catch (e) { /* storage unavailable */ }
    _setUpcomingExpanded(expanded);
    document.getElementById('upcoming-quizzes-toggle')?.addEventListener('click', () => {
        const next = document.getElementById('upcoming-quizzes-list')?.classList.contains('hidden');
        _setUpcomingExpanded(!!next);
        try { localStorage.setItem(_UPCOMING_EXPANDED_KEY, next ? '1' : '0'); } catch (e) { /* storage unavailable */ }
    });
}

document.addEventListener('DOMContentLoaded', initUpcomingToggle);


// ---- Chompy: conveyor belt and due cards ---------------------------------------------------

const CHOMPY_IMG = {
    full: '/static/images/chompy/chompy-full.png',
    hungry: '/static/images/chompy/chompy-hungry.png',
    chomping: '/static/images/chompy/chompy-chomping.png',
    tickled: '/static/images/chompy/chompy-tickled.png',
    icon: '/static/images/chompy/chompy-icon.png',
};

// Belt station from the server's days_until_eaten: 2 or more (or no Chompy clock yet) is
// "due today", 1 is one day over, 0 is two days over and gets eaten at the coming midnight.
function chompyStation(q) {
    const d = q.days_until_eaten;
    if (d === null || d === undefined || d >= 2) return 'today';
    return d === 1 ? 'over1' : 'over2';
}

// Up to three quizzes show as single notes; more collapse into one note with a count. An empty
// station leaves its stretch of belt bare.
function beltStackHTML(count) {
    if (count === 0) return '';
    const note = '<div class="belt-doc"><span></span><span></span><span></span>';
    if (count <= 3) return Array(count).fill(note + '</div>').join('');
    return `${note}<b class="belt-doc-badge">${count}x</b></div>`;
}

// Hourly creep along the belt. The server says how far into the user's local day it is
// (day_progress); the browser adds the time since then, so no further requests are needed.
// Each station spans 24 notches. At local midnight the dashboard reloads once, because that
// is when stations change and Chompy eats.
const BELT_STATIONS = ['today', 'over1', 'over2'];
let _beltClock = null;
let _beltTimer = null;
let _beltReloading = false;

function _beltHour() {
    if (!_beltClock) return 0;
    const elapsedDays = (Date.now() - _beltClock.at) / 86400000;
    return Math.floor((_beltClock.progress + elapsedDays) * 24);
}

function placeBeltGroups(instant = false) {
    const hour = _beltHour();
    if (hour >= 24) {
        if (!_beltReloading && typeof loadDashboard === 'function') {
            _beltReloading = true;
            _chompyAwayShown = false;
            loadDashboard();
        }
        return;
    }
    const frac = hour / 24;
    document.querySelectorAll('.belt-group[data-belt-station]').forEach(group => {
        const idx = BELT_STATIONS.indexOf(group.dataset.beltStation);
        // Left edge at the start of its third at 00:00, right edge at its end at 23:00 and on.
        if (instant) group.style.transition = 'none';
        group.style.left = `${((idx + frac) / 3) * 100}%`;
        group.style.transform = `translateX(-${frac * 100}%)`;
        if (instant) {
            void group.offsetWidth;
            group.style.transition = '';
        }
    });
}

function renderChompyBelt(dueQuizzes, dayProgress) {
    const belt = document.getElementById('due-quizzes-hero');
    if (!belt) return;
    belt.classList.remove('hidden');

    const counts = { today: 0, over1: 0, over2: 0 };
    dueQuizzes.forEach(info => { counts[chompyStation(info.quiz)]++; });
    belt.querySelectorAll('[data-belt-station]').forEach(el => {
        el.innerHTML = beltStackHTML(counts[el.dataset.beltStation]);
    });

    _beltClock = { progress: Number(dayProgress) || 0, at: Date.now() };
    _beltReloading = false;
    placeBeltGroups(true);
    if (!_beltTimer) _beltTimer = setInterval(() => placeBeltGroups(false), 60000);

    const total = dueQuizzes.length;
    document.getElementById('belt-headline').textContent =
        total === 0 ? 'All caught up' : `${total} ${total === 1 ? 'quiz' : 'quizzes'} to review`;

    // Asleep while nothing is overdue; awake (and hungry) once something is.
    const awake = counts.over1 + counts.over2 > 0;
    const img = document.getElementById('belt-chompy-img');
    img.src = awake ? CHOMPY_IMG.hungry : CHOMPY_IMG.full;
    img.alt = awake ? 'Chompy, awake and hungry' : 'Chompy, asleep';
    document.getElementById('belt-chompy-zz').classList.toggle('hidden', awake);
    img.dataset.state = awake ? 'awake' : 'asleep';
    const speech = document.getElementById('belt-chompy-speech');
    speech.textContent = counts.over2 > 0 ? 'Dinner is at midnight!' : (awake ? 'Dinner is tomorrow night' : '');
    speech.classList.toggle('hidden', !awake);

    // Plays the wake-up hop once, the first time this browser sees him awake again.
    let before = null;
    try { before = localStorage.getItem('studiamo_chompy_state'); } catch (e) { /* storage unavailable */ }
    const now = awake ? 'awake' : 'asleep';
    if (before === 'asleep' && now === 'awake') {
        img.classList.remove('chompy-wake');
        void img.offsetWidth;
        img.classList.add('chompy-wake');
    }
    try { localStorage.setItem('studiamo_chompy_state', now); } catch (e) { /* storage unavailable */ }
}

// Due quiz card, option C: tinted by station, Chompy peeking in bigger each day. "+1 Day" only
// while the quiz is due today; overdue quizzes can only be saved by doing them.
function renderDueCard(item) {
    const q = item.quiz;
    const station = chompyStation(q);
    const meta = {
        today: 'Due today',
        over1: '<span class="due-card-meta-over1">Chompy eats this tomorrow night</span>',
        over2: '<span class="due-card-meta-over2">Chompy eats this tonight</span>',
    }[station];
    const peek = { today: CHOMPY_IMG.icon, over1: CHOMPY_IMG.hungry, over2: CHOMPY_IMG.chomping }[station];

    const goalName = item.goal_title || (item.video ? item.video.goal_title : null);
    const goalStr = goalName ? ` • ${escapeHtml(goalName)}` : '';
    const titleAction = (item.video && item.video.id) ? `javascript:navigateToVideoInGoals(${item.video.id})` : 'javascript:void(0)';
    const videoId = item.video ? item.video.id : '';
    const level = item.video ? (item.video.importance_rating || 3) : 3;

    const username = typeof activeUsername !== 'undefined' ? activeUsername : 'default';
    const saved = localStorage.getItem(`quiz-progress-${username}-${q.id}`);
    const continued = (q.in_progress_index > 0) || (saved && parseInt(saved, 10) > 0);
    const startLabel = station === 'over2' ? 'Save it now' : (continued ? 'Continue Quiz' : 'Start Quiz');
    const startClass = station === 'over2' ? 'btn-save-now' : 'btn-primary';

    const thumbHTML = renderMediaThumbHTML(item.video, { sizeClasses: 'w-12 h-8', title: 'View Video in Goals' });

    return `
        <div class="due-card due-card-${station} rounded-xl p-3 flex flex-col justify-between space-y-2.5 shadow-sm">
            <div class="flex space-x-2.5 items-center min-w-0">
                <a href="${titleAction}" class="shrink-0">${thumbHTML}</a>
                <div class="min-w-0 flex-grow">
                    <a href="${titleAction}" class="font-bold text-xs text-stone-800 truncate hover:text-amber-700 block" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</a>
                    <p class="text-[10px] text-stone-500 mt-0.5">${q.mastered ? 'Mastered' : `Stage ${q.srs_stage}`} • ${meta}${goalStr}</p>
                </div>
            </div>
            <div class="flex items-center space-x-2 pt-1">
                <button type="button" data-start-quiz="${q.id}" data-video="${videoId}" data-level="${level}" class="${startClass} flex-grow py-1.5 font-extrabold rounded-lg text-xs transition flex items-center justify-center space-x-1 h-[32px]">
                    <i data-lucide="play" class="w-3 h-3"></i>
                    <span>${startLabel}</span>
                </button>
                ${station === 'today' ? `
                <button type="button" data-plus-day="${q.id}" class="py-1.5 px-2.5 bg-[#f3ebd9] hover:bg-[#e7dfd3] border border-[#e7dfd3] text-stone-700 hover:text-stone-900 font-semibold rounded-lg text-xs transition flex items-center justify-center space-x-1 h-[32px]" title="Move to tomorrow" aria-label="Move this quiz to tomorrow">
                    <i data-lucide="calendar-plus" class="w-3.5 h-3.5 text-amber-700"></i>
                    <span>+1 Day</span>
                </button>` : ''}
            </div>
            <img src="${peek}" alt="" class="due-card-peek">
        </div>
    `;
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('due-quizzes-list')?.addEventListener('click', (e) => {
        const start = e.target.closest('[data-start-quiz]');
        if (start) {
            const video = start.dataset.video ? Number(start.dataset.video) : null;
            startQuiz(Number(start.dataset.startQuiz), video, Number(start.dataset.level) || 3);
            return;
        }
        const plus = e.target.closest('[data-plus-day]');
        if (plus && typeof rescheduleQuiz === 'function') rescheduleQuiz(Number(plus.dataset.plusDay));
    });
});

// Easter egg: five quick taps on the header's Beta badge open a thank-you note. A pause longer
// than BETA_EGG_WINDOW_MS between taps starts the count over.
const BETA_EGG_TAPS = 5;
const BETA_EGG_WINDOW_MS = 1500;
let _betaEggCount = 0;
let _betaEggLastTap = 0;

function openBetaEgg() {
    openOverlay('overlay-beta-egg', closeBetaEgg);
    document.getElementById('btn-close-beta-egg')?.focus();
}

function closeBetaEgg() {
    document.getElementById('overlay-beta-egg')?.classList.add('hidden');
    closeOverlay('overlay-beta-egg');
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.beta-badge').forEach((badge) => {
        badge.addEventListener('click', () => {
            const now = Date.now();
            _betaEggCount = now - _betaEggLastTap > BETA_EGG_WINDOW_MS ? 1 : _betaEggCount + 1;
            _betaEggLastTap = now;
            if (_betaEggCount >= BETA_EGG_TAPS) {
                _betaEggCount = 0;
                openBetaEgg();
            }
        });
    });
    document.getElementById('btn-close-beta-egg')?.addEventListener('click', closeBetaEgg);
    // A tap on the dimmed backdrop closes it too, but not one inside the card.
    document.getElementById('overlay-beta-egg')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeBetaEgg();
    });
});
