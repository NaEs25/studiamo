// --- Studiamo Goals Module ---

async function loadGoals() {
    try {
        const data = await fetchAPI('/api/dashboard');
        const goals = data.goals || [];
        const archivedGoals = data.archived_goals || [];
        const videos = data.videos || [];
        const quizzes = data.quizzes || [];

        // Cache video data for context operations
        window._videoCardCache = {};
        [...videos, ...(data.archived || [])].forEach(v => {
            window._videoCardCache[v.id] = v;
        });

        // 1. Render Watchlist Queue at top if populated
        const watchlistContainer = document.getElementById('goals-watchlist-container');
        if (watchlistContainer) {
            const watchlistVideos = videos.filter(v => v.is_watchlist === 1);
            if (watchlistVideos.length > 0) {
                const isWatchlistOpen = localStorage.getItem('accordion-open-watchlist') !== 'false';
                watchlistContainer.innerHTML = `
                    <div class="bg-[#fbf8f2] border border-[#e7dfd3] rounded-2xl overflow-hidden mb-6 shadow-sm">
                        <button onclick="toggleAccordion('watchlist')" class="w-full flex justify-between items-center px-5 py-4 bg-[#f7f2e8] hover:bg-[#f3ebd9] transition text-left">
                            <span class="flex items-center space-x-2.5 font-bold">
                                <i data-lucide="bookmark" class="w-5 h-5 text-amber-600 fill-amber-500"></i>
                                <span class="text-stone-800">Study Queue / Watchlist</span>
                                <span class="text-xs bg-amber-500/20 text-amber-800 px-2 py-0.5 rounded-full font-semibold border border-amber-500/30">${watchlistVideos.length}</span>
                            </span>
                            <i data-lucide="chevron-down" id="chevron-watchlist" class="w-5 h-5 text-amber-600 transition-transform ${isWatchlistOpen ? 'rotate-180' : ''}"></i>
                        </button>
                        
                        <div id="content-watchlist" class="p-4 space-y-4 ${isWatchlistOpen ? '' : 'hidden'}">
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                                ${watchlistVideos.map(item => renderVideoCard(item, quizzes, goals)).join('')}
                            </div>
                        </div>
                    </div>
                `;
            } else {
                watchlistContainer.innerHTML = '';
            }
        }

        window._goalsCache = {};
        goals.forEach(g => { window._goalsCache[g.id] = g; });
        if (typeof renderGoalBoxes === 'function') renderGoalBoxes(goals);

        // 2. Render Active Goals Grid
        const container = document.getElementById('goals-container');
        if (container) {
            container.innerHTML = '';
            if (goals.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-16 px-6 bg-white rounded-3xl border border-dashed border-amber-500/30 shadow-xl max-w-xl mx-auto my-6 space-y-5">
                        <div class="w-20 h-20 bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-3xl flex items-center justify-center mx-auto shadow-inner">
                            <i data-lucide="target" class="w-10 h-10"></i>
                        </div>
                        <div class="space-y-2">
                            <h3 class="text-2xl font-extrabold text-stone-900 tracking-tight">Set Your First Learning Goal</h3>
                            <p class="text-xs text-stone-500 max-w-md mx-auto leading-relaxed">
                                Goals keep your learning structured and focused. Create your first goal to begin mapping YouTube videos, documents, and active recall quizzes.
                            </p>
                        </div>
                        <div class="pt-3">
                            <button type="button" onclick="openCreateGoalModal()" class="btn-primary px-8 py-4 font-extrabold text-sm rounded-2xl transition transform hover:-translate-y-0.5 inline-flex items-center space-x-2">
                                <i data-lucide="plus-circle" class="w-5 h-5"></i>
                                <span>+ Create First Goal</span>
                            </button>
                        </div>
                    </div>
                `;
                if (typeof renderIcons === 'function') renderIcons();
            } else {
                goals.forEach((g, index) => {
                    const rankNumber = index + 1;
                    const goalVideos = videos.filter(v => v.learning_goal_id === g.id && v.is_watchlist !== 1);
                    const isMaterialsOpen = localStorage.getItem(`goal-materials-open-${g.id}`) === 'true';
                    
                    let linkedVideoCardsHTML = '';
                    if (goalVideos.length === 0) {
                        linkedVideoCardsHTML = `<p class="text-xs text-stone-400 italic py-2 pl-2">No learning materials added to this goal yet.</p>`;
                    } else {
                        linkedVideoCardsHTML = goalVideos.map(v => renderVideoCard(v, quizzes, goals)).join('');
                    }

                    const isDrawerOpen = Boolean(window._openGoalRecommendations && window._openGoalRecommendations[g.id]);
                    const hasSavedRecs = Boolean(g.has_saved_recommendations);
                    const recsBtnLabel = (isDrawerOpen || hasSavedRecs) ? 'View AI Recommendations' : 'Get AI Recommendations';

                    const cardHTML = `
                        <div class="bg-white border border-stone-200 p-5 rounded-2xl space-y-4 shadow-sm relative group">
                            <div class="flex justify-between items-start">
                                <div class="flex flex-col min-w-0">
                                    <div class="flex items-center space-x-3">
                                        <div class="w-8 h-8 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 font-bold text-xs shrink-0">
                                            #${rankNumber}
                                        </div>
                                        <h3 class="font-bold text-lg text-stone-900 leading-tight">${g.title}</h3>
                                    </div>
                                    ${g.description ? `<p class="text-xs text-stone-500 mt-1 ml-11">${g.description}</p>` : ''}
                                </div>
                                
                                <div class="flex items-center space-x-1 shrink-0 bg-stone-100 border border-stone-200 rounded-xl p-1">
                                    <button onclick="reorderGoal(${g.id}, 'up')" ${index === 0 ? 'disabled class="p-1 text-stone-300 cursor-not-allowed"' : 'class="p-1 text-stone-600 hover:text-amber-600 transition"'} title="Move Priority Up (Rank #${rankNumber - 1})">
                                        <i data-lucide="arrow-up" class="w-4 h-4"></i>
                                    </button>
                                    <button onclick="reorderGoal(${g.id}, 'down')" ${index === goals.length - 1 ? 'disabled class="p-1 text-stone-300 cursor-not-allowed"' : 'class="p-1 text-stone-600 hover:text-amber-600 transition"'} title="Move Priority Down (Rank #${rankNumber + 1})">
                                        <i data-lucide="arrow-down" class="w-4 h-4"></i>
                                    </button>
                                    <div class="w-px h-4 bg-stone-100 mx-0.5"></div>
                                    <button onclick="toggleGoalMenu(event, ${g.id})" id="btn-goal-menu-${g.id}" class="p-1 text-stone-600 hover:text-stone-900 transition" title="Goal Options">
                                        <i data-lucide="more-vertical" class="w-4 h-4"></i>
                                    </button>
                                </div>
                            </div>

                            <div class="space-y-3 pt-1">
                                <div class="flex justify-between items-center">
                                    <button onclick="toggleGoalMaterials(${g.id})" class="flex items-center space-x-2 text-xs font-bold text-stone-700 hover:text-amber-600 transition">
                                        <i data-lucide="folder" class="w-4 h-4 text-amber-600"></i>
                                        <span>Sources &amp; Materials</span>
                                        <span class="text-[10px] bg-amber-500/20 text-amber-700 px-2 py-0.5 rounded-full font-bold">${goalVideos.length}</span>
                                    </button>
                                    <i data-lucide="chevron-down" id="goal-materials-chevron-${g.id}" onclick="toggleGoalMaterials(${g.id})" class="w-4 h-4 text-stone-400 cursor-pointer transition-transform ${isMaterialsOpen ? 'rotate-180' : ''}"></i>
                                </div>

                                <div id="goal-materials-content-${g.id}" class="space-y-3 ${isMaterialsOpen ? '' : 'hidden'}">
                                    ${linkedVideoCardsHTML}
                                </div>
                            </div>

                            <div class="flex gap-2 pt-1">
                                <button id="btn-recs-trigger-${g.id}" data-has-saved-recs="${g.has_saved_recommendations ? 1 : 0}" onclick="loadRecommendations(${g.id}, this)" class="flex-grow py-1.5 px-3 bg-[#fbf8f2] hover:bg-[#f3ebd9] text-stone-800 border border-[#e7dfd3] font-semibold rounded-lg text-xs transition flex items-center justify-center space-x-1.5 shadow-sm">
                                    <i data-lucide="compass" class="w-3.5 h-3.5 text-stone-600"></i>
                                    <span class="recs-btn-text">${recsBtnLabel}</span>
                                </button>
                                
                                <button disabled class="flex-grow py-1.5 px-3 bg-amber-500/10 text-amber-900/60 border border-amber-500/20 font-semibold rounded-lg text-xs flex items-center justify-center space-x-1.5 cursor-not-allowed opacity-75 shadow-2xs">
                                    <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-700/60"></i>
                                    <span>Coming Soon</span>
                                </button>
                            </div>
                            
                            <div id="recs-${g.id}" class="${isDrawerOpen ? '' : 'hidden'} p-3.5 bg-[#fbf8f2] border border-[#e7dfd3] rounded-xl space-y-3 shadow-xs">
                                <div class="flex items-start justify-between pb-2 border-b border-[#e7dfd3]/80 gap-2">
                                    <div class="flex items-start space-x-1.5 min-w-0 flex-1">
                                        <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-700 shrink-0 mt-0.5"></i>
                                        <span class="text-xs font-bold text-stone-800 shrink-0 mt-0.5">Concepts:</span>
                                        <div id="concepts-${g.id}" class="text-[11px] text-stone-600 leading-relaxed break-words flex-1"></div>
                                    </div>
                                    <div class="flex items-center space-x-1 shrink-0">
                                        <button onclick="reloadGoalRecommendations(${g.id}, this)" class="p-1.5 bg-stone-100 hover:bg-stone-200/80 text-stone-600 hover:text-amber-800 rounded-lg transition border border-stone-200/80 shadow-2xs" title="Reload Recommendations">
                                            <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
                                        </button>
                                        <button onclick="closeRecommendationsDrawer(${g.id})" class="p-1.5 hover:bg-stone-200/80 text-stone-400 hover:text-stone-700 rounded-lg transition ml-0.5" title="Collapse Panel">
                                            <i data-lucide="x" class="w-4 h-4"></i>
                                        </button>
                                    </div>
                                </div>
                                <div id="vids-${g.id}" class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]"></div>
                            </div>
                        </div>
                    `;

                    container.innerHTML += cardHTML;
                });

                goals.forEach(g => {
                    if (window._openGoalRecommendations && window._openGoalRecommendations[g.id]) {
                        populateRecommendationDrawer(g.id, window._openGoalRecommendations[g.id]);
                    }
                });
            }
        }

        // 3. Render Unassociated Videos Container
        const unassociatedContainer = document.getElementById('goals-unassociated-container');
        if (unassociatedContainer) {
            const unassociatedVideos = videos.filter(v => !v.learning_goal_id && v.is_watchlist !== 1);
            if (unassociatedVideos.length > 0) {
                const isUnassocOpen = localStorage.getItem('accordion-open-unassociated') === 'true';
                unassociatedContainer.innerHTML = `
                    <div class="bg-white border border-stone-200 rounded-2xl overflow-hidden mt-6 mb-4 shadow-sm">
                        <div class="w-full flex justify-between items-center px-5 py-4 bg-stone-100 hover:bg-stone-200 transition text-left cursor-pointer" onclick="toggleAccordion('unassociated')">
                            <span class="flex items-center space-x-2.5 font-bold">
                                <i data-lucide="help-circle" class="w-5 h-5 text-amber-400"></i>
                                <span class="text-stone-900">Unassociated / Quick Review Material</span>
                                <span class="text-xs bg-stone-200 text-stone-500 px-2 py-0.5 rounded-full font-semibold">${unassociatedVideos.length}</span>
                            </span>
                            <i data-lucide="chevron-down" id="chevron-unassociated" class="w-5 h-5 text-stone-400 transition-transform ${isUnassocOpen ? 'rotate-180' : ''}"></i>
                        </div>
                        
                        <div id="content-unassociated" class="p-4 space-y-4 ${isUnassocOpen ? '' : 'hidden'}">
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                                ${unassociatedVideos.map(item => renderVideoCard(item, quizzes, goals)).join('')}
                            </div>
                        </div>
                    </div>
                `;
            } else {
                unassociatedContainer.innerHTML = '';
            }
        }

        // 4. Render Archived Goals & Videos Section
        const archivedVids = data.archived || [];
        const totalArchivedCount = (archivedGoals ? archivedGoals.length : 0) + archivedVids.length;
        const archivedSection = document.getElementById('goals-archived-section');
        if (archivedSection) {
            if (totalArchivedCount > 0) {
                archivedSection.classList.remove('hidden');
            } else {
                archivedSection.classList.add('hidden');
            }
        }

        const archivedCountEl = document.getElementById('archived-goals-count');
        if (archivedCountEl) {
            archivedCountEl.textContent = `${archivedGoals.length} Goals`;
        }
        const archivedList = document.getElementById('archived-goals-list');
        if (archivedList) {
            archivedList.innerHTML = '';
            if (archivedGoals.length === 0) {
                archivedList.innerHTML = `<p class="text-xs text-stone-400 py-3 text-center">No archived learning goals.</p>`;
            } else {
                archivedGoals.forEach(g => {
                    archivedList.innerHTML += `
                        <div class="flex items-center justify-between p-3 bg-stone-50 border border-stone-200 rounded-xl">
                            <div class="min-w-0">
                                <span class="block text-xs font-bold text-stone-900">${g.title}</span>
                                ${g.description ? `<p class="text-[10px] text-stone-400 truncate max-w-xs md:max-w-md" title="${g.description}">${g.description}</p>` : ''}
                            </div>
                            <div class="flex items-center space-x-1 shrink-0 ml-4 bg-stone-100 border border-stone-200 rounded-xl p-0.5">
                                <button onclick="archiveGoal(${g.id})" class="p-1 text-stone-400 hover:text-emerald-500 transition" title="Restore Goal to Active">
                                    <i data-lucide="rotate-ccw" class="w-4 h-4"></i>
                                </button>
                                <button onclick="deleteGoal(${g.id})" class="p-1 text-stone-400 hover:text-red-400 transition" title="Delete Goal Permanently">
                                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                                </button>
                            </div>
                        </div>
                    `;
                });
            }
        }

        const archivedVidsCountEl = document.getElementById('archived-videos-count');
        const archivedVidsList = document.getElementById('archived-videos-list');
        if (archivedVidsCountEl) {
            archivedVidsCountEl.textContent = `${archivedVids.length} Videos`;
        }
        if (archivedVidsList) {
            archivedVidsList.innerHTML = '';
            if (archivedVids.length === 0) {
                archivedVidsList.innerHTML = `<p class="text-xs text-stone-400 py-3 text-center col-span-full">No archived videos or materials.</p>`;
            } else {
                archivedVidsList.innerHTML = archivedVids.map(item => renderVideoCard(item, quizzes, goals)).join('');
            }
        }

        renderIcons();
    } catch (e) {
        console.error("Goals load error:", e);
    }
}

function initGoalsModal() {
    const overlay = document.getElementById('overlay-goal-modal');
    const btnAdd = document.getElementById('btn-add-goal-modal');
    const btnClose = document.getElementById('btn-close-goal-modal');
    const form = document.getElementById('goal-modal-form');
    
    if (btnAdd) {
        btnAdd.addEventListener('click', () => openCreateGoalModal());
    }
    
    if (btnClose) {
        btnClose.addEventListener('click', () => closeCreateGoalModal());
    }
    
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('goal-modal-id').value;
            const title = document.getElementById('goal-modal-title').value;
            const desc = document.getElementById('goal-modal-desc').value;
            
            const formData = new FormData();
            formData.append('title', title);
            formData.append('description', desc);
            
            const url = id ? `/api/goals/${id}/edit` : '/api/goals';
            
            try {
                await fetchAPI(url, {
                    method: 'POST',
                    body: formData
                });
                closeCreateGoalModal();
                loadGoals();
                if (typeof loadDashboard === 'function') loadDashboard();
            } catch (err) {
                console.error(err);
                if (typeof showToast === 'function') {
                    showToast("Failed to save goal: " + err.message, "failed");
                } else {
                    alert("Failed to save goal: " + err.message);
                }
            }
        });
    }
}

function openCreateGoalModal() {
    const overlay = document.getElementById('overlay-goal-modal');
    if (!overlay) return;
    document.getElementById('goal-modal-id').value = '';
    document.getElementById('goal-modal-title').value = '';
    document.getElementById('goal-modal-desc').value = '';
    overlay.querySelector('h3 span').textContent = "Create Learning Goal";
    overlay.classList.remove('hidden');
}

function closeCreateGoalModal() {
    const overlay = document.getElementById('overlay-goal-modal');
    if (!overlay) return;
    overlay.classList.add('hidden');
    document.getElementById('goal-modal-id').value = '';
    document.getElementById('goal-modal-title').value = '';
    document.getElementById('goal-modal-desc').value = '';
}

function openEditGoalModal(id, title, description) {
    document.getElementById('goal-modal-id').value = id;
    document.getElementById('goal-modal-title').value = title;
    document.getElementById('goal-modal-desc').value = description || '';
    
    const overlay = document.getElementById('overlay-goal-modal');
    if (overlay) {
        overlay.querySelector('h3 span').textContent = "Edit Learning Goal";
        overlay.classList.remove('hidden');
    }
}

async function reorderGoal(id, direction) {
    const formData = new FormData();
    formData.append('direction', direction);
    try {
        await fetchAPI(`/api/goals/${id}/reorder`, {
            method: 'POST',
            body: formData
        });
        loadGoals();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        console.error("Failed to reorder goal:", e);
    }
}

async function archiveGoal(id) {
    try {
        await fetchAPI(`/api/goals/${id}/archive`, { method: 'POST' });
        loadGoals();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        console.error("Archive goal failed:", e);
    }
}

function deleteGoal(id) {
    const goal = window._goalsCache && window._goalsCache[id];
    const title = goal ? goal.title : `Goal #${id}`;
    
    const hiddenId = document.getElementById('delete-goal-modal-id');
    const msg = document.getElementById('delete-goal-modal-msg');
    const modal = document.getElementById('overlay-delete-goal-modal');
    
    if (hiddenId) hiddenId.value = id;
    if (msg) {
        msg.innerHTML = `Are you sure you want to delete learning goal <strong class="text-stone-900">"${title}"</strong>?<br><span class="text-xs text-stone-500 mt-2 block">Choose how to handle the linked video materials:</span>`;
    }
    if (modal) {
        modal.classList.remove('hidden');
        renderIcons();
    }
}

function closeDeleteGoalModal() {
    const modal = document.getElementById('overlay-delete-goal-modal');
    if (modal) modal.classList.add('hidden');
}

async function confirmDeleteGoal(deleteMaterials) {
    const hiddenId = document.getElementById('delete-goal-modal-id');
    const id = hiddenId ? hiddenId.value : null;
    if (!id) return;
    
    closeDeleteGoalModal();
    showLoader("Deleting Learning Goal", deleteMaterials ? "Removing goal and purging linked materials..." : "Removing goal and unassociating materials...");
    
    try {
        await fetchAPI(`/api/goals/${id}?delete_materials=${deleteMaterials}`, { method: 'DELETE' });
        hideLoader();
        loadGoals();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        hideLoader();
        console.error("Delete goal error:", e);
        if (typeof showToast === 'function') {
            showToast("Failed to delete goal: " + e.message, "failed");
        } else {
            alert("Failed to delete goal: " + e.message);
        }
    }
}

function toggleGoalMaterials(goalId) {
    const content = document.getElementById(`goal-materials-content-${goalId}`);
    const chevron = document.getElementById(`goal-materials-chevron-${goalId}`);
    if (!content) return;
    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
        localStorage.setItem(`goal-materials-open-${goalId}`, "true");
    } else {
        content.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
        localStorage.setItem(`goal-materials-open-${goalId}`, "false");
    }
}

window._openGoalRecommendations = window._openGoalRecommendations || {};

async function previewRecommendedVideo(encodedUrl, goalId, title = '') {
    const url = decodeURIComponent(encodedUrl);
    try {
        if (typeof showToast === 'function') showToast('Adding 24h Preview material...', 'info', 2000);
        const formData = new FormData();
        formData.append('url', url);
        if (goalId) formData.append('goal_id', goalId);
        if (title) formData.append('title', title);

        const res = await fetchAPI('/api/videos/preview', { method: 'POST', body: formData });
        if (res && res.video_id) {
            localStorage.setItem(`accordion-open-goal-${goalId}`, "true");
            if (typeof loadGoals === 'function') await loadGoals();
            if (typeof loadDashboard === 'function') await loadDashboard();
            if (typeof openStudyStudio === 'function') {
                openStudyStudio(res.video_id);
            }
        }
    } catch (e) {
        console.error("Preview video failed:", e);
        if (typeof showToast === 'function') showToast('Failed to preview video', 'failed', 3000);
    }
}
window.previewRecommendedVideo = previewRecommendedVideo;

function updateRecsButtonState(goalId) {
    const btn = document.getElementById(`btn-recs-trigger-${goalId}`);
    if (!btn) return;
    const recsDrawer = document.getElementById(`recs-${goalId}`);
    const isOpen = recsDrawer && !recsDrawer.classList.contains('hidden');
    
    let hasRecs = window._openGoalRecommendations && window._openGoalRecommendations[goalId];
    if (!hasRecs) {
        const cached = localStorage.getItem(`recs-cache-${goalId}`);
        if (cached) {
            try {
                window._openGoalRecommendations[goalId] = JSON.parse(cached);
                hasRecs = true;
            } catch(e) {}
        }
    }
    const hasSaved = btn.dataset && btn.dataset.hasSavedRecs === '1';
    
    let text = "Get AI Recommendations";
    if (isOpen) {
        text = "Hide AI Recommendations";
    } else if (hasRecs || hasSaved) {
        text = "View AI Recommendations";
    }
    
    const span = btn.querySelector('.recs-btn-text') || btn;
    if (span) span.textContent = text;
}
window.updateRecsButtonState = updateRecsButtonState;

function closeRecommendationsDrawer(goalId) {
    const recsDrawer = document.getElementById(`recs-${goalId}`);
    if (recsDrawer) recsDrawer.classList.add('hidden');
    updateRecsButtonState(goalId);
}
window.closeRecommendationsDrawer = closeRecommendationsDrawer;

function openRecPlayerModal(ytId, title = "YouTube Video Preview") {
    const overlay = document.getElementById('overlay-rec-player');
    const iframe = document.getElementById('rec-player-iframe');
    const titleEl = document.getElementById('rec-player-title');
    if (!overlay || !iframe) return;

    if (titleEl) titleEl.textContent = title;
    iframe.src = `https://www.youtube.com/embed/${ytId}?autoplay=1&enablejsapi=1`;
    overlay.classList.remove('hidden');
    if (typeof renderIcons === 'function') renderIcons();
}
window.openRecPlayerModal = openRecPlayerModal;

function closeRecPlayerModal() {
    const overlay = document.getElementById('overlay-rec-player');
    const iframe = document.getElementById('rec-player-iframe');
    if (overlay) overlay.classList.add('hidden');
    if (iframe) iframe.src = '';
}
window.closeRecPlayerModal = closeRecPlayerModal;

function renderRecommendationCardHTML(v, goalId) {
    const videoUrl = v.url || `https://www.youtube.com/watch?v=${v.youtube_id}`;
    const encodedUrl = encodeURIComponent(videoUrl);
    const ytId = v.youtube_id || '';
    const durationStr = v.duration || 'N/A';
    const safeTitle = (v.title || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');

    return `
        <div id="rec-card-${goalId}-${ytId}" class="flex items-center space-x-2.5 bg-[#fcfaf6] p-2.5 pr-8 rounded-xl border border-[#e7dfd3] justify-between group transition hover:border-amber-500/40 hover:bg-white shadow-2xs relative">
            <div class="relative shrink-0">
                <img src="${v.thumbnail}" class="w-14 h-9 object-cover rounded-lg border border-[#e7dfd3] bg-[#f3ebd9]">
                ${durationStr !== 'N/A' ? `<span class="absolute bottom-0.5 right-0.5 bg-stone-900/90 text-amber-300 text-[8px] font-mono px-1 py-0.2 rounded font-bold">${durationStr}</span>` : ''}
            </div>
            <div class="min-w-0 flex-grow pr-1">
                <h6 class="font-bold text-stone-900 text-xs line-clamp-1 leading-snug hover:text-amber-800 transition" title="${v.title}">${v.title}</h6>
                <div class="flex items-center space-x-1.5 mt-1">
                    <button onclick="previewRecommendedVideo('${encodedUrl}', ${goalId}, '${safeTitle}')" class="px-2 py-0.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-900 border border-amber-200 font-bold rounded-md text-[9.5px] transition flex items-center space-x-1">
                        <i data-lucide="eye" class="w-3 h-3 text-amber-600"></i>
                        <span>Preview</span>
                    </button>
                    <button onclick="importRecommendedVideo('${ytId}', '${safeTitle}', ${goalId})" class="px-2 py-0.5 bg-amber-500/15 hover:bg-amber-500/25 text-amber-950 border border-amber-500/30 font-bold rounded-md text-[9.5px] transition flex items-center space-x-1">
                        <i data-lucide="plus-circle" class="w-3 h-3 text-amber-700"></i>
                        <span>Import</span>
                    </button>
                </div>
            </div>
            <button onclick="dismissGoalRecommendation('${ytId}', ${goalId})" class="absolute top-2 right-2 p-1 hover:bg-stone-200/80 text-stone-400 hover:text-red-600 rounded-md transition shrink-0" title="Dismiss Video">
                <i data-lucide="x" class="w-3.5 h-3.5"></i>
            </button>
        </div>
    `;
}


async function reloadGoalRecommendations(goalId, btnEl = null) {
    const vidsList = document.getElementById(`vids-${goalId}`);
    if (!vidsList) return;
    
    if (btnEl) {
        btnEl.disabled = true;
        const icon = btnEl.querySelector('i, svg');
        if (icon) icon.classList.add('animate-spin');
    }

    try {
        const res = await fetchAPI(`/api/goals/${goalId}/recommendations/reload_all`, { method: 'POST' });
        if (res && res.videos) {
            vidsList.innerHTML = '';
            if (res.videos.length === 0) {
                const message = res.youtube_api_key_missing
                    ? 'To enable recommendations, add a YouTube Data API v3 key (see the self-hosting setup guide for details).'
                    : 'No new recommendations available.';
                vidsList.innerHTML = `<p class="text-[10px] text-stone-400">${message}</p>`;
            } else {
                res.videos.forEach(v => {
                    vidsList.insertAdjacentHTML('beforeend', renderRecommendationCardHTML(v, goalId));
                });
            }
            if (window._openGoalRecommendations) {
                window._openGoalRecommendations[goalId] = res;
            }
            try {
                localStorage.setItem(`recs-cache-${goalId}`, JSON.stringify(res));
            } catch(e) {}
            if (typeof renderIcons === 'function') renderIcons();
        }
    } catch (e) {
        console.error("Reload recommendations failed:", e);
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            const icon = btnEl.querySelector('i, svg');
            if (icon) icon.classList.remove('animate-spin');
        }
        updateRecsButtonState(goalId);
    }
}
window.reloadGoalRecommendations = reloadGoalRecommendations;

function populateRecommendationDrawer(goalId, data) {
    if (!data) return;
    const recsDrawer = document.getElementById(`recs-${goalId}`);
    if (!recsDrawer) return;

    const conceptsList = document.getElementById(`concepts-${goalId}`);
    if (conceptsList && data.key_concepts) {
        conceptsList.innerHTML = data.key_concepts.map(c => `<span class="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-500/10 text-amber-950 border border-amber-500/20 shadow-2xs">${c}</span>`).join('');
    }
    
    const vidsList = document.getElementById(`vids-${goalId}`);
    if (vidsList && data.videos) {
        vidsList.innerHTML = '';
        if (data.videos.length === 0) {
            const message = data.youtube_api_key_missing
                ? 'To enable recommendations, add a YouTube Data API v3 key (see the self-hosting setup guide for details).'
                : 'No matching YouTube videos found.';
            vidsList.innerHTML = `<p class="text-[10px] text-stone-500">${message}</p>`;
        } else {
            data.videos.slice(0, 4).forEach(v => {
                vidsList.insertAdjacentHTML('beforeend', renderRecommendationCardHTML(v, goalId));
            });
            if (typeof renderIcons === 'function') renderIcons();
        }
    }

    const btn = document.getElementById(`btn-recs-trigger-${goalId}`);
    if (btn) btn.dataset.hasSavedRecs = '1';

    recsDrawer.classList.remove('hidden');
    updateRecsButtonState(goalId);
}
window.populateRecommendationDrawer = populateRecommendationDrawer;

async function loadRecommendations(goalId, btnEl = null) {
    const recsDrawer = document.getElementById(`recs-${goalId}`);
    if (!recsDrawer) return;
    
    // Toggle: if currently open (visible), close it!
    if (!recsDrawer.classList.contains('hidden')) {
        recsDrawer.classList.add('hidden');
        updateRecsButtonState(goalId);
        return;
    }
    
    let data = window._openGoalRecommendations ? window._openGoalRecommendations[goalId] : null;
    if (!data) {
        const cached = localStorage.getItem(`recs-cache-${goalId}`);
        if (cached) {
            try {
                data = JSON.parse(cached);
                window._openGoalRecommendations[goalId] = data;
            } catch(e) {}
        }
    }

    if (data) {
        populateRecommendationDrawer(goalId, data);
        return;
    }

    if (btnEl) {
        const icon = btnEl.querySelector('i, svg');
        if (icon) {
            icon.outerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-amber-600 shrink-0"></i>`;
        }
        btnEl.classList.add('opacity-75', 'cursor-wait');
        btnEl.disabled = true;
        if (typeof renderIcons === 'function') renderIcons();
    }

    try {
        data = await fetchAPI(`/api/goals/${goalId}/recommendations`);
        if (data && data.videos) {
            window._openGoalRecommendations[goalId] = data;
            try {
                localStorage.setItem(`recs-cache-${goalId}`, JSON.stringify(data));
            } catch(e) {}
        }

        populateRecommendationDrawer(goalId, data);
    } catch (e) {
        console.error("Fetch recommendations failed:", e);
    } finally {
        if (btnEl) {
            btnEl.classList.remove('opacity-75', 'cursor-wait');
            btnEl.disabled = false;
        }
        updateRecsButtonState(goalId);
        if (typeof renderIcons === 'function') renderIcons();
    }
}

async function dismissGoalRecommendation(ytId, goalId) {
    if (!ytId) return;
    const card = document.getElementById(`rec-card-${goalId}-${ytId}`);
    if (card) {
        card.style.opacity = '0.4';
        card.style.pointerEvents = 'none';
    }
    try {
        const formData = new FormData();
        formData.append('dismissed_yt_id', ytId);
        const res = await fetchAPI(`/api/goals/${goalId}/recommendations/replace_one`, { method: 'POST', body: formData });
        
        if (card) card.remove();

        if (res && res.replacement) {
            const vidsList = document.getElementById(`vids-${goalId}`);
            if (vidsList) {
                vidsList.insertAdjacentHTML('beforeend', renderRecommendationCardHTML(res.replacement, goalId));
                if (typeof renderIcons === 'function') renderIcons();
            }
        }
    } catch (e) {
        console.error("Failed to dismiss goal recommendation:", e);
        if (card) {
            card.style.opacity = '1';
            card.style.pointerEvents = 'auto';
        }
    }
}
window.dismissGoalRecommendation = dismissGoalRecommendation;


async function generateGoalQuiz(goalId, btnEl = null) {
    const promptFn = window.showPrompt || (typeof showPrompt === 'function' ? showPrompt : null);
    let qCount = null;
    if (promptFn) {
        qCount = await promptFn({
            title: "Practice Goal Quiz",
            message: "How many active recall questions do you want in this practice session?",
            defaultValue: "5",
            inputType: "number"
        });
    } else {
        qCount = prompt("How many active recall questions do you want in this practice goal quiz?", "5");
    }
    if (!qCount) return;
    const count = parseInt(qCount, 10);
    if (isNaN(count) || count <= 0) return;
    
    let origText = '';
    if (btnEl) {
        origText = btnEl.innerHTML;
        const icon = btnEl.querySelector('i, svg');
        if (icon) {
            icon.outerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-amber-600 shrink-0"></i>`;
        }
        btnEl.classList.add('opacity-75', 'cursor-wait');
        btnEl.disabled = true;
        if (typeof renderIcons === 'function') renderIcons();
    }

    try {
        const formData = new FormData();
        formData.append('question_count', count);
        
        const res = await fetchAPI(`/api/goals/${goalId}/practice`, {
            method: 'POST',
            body: formData
        });
        if (typeof startQuiz === 'function') {
            startQuiz(res.quiz_id);
        }
    } catch (e) {
        console.error(e);
        if (typeof showToast === 'function') {
            showToast("Failed to synthesize goal quiz: " + e.message, "failed");
        } else {
            alert("Failed to synthesize goal quiz: " + e.message);
        }
    } finally {
        if (btnEl) {
            btnEl.innerHTML = origText;
            btnEl.classList.remove('opacity-75', 'cursor-wait');
            btnEl.disabled = false;
            if (typeof renderIcons === 'function') renderIcons();
        }
    }
}

function toggleAccordion(cat) {
    const el = document.getElementById(`content-${cat}`);
    const chevron = document.getElementById(`chevron-${cat}`);
    if (!el) return;
    if (el.classList.contains('hidden')) {
        el.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
        localStorage.setItem(`accordion-open-${cat}`, "true");
    } else {
        el.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
        localStorage.setItem(`accordion-open-${cat}`, "false");
    }
}

function toggleArchivedGoals() {
    const wrapper = document.getElementById('archived-goals-wrapper');
    const chevron = document.getElementById('archived-goals-chevron');
    if (!wrapper) return;
    if (wrapper.classList.contains('hidden')) {
        wrapper.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
    } else {
        wrapper.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
}

function setAllAccordions(expand) {
    document.querySelectorAll('[id^="content-"]').forEach(el => {
        const cat = el.id.replace('content-', '');
        const chevron = document.getElementById(`chevron-${cat}`);
        if (expand) {
            el.classList.remove('hidden');
            if (chevron) chevron.classList.add('rotate-180');
            localStorage.setItem(`accordion-open-${cat}`, "true");
        } else {
            el.classList.add('hidden');
            if (chevron) chevron.classList.remove('rotate-180');
            localStorage.setItem(`accordion-open-${cat}`, "false");
        }
    });

    document.querySelectorAll('[id^="goal-materials-content-"]').forEach(el => {
        const goalId = el.id.replace('goal-materials-content-', '');
        const chevron = document.getElementById(`goal-materials-chevron-${goalId}`);
        if (expand) {
            el.classList.remove('hidden');
            if (chevron) chevron.classList.add('rotate-180');
            localStorage.setItem(`goal-materials-open-${goalId}`, "true");
        } else {
            el.classList.add('hidden');
            if (chevron) chevron.classList.remove('rotate-180');
            localStorage.setItem(`goal-materials-open-${goalId}`, "false");
        }
    });

    const archivedWrapper = document.getElementById('archived-goals-wrapper');
    const archivedChevron = document.getElementById('archived-goals-chevron');
    if (archivedWrapper) {
        if (expand) {
            archivedWrapper.classList.remove('hidden');
            if (archivedChevron) archivedChevron.classList.add('rotate-180');
        } else {
            archivedWrapper.classList.add('hidden');
            if (archivedChevron) archivedChevron.classList.remove('rotate-180');
        }
    }
}

function closeGoalMenu() {
    const existingPortal = document.getElementById('portal-goal-menu');
    if (existingPortal) existingPortal.remove();
}

function toggleGoalMenu(event, id) {
    if (event) event.stopPropagation();

    const existingPortal = document.getElementById('portal-goal-menu');
    if (existingPortal) {
        if (existingPortal.dataset.forId === String(id)) {
            existingPortal.remove();
            return;
        }
        existingPortal.remove();
    }
    
    const btn = event ? event.currentTarget : document.getElementById(`btn-goal-menu-${id}`);
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    
    const goalData = window._goalsCache && window._goalsCache[id];
    const title = goalData ? (goalData.title || '').replace(/'/g, "\\'") : '';
    const desc = goalData ? (goalData.description || '').replace(/'/g, "\\'") : '';
    
    const portal = document.createElement('div');
    portal.id = 'portal-goal-menu';
    portal.dataset.forId = String(id);
    portal.className = 'fixed w-52 rounded-xl bg-white border border-stone-200 shadow-2xl z-[9999] overflow-hidden';
    portal.innerHTML = `<div class="py-1">
        <button onclick="closeGoalMenu(); openEditGoalModal(${id}, '${title}', '${desc}')" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="edit-3" class="w-4 h-4 text-amber-600"></i><span>Edit Title &amp; Description</span>
        </button>
        <button onclick="closeGoalMenu(); archiveGoal(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="archive" class="w-4 h-4 text-amber-500"></i><span>Archive Goal</span>
        </button>
        <div class="border-t border-stone-200 my-1"></div>
        <button onclick="closeGoalMenu(); deleteGoal(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-red-400 hover:bg-red-950/20 hover:text-red-300 transition">
            <i data-lucide="trash-2" class="w-4 h-4"></i><span>Permanently Delete</span>
        </button>
    </div>`;
    
    document.body.appendChild(portal);
    renderIcons();
    
    const menuH = 140;
    let top = rect.bottom + 6;
    if (top + menuH > window.innerHeight) {
        top = rect.top - menuH - 6;
    }
    const left = Math.min(rect.right - 208, window.innerWidth - 216);
    
    portal.style.top = `${top}px`;
    portal.style.left = `${left}px`;
    
    const closeListener = (e) => {
        if (!portal.contains(e.target) && !btn.contains(e.target)) {
            portal.remove();
            document.removeEventListener('click', closeListener);
        }
    };
    setTimeout(() => document.addEventListener('click', closeListener), 10);
}

// Window bindings for inline HTML attribute calls
window.loadGoals = loadGoals;
window.initGoalsModal = initGoalsModal;
window.openCreateGoalModal = openCreateGoalModal;
window.closeCreateGoalModal = closeCreateGoalModal;
window.openEditGoalModal = openEditGoalModal;
window.reorderGoal = reorderGoal;
window.archiveGoal = archiveGoal;
window.deleteGoal = deleteGoal;
window.toggleGoalMaterials = toggleGoalMaterials;
window.loadRecommendations = loadRecommendations;
window.generateGoalQuiz = generateGoalQuiz;
window.toggleAccordion = toggleAccordion;
window.toggleArchivedGoals = toggleArchivedGoals;
window.setAllAccordions = setAllAccordions;
window.toggleGoalMenu = toggleGoalMenu;
window.closeGoalMenu = closeGoalMenu;
window.closeDeleteGoalModal = closeDeleteGoalModal;
window.confirmDeleteGoal = confirmDeleteGoal;

