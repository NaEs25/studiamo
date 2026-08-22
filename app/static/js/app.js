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
        
        if (typeof renderGoalBoxes === 'function' && data.goals) {
            renderGoalBoxes(data.goals);
        }

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
        
        const now = new Date();
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
            .filter(info => info !== null);

        const dueQuizzes = activeQuizzes.filter(info => parseDate(info.quiz.next_review_at) <= now);
        const upcomingQuizzes = activeQuizzes
            .filter(info => parseDate(info.quiz.next_review_at) > now)
            .sort((a, b) => parseDate(a.quiz.next_review_at) - parseDate(b.quiz.next_review_at));
            
        const dueCountText = document.getElementById('due-quizzes-count');
        const btnStartDue = document.getElementById('btn-start-due');
        
        if (dueHero && dueCountText && btnStartDue) {
            if (dueQuizzes.length > 0) {
                dueCountText.textContent = dueQuizzes.length;
                dueHero.classList.remove('hidden');
                
                const firstQ = dueQuizzes[0] && dueQuizzes[0].quiz ? dueQuizzes[0].quiz : null;
                const username = typeof activeUsername !== 'undefined' ? activeUsername : 'default';
                const savedIdx = firstQ ? localStorage.getItem(`quiz-progress-${username}-${firstQ.id}`) : null;
                const isHeroContinued = firstQ && ((firstQ.in_progress_index !== undefined && firstQ.in_progress_index !== null && firstQ.in_progress_index > 0) || (savedIdx && parseInt(savedIdx, 10) > 0));
                
                const heroSpan = btnStartDue.querySelector('span');
                if (heroSpan) {
                    heroSpan.textContent = isHeroContinued ? 'Continue Quiz' : 'Study Now';
                }
                
                btnStartDue.onclick = (e) => {
                    if (e) e.preventDefault();
                    const targetId = firstQ ? firstQ.id : null;
                    if (targetId && typeof startQuiz === 'function') {
                        startQuiz(targetId);
                    }
                };
            } else {
                dueHero.classList.add('hidden');
            }
        }
        const dueList = document.getElementById('due-quizzes-list');
        if (duePanel && dueList) {
            if (dueQuizzes.length > 0) {
                dueList.innerHTML = dueQuizzes.map(item => {
                    const q = item.quiz;
                    const dateVal = parseDate(q.next_review_at);
                    const diffMs = now - dateVal;
                    const diffHrs = Math.round(diffMs / 3600000);
                    const timeStr = diffHrs <= 0 ? 'Due now' : `Due ${diffHrs}h ago`;
                    const goalName = item.goal_title || (item.video ? item.video.goal_title : null);
                    const goalStr = goalName ? ` • ${goalName}` : '';

                    let titleAction = 'javascript:void(0)';
                    if (item.video && item.video.id) {
                        titleAction = `javascript:navigateToVideoInGoals(${item.video.id})`;
                    }

                    const videoId = item.video ? item.video.id : 'null';
                    const levelVal = item.video ? (item.video.importance_rating || 3) : 3;

                    const username = typeof activeUsername !== 'undefined' ? activeUsername : 'default';
                    const savedProgress = localStorage.getItem(`quiz-progress-${username}-${q.id}`);
                    const isContinued = (q.in_progress_index !== undefined && q.in_progress_index !== null && q.in_progress_index > 0) || (savedProgress && parseInt(savedProgress, 10) > 0);
                    const btnLabel = isContinued ? 'Continue Quiz' : 'Start Quiz';

                    const thumbHTML = renderMediaThumbHTML(item.video, {
                        sizeClasses: 'w-12 h-8',
                        title: 'View Video in Goals'
                    });

                    return `
                        <div class="bg-white rounded-xl p-3 flex flex-col justify-between space-y-2.5 border border-[#e7dfd3] hover:border-amber-500/40 transition shadow-sm">
                            <div class="flex space-x-2.5 items-center min-w-0">
                                <a href="${titleAction}" class="shrink-0">
                                    ${thumbHTML}
                                </a>
                                <div class="min-w-0 flex-grow">
                                    <a href="${titleAction}" class="font-bold text-xs text-stone-800 truncate hover:text-amber-700 block" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</a>
                                    <p class="text-[10px] text-stone-500 mt-0.5">Stage: ${q.srs_stage} • ${timeStr}${goalStr}</p>
                                </div>
                            </div>
                            <div class="flex items-center space-x-2 pt-1">
                                <button onclick="startQuiz(${q.id}, ${videoId}, ${levelVal})" class="btn-primary flex-grow py-1.5 font-extrabold rounded-lg text-xs transition flex items-center justify-center space-x-1 h-[32px]">
                                    <i data-lucide="play" class="w-3 h-3 fill-amber-900"></i>
                                    <span>${btnLabel}</span>
                                </button>
                                <button onclick="rescheduleQuiz(${q.id})" class="py-1.5 px-2.5 bg-[#f3ebd9] hover:bg-[#e7dfd3] border border-[#e7dfd3] text-stone-700 hover:text-stone-900 font-semibold rounded-lg text-xs transition flex items-center justify-center space-x-1 h-[32px]" title="Reschedule by 1 day" aria-label="Reschedule quiz by 1 day">
                                    <i data-lucide="calendar" class="w-3.5 h-3.5 text-amber-700"></i>
                                    <span>Reschedule</span>
                                </button>
                            </div>
                        </div>
                    `;
                }).join('');
                duePanel.classList.remove('hidden');
            } else {
                duePanel.classList.add('hidden');
            }
        }

        const upcomingList = document.getElementById('upcoming-quizzes-list');
        if (upcomingPanel && upcomingList) {
            if (upcomingQuizzes.length > 0) {
                upcomingList.innerHTML = upcomingQuizzes.map(item => {
                    const q = item.quiz;
                    const diffMs = parseDate(q.next_review_at) - now;
                    const diffMins = Math.round(diffMs / 60000);
                    let relativeStr = "";
                    if (diffMins < 60) {
                        relativeStr = `in ${diffMins} Min.`;
                    } else {
                        const diffHrs = Math.round(diffMins / 60);
                        if (diffHrs < 24) {
                            relativeStr = `in ${diffHrs} Std.`;
                        } else {
                            const diffDays = Math.round(diffHrs / 24);
                            relativeStr = `in ${diffDays} Tag(en)`;
                        }
                    }
                    const formattedDate = parseDate(q.next_review_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
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
    }
}

window._dailyRecsDrafts = window._dailyRecsDrafts || {};

function escapeRecQuotes(str) {
    if (!str) return '';
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function playInlineVideo(ytId, wrapperId) {
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return;
    wrapper.onclick = null;
    wrapper.removeAttribute('onclick');
    wrapper.classList.remove('cursor-pointer');
    wrapper.classList.add('yt-downscale-wrapper');
    wrapper.innerHTML = `
        <iframe class="w-full h-full border-0"
                src="https://www.youtube-nocookie.com/embed/${ytId}?autoplay=1&rel=0"
                frameborder="0"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen>
        </iframe>
    `;
}
window.playInlineVideo = playInlineVideo;

function playRecommendedVideo(ytId, wrapperId, title, goalId) {
    playInlineVideo(ytId, wrapperId);
    queueRecommendationPreview(ytId, title, goalId, true);
}
window.playRecommendedVideo = playRecommendedVideo;

function playVideoModal(ytId, title) {
    const modal = document.getElementById('overlay-rec-player') || document.getElementById('overlay-video-player');
    const iframe = document.getElementById('rec-player-iframe');
    const titleEl = document.getElementById('rec-player-title') || document.getElementById('video-player-title');

    if (titleEl) titleEl.textContent = title || 'YouTube Player';
    if (iframe) {
        iframe.src = `https://www.youtube-nocookie.com/embed/${ytId}?autoplay=1&rel=0`;
    }
    if (modal) modal.classList.remove('hidden');
    if (typeof renderIcons === 'function') renderIcons();
    else if (typeof lucide !== 'undefined') lucide.createIcons();
}
window.playVideoModal = playVideoModal;

async function loadDailyRecommendations() {
    const grid = document.getElementById('daily-recommendations-grid');
    const panel = document.getElementById('daily-recommendations-panel');
    if (!grid) return;

    try {
        const data = await fetchAPI('/api/daily-recommendations');
        if (panel) panel.classList.remove('hidden');

        const dateEl = document.getElementById('daily-recs-date');
        if (dateEl) dateEl.textContent = data.date ? `For ${data.date}` : '';

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
            const isDraft = Boolean(rec.is_temporary === 1 || rec.is_temporary === true || (draftVideoId && window._dailyRecsDrafts[ytId]));
            const isQueued = Boolean(draftVideoId);
            const thumbUrl = rec.thumbnail_url || rec.thumbnail || (ytId ? `https://img.youtube.com/vi/${ytId}/hqdefault.jpg` : '/static/images/notes-icon.svg');
            const cleanTitle = escapeRecQuotes(rec.title || '');
            const wrapperId = `media-wrapper-${ytId}`;

            let progressPercent = 0;
            const lastPos = parseFloat(rec.last_position_seconds) || 0;
            const durSec = parseFloat(rec.duration_seconds) || 0;
            if (lastPos > 0 && durSec > 0) {
                progressPercent = Math.min(100, Math.round((lastPos / durSec) * 100));
            }

            return `
                <div class="bg-white border border-stone-200/90 rounded-2xl overflow-hidden flex flex-col justify-between hover:border-amber-400 hover:shadow-md transition-all duration-200 relative group select-none">
                    <!-- Inline Playable Media Wrapper -->
                    <div id="${wrapperId}" class="w-full aspect-video relative overflow-hidden bg-stone-900 cursor-pointer group" onclick="playRecommendedVideo('${ytId}', '${wrapperId}', '${cleanTitle}', '${rec.goal_id || ''}')">
                        <img src="${thumbUrl}"
                             class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                             draggable="false"
                             onerror="this.src='/static/images/notes-icon.svg'">
                        
                        <!-- Goal Badge (Top-Left) -->
                        <span class="absolute top-2 left-2 z-10 bg-amber-500/20 backdrop-blur-xs border border-amber-500/40 text-amber-900 text-[9px] font-extrabold px-2 py-0.5 rounded-md flex items-center space-x-1">
                            <i data-lucide="target" class="w-3 h-3 text-amber-900"></i>
                            <span class="truncate max-w-[120px]">${rec.goal_title || 'AI Recommendation'}</span>
                        </span>

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
                                <span>${rec.views}</span>
                            </span>
                        ` : ''}

                        <!-- Duration Badge (Bottom-Right, Compact) -->
                        ${rec.duration && rec.duration !== 'N/A' ? `
                            <span class="absolute bottom-2 right-2 z-10 bg-white/70 text-stone-900/80 text-[10px] font-extrabold px-1.5 py-0.5 rounded-md flex items-center space-x-1">
                                <i data-lucide="clock" class="w-3 h-3 text-stone-900/80"></i>
                                <span>${rec.duration}</span>
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
                    <div class="p-4 flex-grow flex flex-col justify-between space-y-3 bg-white">
                        <div class="space-y-1.5">
                            <h4 class="font-bold text-sm text-stone-900 leading-snug line-clamp-2 hover:text-amber-700 transition-colors cursor-pointer"
                                onclick="playRecommendedVideo('${ytId}', '${wrapperId}', '${cleanTitle}', '${rec.goal_id || ''}')">
                                ${escapeHtml(rec.title)}
                            </h4>
                            <div class="flex items-center text-xs text-stone-500 pt-0.5">
                                <span class="flex items-center space-x-1 truncate" title="${escapeHtml(rec.channel) || ''}">
                                    ${rec.channel ? `
                                        <i data-lucide="youtube" class="w-3.5 h-3.5 text-red-600 shrink-0"></i>
                                        <span class="truncate">${escapeHtml(rec.channel)}</span>
                                    ` : ''}
                                </span>
                            </div>
                        </div>

                        <!-- Action Bar -->
                        <div class="flex items-center space-x-2 pt-2.5">
                            ${isQueued ? `
                                <button id="btn-queue-${ytId}" onclick="navigateToVideoInGoals(${draftVideoId})" class="btn-primary flex-grow py-2 px-3 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 active:scale-[0.98]">
                                    <i data-lucide="bookmark" class="w-3.5 h-3.5 fill-current"></i>
                                    <span>View in Queue</span>
                                </button>
                            ` : `
                                <button id="btn-queue-${ytId}" onclick="queueRecommendationPreview('${ytId}', '${cleanTitle}', '${rec.goal_id || ''}')" class="btn-primary flex-grow py-2 px-3 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 active:scale-[0.98]">
                                    <i data-lucide="bookmark" class="w-3.5 h-3.5"></i>
                                    <span>Add to Queue</span>
                                </button>
                            `}
                            <button onclick="openRecommendationInStudio('${ytId}', '${cleanTitle}', '${rec.goal_id || ''}')" class="p-2 bg-stone-100 hover:bg-amber-100 text-stone-700 hover:text-amber-900 border border-stone-200 rounded-xl transition flex items-center justify-center min-w-[38px] h-[38px] shadow-sm" title="Open Study Studio (Notes)">
                                <i data-lucide="book-open" class="w-4 h-4"></i>
                            </button>
                            <button onclick="dismissRecommendation('${ytId}')" class="p-2 bg-stone-100 hover:bg-red-100 text-stone-500 hover:text-red-700 border border-stone-200 rounded-xl transition flex items-center justify-center min-w-[38px] h-[38px] shadow-sm" title="Dismiss">
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
        if (typeof showToast === 'function') {
            showToast("Import failed: " + e.message, "failed");
        } else {
            alert("Import failed: " + e.message);
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Swaps a single rec card's primary button to "View in Queue" in place, without
// reloading the grid, a full reload would tear out an inline video mid-playback.
function markRecommendationQueued(youtubeId, videoId) {
    const btn = document.getElementById(`btn-queue-${youtubeId}`);
    if (!btn) return;
    btn.setAttribute('onclick', `navigateToVideoInGoals(${videoId})`);
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
    try {
        const formData = new FormData();
        formData.append('youtube_id', recId);
        await fetchAPI('/api/daily-recommendations/dismiss', { method: 'POST', body: formData });
        loadDailyRecommendations();
    } catch (e) {
        console.error("Dismiss failed:", e);
    }
}

async function refreshDailyRecommendations() {
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
        if (typeof showToast === 'function') {
            showToast("Failed to refresh recommendations: " + e.message, "failed");
        } else {
            alert("Failed to refresh recommendations: " + e.message);
        }
    } finally {
        if (btn) btn.disabled = false;
        if (icon) icon.classList.remove('animate-spin');
    }
}

function updateStreakTimer() {
    const streakCount = currentUserStats ? (currentUserStats.streak || 0) : 0;
    const lastQuizAt = currentUserStats ? currentUserStats.last_quiz_at : null;

    const headerTimer = document.getElementById('header-streak-timer');
    const subtextEl = document.getElementById('stats-streak-subtext');
    const fireIcon = document.getElementById('streak-fire-icon');

    const now = new Date();
    
    if (!lastQuizAt) {
        if (subtextEl) {
            subtextEl.textContent = 'Do 1 quiz to start your streak!';
            subtextEl.className = 'text-[11px] text-stone-500';
        }
        if (headerTimer) headerTimer.classList.add('hidden');
        if (fireIcon) fireIcon.className = 'p-3 bg-amber-500/10 rounded-full border border-amber-500/20 text-amber-500';
        return;
    }

    const lastDate = parseDate(lastQuizAt);
    if (!lastDate) return;

    // 24-hour expiration deadline from last quiz completion
    const expireTime = lastDate.getTime() + (24 * 60 * 60 * 1000);
    const msLeft = expireTime - now.getTime();
    const hoursLeft = msLeft / (1000 * 60 * 60);

    if (msLeft <= 0) {
        // Expired!
        if (subtextEl) {
            subtextEl.textContent = 'Streak expired · Do 1 quiz to start!';
            subtextEl.className = 'text-[11px] text-stone-500';
        }
        if (headerTimer) headerTimer.classList.add('hidden');
        if (fireIcon) fireIcon.className = 'p-3 bg-amber-500/10 rounded-full border border-amber-500/20 text-amber-500';
        return;
    }

    if (hoursLeft <= 5) {
        // Warning mode: 5 hours or less remaining before 24h expiration
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
        if (fireIcon) {
            fireIcon.className = 'p-3 bg-red-500/10 rounded-full border border-red-500/30 text-red-400';
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
        if (fireIcon) {
            fireIcon.className = 'p-3 bg-emerald-500/10 rounded-full border border-emerald-500/20 text-emerald-400';
        }
    }
}

function updateHeaderStats() {
    const lvlEl = document.getElementById('header-level-val');
    if (lvlEl) lvlEl.textContent = currentUserStats.level || 1;
    
    const streakBadge = document.getElementById('top-streak-badge');
    const streakCount = document.getElementById('header-streak-count');
    
    if (streakBadge && streakCount) {
        if (currentUserStats.streak > 0) {
            streakCount.textContent = currentUserStats.streak;
            streakBadge.classList.remove('hidden');
        } else {
            streakBadge.classList.add('hidden');
        }
    }

    updateStreakTimer();
}

window.updateStreakTimer = updateStreakTimer;

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
    if (typeof initEditVideoEvents === 'function') initEditVideoEvents();
    if (typeof initFocusModalEvents === 'function') initFocusModalEvents();
    
    const savedTab = localStorage.getItem('active_studiamo_tab') || 'dashboard';
    switchTab(savedTab);
    
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
    if (typeof switchTab === 'function') {
        switchTab('goals');
    }
    const scrollToCard = () => {
        const cached = (window._videoCardCache && window._videoCardCache[videoId]) || null;
        if (cached) {
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
            }
        }
        const card = document.getElementById(`video-card-${videoId}`);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.classList.add('ring-2', 'ring-amber-500', 'ring-offset-2');
            setTimeout(() => card.classList.remove('ring-2', 'ring-amber-500', 'ring-offset-2'), 2500);
        }
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
