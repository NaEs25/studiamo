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
                        <button type="button" data-goal-action="toggle-accordion" data-cat="watchlist" class="w-full flex justify-between items-center px-5 py-4 bg-[#f7f2e8] hover:bg-[#f3ebd9] transition text-left">
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
        window._archivedGoalsCache = {};
        archivedGoals.forEach(g => { window._archivedGoalsCache[g.id] = g; });
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
                            <button type="button" data-goal-action="create-goal" class="btn-primary px-8 py-4 font-extrabold text-sm rounded-2xl transition transform hover:-translate-y-0.5 inline-flex items-center space-x-2">
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
                        <div data-goal-card="${g.id}" class="bg-white border border-stone-200 p-5 rounded-2xl space-y-4 shadow-sm relative group">
                            <div class="flex justify-between items-start">
                                <div class="flex flex-col min-w-0">
                                    <div class="flex items-center space-x-3">
                                        <div class="w-8 h-8 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 font-bold text-xs shrink-0">
                                            #${rankNumber}
                                        </div>
                                        <h3 class="font-bold text-lg text-stone-900 leading-tight">${escapeHtml(g.title)}</h3>
                                    </div>
                                    ${g.description ? `<p class="text-xs text-stone-500 mt-1 ml-11">${escapeHtml(g.description)}</p>` : ''}
                                </div>
                                
                                <div class="flex items-center space-x-1 shrink-0 bg-stone-100 border border-stone-200 rounded-xl p-1">
                                    <button type="button" data-goal-action="reorder" data-goal-id="${g.id}" data-direction="up" ${index === 0 ? 'disabled class="p-1 text-stone-300 cursor-not-allowed"' : 'class="p-1 text-stone-600 hover:text-amber-600 transition"'} title="Move Priority Up (Rank #${rankNumber - 1})">
                                        <i data-lucide="arrow-up" class="w-4 h-4"></i>
                                    </button>
                                    <button type="button" data-goal-action="reorder" data-goal-id="${g.id}" data-direction="down" ${index === goals.length - 1 ? 'disabled class="p-1 text-stone-300 cursor-not-allowed"' : 'class="p-1 text-stone-600 hover:text-amber-600 transition"'} title="Move Priority Down (Rank #${rankNumber + 1})">
                                        <i data-lucide="arrow-down" class="w-4 h-4"></i>
                                    </button>
                                    <div class="w-px h-4 bg-stone-100 mx-0.5"></div>
                                    <button type="button" data-goal-action="menu" data-goal-id="${g.id}" id="btn-goal-menu-${g.id}" class="p-1 text-stone-600 hover:text-stone-900 transition" title="Goal Options">
                                        <i data-lucide="more-vertical" class="w-4 h-4"></i>
                                    </button>
                                </div>
                            </div>

                            <div class="space-y-3 pt-1">
                                <div class="flex justify-between items-center">
                                    <button type="button" data-goal-action="toggle-materials" data-goal-id="${g.id}" class="flex items-center space-x-2 text-xs font-bold text-stone-700 hover:text-amber-600 transition">
                                        <i data-lucide="folder" class="w-4 h-4 text-amber-600"></i>
                                        <span>Sources &amp; Materials</span>
                                        <span class="text-[10px] bg-amber-500/20 text-amber-700 px-2 py-0.5 rounded-full font-bold">${goalVideos.length}</span>
                                    </button>
                                    <i data-lucide="chevron-down" id="goal-materials-chevron-${g.id}" data-goal-action="toggle-materials" data-goal-id="${g.id}" class="w-4 h-4 text-stone-400 cursor-pointer transition-transform ${isMaterialsOpen ? 'rotate-180' : ''}"></i>
                                </div>

                                <div id="goal-materials-content-${g.id}" class="space-y-3 ${isMaterialsOpen ? '' : 'hidden'}">
                                    ${linkedVideoCardsHTML}
                                </div>
                            </div>

                            <div class="flex gap-2 pt-1">
                                <button id="btn-recs-trigger-${g.id}" data-has-saved-recs="${g.has_saved_recommendations ? 1 : 0}" data-goal-action="load-recs" data-goal-id="${g.id}" class="flex-grow py-1.5 px-3 bg-[#fbf8f2] hover:bg-[#f3ebd9] text-stone-800 border border-[#e7dfd3] font-semibold rounded-lg text-xs transition flex items-center justify-center space-x-1.5 shadow-sm">
                                    <i data-lucide="compass" class="w-3.5 h-3.5 text-stone-600"></i>
                                    <span class="recs-btn-text">${recsBtnLabel}</span>
                                </button>
                                
                                <button disabled class="flex-grow py-1.5 px-3 bg-amber-500/10 text-amber-900/60 border border-amber-500/20 font-semibold rounded-lg text-xs flex items-center justify-center space-x-1.5 cursor-not-allowed opacity-75 shadow-sm">
                                    <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-700/60"></i>
                                    <span>Coming Soon</span>
                                </button>
                            </div>
                            
                            <div id="recs-${g.id}" class="${isDrawerOpen ? '' : 'hidden'} p-3.5 bg-[#fbf8f2] border border-[#e7dfd3] rounded-xl space-y-3 shadow-sm">
                                <div class="flex items-start justify-between pb-2 border-b border-[#e7dfd3]/80 gap-2">
                                    <div class="min-w-0 flex-1 space-y-2">
                                        <button type="button" data-goal-action="toggle-concepts" class="concepts-toggle flex items-center space-x-1.5 text-xs font-bold text-stone-800 hover:text-amber-700 transition" data-goal-id="${g.id}" aria-expanded="false" aria-controls="concepts-${g.id}">
                                            <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-700 shrink-0"></i>
                                            <span>Concepts</span>
                                            <span id="concepts-count-${g.id}" class="text-[10px] bg-amber-500/20 text-amber-700 px-1.5 py-0.5 rounded-full font-bold"></span>
                                            <i data-lucide="chevron-down" class="concepts-chevron w-3.5 h-3.5 text-stone-400 transition-transform"></i>
                                        </button>
                                        <div id="concepts-${g.id}" class="hidden text-[11px] text-stone-600 leading-relaxed break-words"></div>
                                    </div>
                                    <div class="flex items-center space-x-1 shrink-0">
                                        <button type="button" data-goal-action="reload-recs" data-goal-id="${g.id}" class="p-1.5 bg-stone-100 hover:bg-stone-200/80 text-stone-600 hover:text-amber-800 rounded-lg transition border border-stone-200/80 shadow-sm" title="Reload Recommendations">
                                            <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
                                        </button>
                                        <button type="button" data-goal-action="close-recs" data-goal-id="${g.id}" class="p-1.5 hover:bg-stone-200/80 text-stone-400 hover:text-stone-700 rounded-lg transition ml-0.5" title="Collapse Panel">
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
                        <div class="w-full flex justify-between items-center px-5 py-4 bg-stone-100 hover:bg-stone-200 transition text-left cursor-pointer" data-goal-action="toggle-accordion" data-cat="unassociated">
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
                        <div data-archived-goal="${g.id}" class="flex items-center justify-between p-3 bg-stone-50 border border-stone-200 rounded-xl">
                            <div class="min-w-0">
                                <span class="block text-xs font-bold text-stone-900">${escapeHtml(g.title)}</span>
                                ${g.description ? `<p class="text-[10px] text-stone-400 truncate max-w-xs md:max-w-md" title="${escapeHtml(g.description)}">${escapeHtml(g.description)}</p>` : ''}
                            </div>
                            <div class="flex items-center space-x-1 shrink-0 ml-4 bg-stone-100 border border-stone-200 rounded-xl p-0.5">
                                <button type="button" data-goal-action="archive" data-goal-id="${g.id}" class="p-1 text-stone-400 hover:text-emerald-500 transition" title="Restore Goal to Active">
                                    <i data-lucide="rotate-ccw" class="w-4 h-4"></i>
                                </button>
                                <button type="button" data-goal-action="delete" data-goal-id="${g.id}" class="p-1 text-stone-400 hover:text-red-400 transition" title="Delete Goal Permanently">
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

        // Re-renders replace every card, so an active search has to be applied again.
        applyGoalsSearch();
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
                showToast("Failed to save goal: " + err.message, "failed");
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
    openOverlay('overlay-goal-modal', closeCreateGoalModal);
}

function closeCreateGoalModal() {
    const overlay = document.getElementById('overlay-goal-modal');
    if (!overlay) return;
    overlay.classList.add('hidden');
    closeOverlay('overlay-goal-modal');
    document.getElementById('goal-modal-id').value = '';
    document.getElementById('goal-modal-title').value = '';
    document.getElementById('goal-modal-desc').value = '';
}

function openEditGoalModal(id, title, description) {
    // Called with the id alone from the goal menu, which reads the text from the cache: a
    // title or description can hold quotes, backslashes and line breaks, none of which
    // survive being written into an inline handler.
    const cached = window._goalsCache && window._goalsCache[id];
    if (title === undefined && cached) {
        title = cached.title || '';
        description = cached.description || '';
    }
    document.getElementById('goal-modal-id').value = id;
    document.getElementById('goal-modal-title').value = title;
    document.getElementById('goal-modal-desc').value = description || '';
    
    const overlay = document.getElementById('overlay-goal-modal');
    if (overlay) {
        overlay.querySelector('h3 span').textContent = "Edit Learning Goal";
        openOverlay('overlay-goal-modal', closeCreateGoalModal);
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
    const goal = (window._goalsCache && window._goalsCache[id])
        || (window._archivedGoalsCache && window._archivedGoalsCache[id]);
    const title = goal ? goal.title : `Goal #${id}`;
    
    const hiddenId = document.getElementById('delete-goal-modal-id');
    const msg = document.getElementById('delete-goal-modal-msg');
    const modal = document.getElementById('overlay-delete-goal-modal');
    
    if (hiddenId) hiddenId.value = id;
    if (msg) {
        msg.innerHTML = `Are you sure you want to delete learning goal <strong class="text-stone-900">"${escapeHtml(title)}"</strong>?<br><span class="text-xs text-stone-500 mt-2 block">Choose how to handle the linked video materials:</span>`;
    }
    if (modal) {
        openOverlay('overlay-delete-goal-modal', closeDeleteGoalModal);
        renderIcons();
    }
}

function closeDeleteGoalModal() {
    const modal = document.getElementById('overlay-delete-goal-modal');
    if (modal) modal.classList.add('hidden');
    closeOverlay('overlay-delete-goal-modal');
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
        showToast("Failed to delete goal: " + e.message, "failed");
    }
}

// Opens or closes a collapsible section and turns its chevron to match. With a storageKey the
// choice is saved for the next render. A section the user opens or closes by hand is theirs
// again, so the search no longer closes it when it is cleared.
function setSectionOpen(contentEl, chevronEl, open, storageKey = null) {
    if (!contentEl) return;
    contentEl.classList.toggle('hidden', !open);
    if (chevronEl) chevronEl.classList.toggle('rotate-180', open);
    if (storageKey) localStorage.setItem(storageKey, open ? 'true' : 'false');
    delete contentEl.dataset.searchOpened;
}

function toggleGoalMaterials(goalId) {
    const content = document.getElementById(`goal-materials-content-${goalId}`);
    if (!content) return;
    setSectionOpen(content, document.getElementById(`goal-materials-chevron-${goalId}`),
        content.classList.contains('hidden'), `goal-materials-open-${goalId}`);
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

function renderRecommendationCardHTML(v, goalId) {
    const videoUrl = v.url || `https://www.youtube.com/watch?v=${v.youtube_id}`;
    const encodedUrl = encodeURIComponent(videoUrl);
    const ytId = v.youtube_id || '';
    const durationStr = v.duration || 'N/A';

    return `
        <div id="rec-card-${goalId}-${ytId}" class="flex items-center space-x-2.5 bg-[#fcfaf6] p-2.5 pr-8 rounded-xl border border-[#e7dfd3] justify-between group transition hover:border-amber-500/40 hover:bg-white shadow-sm relative">
            <div class="relative shrink-0">
                <img src="${v.thumbnail}" class="w-14 h-9 object-cover rounded-lg border border-[#e7dfd3] bg-[#f3ebd9]">
                ${durationStr !== 'N/A' ? `<span class="absolute bottom-0.5 right-0.5 bg-stone-900/90 text-amber-300 text-[8px] font-mono px-1 py-0.2 rounded font-bold">${durationStr}</span>` : ''}
            </div>
            <div class="min-w-0 flex-grow pr-1">
                <h6 class="font-bold text-stone-900 text-xs line-clamp-1 leading-snug hover:text-amber-800 transition" title="${escapeHtml(v.title)}">${escapeHtml(v.title)}</h6>
                <div class="flex items-center space-x-1.5 mt-1">
                    <button type="button" data-goal-action="preview-rec" data-goal-id="${goalId}" data-url="${encodedUrl}" data-title="${escapeHtml(v.title || '')}" class="px-2 py-0.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-900 border border-amber-200 font-bold rounded-md text-[9.5px] transition flex items-center space-x-1">
                        <i data-lucide="eye" class="w-3 h-3 text-amber-600"></i>
                        <span>Preview</span>
                    </button>
                    <button type="button" data-goal-action="import-rec" data-goal-id="${goalId}" data-yt-id="${escapeHtml(ytId)}" data-title="${escapeHtml(v.title || '')}" class="px-2 py-0.5 bg-amber-500/15 hover:bg-amber-500/25 text-amber-950 border border-amber-500/30 font-bold rounded-md text-[9.5px] transition flex items-center space-x-1">
                        <i data-lucide="plus-circle" class="w-3 h-3 text-amber-700"></i>
                        <span>Import</span>
                    </button>
                </div>
            </div>
            <button type="button" data-goal-action="dismiss-rec" data-goal-id="${goalId}" data-yt-id="${escapeHtml(ytId)}" class="absolute top-2 right-2 p-1 hover:bg-stone-200/80 text-stone-400 hover:text-red-600 rounded-md transition shrink-0" title="Dismiss Video">
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

// Concept chips stay collapsed until the header is clicked (data-goal-action="toggle-concepts").
function toggleConcepts(toggle) {
    const list = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!list) return;
    const nowHidden = list.classList.toggle('hidden');
    toggle.setAttribute('aria-expanded', String(!nowHidden));
    toggle.querySelector('.concepts-chevron')?.classList.toggle('rotate-180', !nowHidden);
}

function populateRecommendationDrawer(goalId, data) {
    if (!data) return;
    const recsDrawer = document.getElementById(`recs-${goalId}`);
    if (!recsDrawer) return;

    const conceptsList = document.getElementById(`concepts-${goalId}`);
    if (conceptsList && data.key_concepts) {
        conceptsList.innerHTML = data.key_concepts.map(c => `<span class="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-500/10 text-amber-950 border border-amber-500/20 shadow-sm">${escapeHtml(c)}</span>`).join('');
        const countEl = document.getElementById(`concepts-count-${goalId}`);
        if (countEl) countEl.textContent = data.key_concepts.length;
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
        showToast("Failed to synthesize goal quiz: " + e.message, "failed");
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
    if (!el) return;
    setSectionOpen(el, document.getElementById(`chevron-${cat}`), el.classList.contains('hidden'), `accordion-open-${cat}`);
}

function toggleArchivedGoals() {
    const wrapper = document.getElementById('archived-goals-wrapper');
    if (!wrapper) return;
    setSectionOpen(wrapper, document.getElementById('archived-goals-chevron'), wrapper.classList.contains('hidden'));
}

function setAllAccordions(expand) {
    document.querySelectorAll('[id^="content-"]').forEach(el => {
        const cat = el.id.replace('content-', '');
        setSectionOpen(el, document.getElementById(`chevron-${cat}`), expand, `accordion-open-${cat}`);
    });
    document.querySelectorAll('[id^="goal-materials-content-"]').forEach(el => {
        const goalId = el.id.replace('goal-materials-content-', '');
        setSectionOpen(el, document.getElementById(`goal-materials-chevron-${goalId}`), expand, `goal-materials-open-${goalId}`);
    });
    setSectionOpen(document.getElementById('archived-goals-wrapper'), document.getElementById('archived-goals-chevron'), expand);
}

function closeGoalMenu() {
    closeContextMenuPortal('portal-goal-menu');
}

// anchorEl is the menu button; without one, the menu anchors to that goal's button by id.
function toggleGoalMenu(event, id, anchorEl = null) {
    if (event) event.stopPropagation();

    const btn = anchorEl || document.getElementById(`btn-goal-menu-${id}`);

    const html = `<div class="py-1">
        <button type="button" data-goal-menu-action="edit" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="edit-3" class="w-4 h-4 text-amber-600"></i><span>Edit Title &amp; Description</span>
        </button>
        <button type="button" data-goal-menu-action="archive" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="archive" class="w-4 h-4 text-amber-500"></i><span>Archive Goal</span>
        </button>
        <div class="border-t border-stone-200 my-1"></div>
        <button type="button" data-goal-menu-action="delete" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-red-400 hover:bg-red-950/20 hover:text-red-300 transition">
            <i data-lucide="trash-2" class="w-4 h-4"></i><span>Permanently Delete</span>
        </button>
    </div>`;

    toggleContextMenuPortal('portal-goal-menu', id, btn, html, {
        extraClasses: 'w-52 border border-stone-200',
        onMount: (portal) => {
            portal.addEventListener('click', (e) => {
                const item = e.target.closest('[data-goal-menu-action]');
                if (!item) return;
                closeGoalMenu();
                const action = item.dataset.goalMenuAction;
                if (action === 'edit') openEditGoalModal(id);
                else if (action === 'archive') archiveGoal(id);
                else if (action === 'delete') deleteGoal(id);
            });
        },
    });
}

// One delegated listener for the buttons goals.js renders into the goals tab (goal cards, the
// study queue and unassociated accordions, archived goals, recommendation cards and concepts),
// keyed by data-goal-action. Not covered: material cards from renderVideoCard (videos.js), and
// the static header and archive buttons in index.html, which still use inline handlers.
function initGoalsActions() {
    const tab = document.getElementById('tab-goals');
    if (!tab) return;
    tab.addEventListener('click', (e) => {
        const el = e.target.closest('[data-goal-action]');
        // Some browsers deliver clicks on the icon inside a disabled button.
        if (!el || !tab.contains(el) || el.disabled) return;
        const goalId = Number(el.dataset.goalId);
        switch (el.dataset.goalAction) {
            case 'toggle-accordion': toggleAccordion(el.dataset.cat); break;
            case 'create-goal': openCreateGoalModal(); break;
            case 'reorder': reorderGoal(goalId, el.dataset.direction); break;
            case 'menu': toggleGoalMenu(e, goalId, el); break;
            case 'toggle-materials': toggleGoalMaterials(goalId); break;
            case 'load-recs': loadRecommendations(goalId, el); break;
            case 'reload-recs': reloadGoalRecommendations(goalId, el); break;
            case 'close-recs': closeRecommendationsDrawer(goalId); break;
            case 'toggle-concepts': toggleConcepts(el); break;
            case 'archive': archiveGoal(goalId); break;
            case 'delete': deleteGoal(goalId); break;
            case 'preview-rec': previewRecommendedVideo(el.dataset.url, goalId, el.dataset.title); break;
            case 'import-rec': importRecommendedVideo(el.dataset.ytId, el.dataset.title, goalId); break;
            case 'dismiss-rec': dismissGoalRecommendation(el.dataset.ytId, goalId); break;
        }
    });
}

// --- Goals tab search ---
// Filters the cards loadGoals() already rendered, so it needs no API call. A goal whose title
// or description matches stays with all of its materials; otherwise it stays only if one of
// its materials matches, and then only those materials show. Material search covers titles. Sections a match sits in are
// opened for the search and closed again when it is cleared, without touching the saved
// accordion state in localStorage.

function normalizeSearchText(text) {
    return String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function getGoalsSearchTerms() {
    const input = document.getElementById('goals-search-input');
    return normalizeSearchText(input ? input.value : '').split(/\s+/).filter(Boolean);
}

function matchesSearchTerms(text, terms) {
    const haystack = normalizeSearchText(text);
    return terms.every(term => haystack.includes(term));
}

function setSearchMiss(el, miss) {
    if (el) el.classList.toggle('search-miss', miss);
}

// Opens a collapsed section for the search and marks it, so clearing the search can close it.
// The mark remembers the chevron and the section's saved-state key for that.
function openSectionForSearch(contentEl, chevronEl, storageKey = '') {
    if (!contentEl || !contentEl.classList.contains('hidden')) return;
    setSectionOpen(contentEl, chevronEl, true);
    contentEl.dataset.searchOpened = chevronEl ? chevronEl.id : '';
    contentEl.dataset.searchStorageKey = storageKey;
}

// Closes what the search opened, except sections whose saved state says open by now (for
// example after a jump to a material, which saves the section as open).
function restoreSearchOpenedSections() {
    document.querySelectorAll('#tab-goals [data-search-opened]').forEach(el => {
        const key = el.dataset.searchStorageKey;
        const chevron = el.dataset.searchOpened ? document.getElementById(el.dataset.searchOpened) : null;
        delete el.dataset.searchStorageKey;
        if (key && localStorage.getItem(key) === 'true') {
            delete el.dataset.searchOpened;
            return;
        }
        setSectionOpen(el, chevron, false);
    });
}

// Hides the material cards in a container that do not match and returns how many do.
function filterMaterialCards(containerEl, terms) {
    if (!containerEl) return 0;
    let matched = 0;
    containerEl.querySelectorAll('[id^="video-card-"]').forEach(card => {
        const video = (window._videoCardCache || {})[card.id.replace('video-card-', '')];
        const isMatch = !!video && matchesSearchTerms(video.title, terms);
        setSearchMiss(card, !isMatch);
        if (isMatch) matched++;
    });
    return matched;
}

function applyGoalsSearch() {
    const tab = document.getElementById('tab-goals');
    if (!tab) return;
    const terms = getGoalsSearchTerms();
    const clearBtn = document.getElementById('btn-goals-search-clear');
    const status = document.getElementById('goals-search-status');
    const empty = document.getElementById('goals-search-empty');

    restoreSearchOpenedSections();
    if (clearBtn) clearBtn.classList.toggle('hidden', terms.length === 0);

    if (terms.length === 0) {
        tab.querySelectorAll('.search-miss').forEach(el => el.classList.remove('search-miss'));
        if (status) status.textContent = '';
        if (empty) empty.classList.add('hidden');
        return;
    }

    let goalCount = 0;
    let materialCount = 0;

    // Active goals
    const goalsContainer = document.getElementById('goals-container');
    let visibleGoals = 0;
    tab.querySelectorAll('[data-goal-card]').forEach(card => {
        const goalId = card.dataset.goalCard;
        const goal = (window._goalsCache || {})[goalId];
        const materials = document.getElementById(`goal-materials-content-${goalId}`);
        const goalMatches = !!goal && matchesSearchTerms(`${goal.title} ${goal.description || ''}`, terms);
        const matchedMaterials = filterMaterialCards(materials, terms);
        materialCount += matchedMaterials;
        if (matchedMaterials > 0) {
            openSectionForSearch(materials, document.getElementById(`goal-materials-chevron-${goalId}`), `goal-materials-open-${goalId}`);
        }
        if (goalMatches) {
            goalCount++;
            // A matching goal keeps all of its materials, matching or not.
            if (materials) materials.querySelectorAll('.search-miss').forEach(el => el.classList.remove('search-miss'));
        }
        const visible = goalMatches || matchedMaterials > 0;
        setSearchMiss(card, !visible);
        if (visible) visibleGoals++;
    });
    setSearchMiss(goalsContainer, visibleGoals === 0);

    // Watchlist and unassociated materials
    ['watchlist', 'unassociated'].forEach(cat => {
        const container = document.getElementById(`goals-${cat}-container`);
        const content = document.getElementById(`content-${cat}`);
        const matched = filterMaterialCards(content, terms);
        materialCount += matched;
        setSearchMiss(container, matched === 0);
        if (matched > 0) openSectionForSearch(content, document.getElementById(`chevron-${cat}`), `accordion-open-${cat}`);
    });

    // Archived goals and materials
    const archivedList = document.getElementById('archived-goals-list');
    let archivedGoalMatches = 0;
    if (archivedList) {
        archivedList.querySelectorAll('[data-archived-goal]').forEach(item => {
            const goal = (window._archivedGoalsCache || {})[item.dataset.archivedGoal];
            const isMatch = !!goal && matchesSearchTerms(`${goal.title} ${goal.description || ''}`, terms);
            setSearchMiss(item, !isMatch);
            if (isMatch) archivedGoalMatches++;
        });
        setSearchMiss(archivedList.parentElement, archivedGoalMatches === 0);
    }
    const archivedVidsList = document.getElementById('archived-videos-list');
    const archivedVidMatches = filterMaterialCards(archivedVidsList, terms);
    if (archivedVidsList) setSearchMiss(archivedVidsList.parentElement, archivedVidMatches === 0);
    goalCount += archivedGoalMatches;
    materialCount += archivedVidMatches;
    const archivedTotal = archivedGoalMatches + archivedVidMatches;
    setSearchMiss(document.getElementById('goals-archived-section'), archivedTotal === 0);
    if (archivedTotal > 0) {
        openSectionForSearch(document.getElementById('archived-goals-wrapper'), document.getElementById('archived-goals-chevron'));
    }

    const total = goalCount + materialCount;
    if (empty) empty.classList.toggle('hidden', total > 0);
    if (status) {
        const parts = [];
        if (goalCount) parts.push(`${goalCount} ${goalCount === 1 ? 'goal' : 'goals'}`);
        if (materialCount) parts.push(`${materialCount} ${materialCount === 1 ? 'material' : 'materials'}`);
        status.textContent = total ? `Showing ${parts.join(' and ')}` : '';
    }
}

function setGoalsSearchOpen(open) {
    const bar = document.getElementById('goals-search-bar');
    const toggle = document.getElementById('btn-goals-search-toggle');
    const input = document.getElementById('goals-search-input');
    if (!bar || !input) return;
    bar.classList.toggle('hidden', !open);
    if (toggle) toggle.setAttribute('aria-expanded', String(open));
    if (open) {
        input.focus();
    } else {
        input.value = '';
        applyGoalsSearch();
    }
}

// Called before jumping to a material card, which an active search could be hiding.
function clearGoalsSearch() {
    const input = document.getElementById('goals-search-input');
    if (input && input.value) setGoalsSearchOpen(false);
}

function initGoalsSearch() {
    const toggle = document.getElementById('btn-goals-search-toggle');
    const input = document.getElementById('goals-search-input');
    const clearBtn = document.getElementById('btn-goals-search-clear');
    if (!toggle || !input) return;

    toggle.addEventListener('click', () => {
        const bar = document.getElementById('goals-search-bar');
        setGoalsSearchOpen(bar.classList.contains('hidden'));
    });
    // Short debounce: every run re-filters the whole tab.
    let searchTimer = null;
    input.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(applyGoalsSearch, 100);
    });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            // Only the search closes, not an overlay that core.js's Escape handler would close.
            e.stopPropagation();
            setGoalsSearchOpen(false);
            toggle.focus();
        }
    });
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            input.value = '';
            applyGoalsSearch();
            input.focus();
        });
    }
    // "/" opens the search while the goals tab is showing, unless the user is typing somewhere.
    document.addEventListener('keydown', (e) => {
        if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
        const tab = document.getElementById('tab-goals');
        if (!tab || tab.classList.contains('hidden')) return;
        if (typeof _openOverlays !== 'undefined' && _openOverlays.size > 0) return;
        const target = e.target;
        if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return;
        e.preventDefault();
        setGoalsSearchOpen(true);
    });
}

// Functions other scripts or index.html's inline handlers call. Top-level function declarations
// are global in these classic scripts anyway; listing them keeps the outside callers findable.
window.loadGoals = loadGoals;
window.initGoalsModal = initGoalsModal;
window.openCreateGoalModal = openCreateGoalModal;
window.toggleArchivedGoals = toggleArchivedGoals;
window.setAllAccordions = setAllAccordions;
window.closeDeleteGoalModal = closeDeleteGoalModal;
window.confirmDeleteGoal = confirmDeleteGoal;

