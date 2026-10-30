// --- Studiamo Goals Module ---

// Videos in the Study Queue get no review quizzes or reminders until they are taken out of it,
// which is easy to miss. Once the queue passes this size the hint is shown, up to twice per
// account (the count lives on user_profile.queue_hint_count, capped server-side).
const QUEUE_HINT_THRESHOLD = 5;
let queueHintChecked = false;

async function maybeShowQueueHint(queueSize) {
    if (queueHintChecked || queueSize <= QUEUE_HINT_THRESHOLD) return;
    queueHintChecked = true;
    try {
        const status = await fetchAPI('/api/user/onboarding_status');
        if ((status.queue_hint_count || 0) >= 2) return;
        await fetchAPI('/api/user/queue_hint_seen', { method: 'POST' });
        await showConfirm({
            title: 'Your Study Queue is filling up',
            message: 'Videos in the Study Queue get no review quizzes and no reminders. Once you have watched one, tap its bookmark icon to take it out of the queue, and its reviews will start.',
            confirmText: 'Got it',
            hideCancel: true,
            icon: 'bookmark'
        });
    } catch (e) {
        queueHintChecked = false;
    }
}

// A small "Plan" tag on an AI button, shown only to an account without a plan so the upgrade
// toast it will get is never a surprise. The buttons stay visible and clickable.
function planTagHTML() {
    return (typeof isFreePlan === 'function' && isFreePlan())
        ? '<span class="plan-badge ml-1 select-none">Plan</span>'
        : '';
}

function goalRankBadgeHTML(rank) {
    return `<div class="w-8 h-8 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-700 font-bold text-xs shrink-0">#${rank}</div>`;
}

// A goal's quiz counts: one per material that has a quiz, however many quizzes that material
// holds, so a material still waiting for its "Generate quiz" is the gap between the material
// and quiz counts. A material's quiz is the one at its current importance, else any it has, as
// on its card. Archived and Study Queue materials are skipped, as they are in the material count.
// A material Chompy paused still has its quiz and still counts; due leaves out paused materials
// (they are won back, not studied) and mastered quizzes, which have no real next review.
function goalStats(goalId, videos, quizzes) {
    const stats = { total: 0, due: 0 };
    videos.forEach(v => {
        if (v.learning_goal_id !== goalId || v.is_archived || v.is_watchlist) return;
        const own = quizzes.filter(q => q.quiz_type === 'video' && q.video_id === v.id);
        const quiz = own.find(q => q.importance_level === v.importance_rating) || own[0];
        if (!quiz) return;
        stats.total++;
        if (!quiz.mastered && quiz.is_due === true && !v.is_paused) stats.due++;
    });
    return stats;
}

// The count chips on a goal card: materials, quizzes, and what is due, which stands out.
function goalStatsHTML(stats, materialCount) {
    const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    return `
        <div class="flex flex-wrap items-center gap-2">
            <span class="goal-stat">${plural(materialCount, 'material', 'materials')}</span>
            <span class="goal-stat">${plural(stats.total, 'quiz', 'quizzes')}</span>
            ${stats.due > 0 ? `<span class="goal-stat goal-stat-due">${stats.due} due today</span>` : ''}
        </div>`;
}

// The AI recommendations button, the "Coming Soon" placeholder beside it, and the recommendations
// drawer. Shown at the top of the goal page only; its ids are per goal.
function goalRecsSectionHTML(g) {
    const isDrawerOpen = Boolean(window._openGoalRecommendations && window._openGoalRecommendations[g.id]);
    const hasSavedRecs = Boolean(g.has_saved_recommendations);
    const recsBtnLabel = (isDrawerOpen || hasSavedRecs) ? 'View AI Recommendations' : 'Get AI Recommendations';
    return `
                            <div data-recs-section class="flex gap-2 pt-1">
                                <button id="btn-recs-trigger-${g.id}" data-has-saved-recs="${g.has_saved_recommendations ? 1 : 0}" data-goal-action="load-recs" data-goal-id="${g.id}" class="flex-grow py-1.5 px-3 bg-[#fbf8f2] hover:bg-[#f3ebd9] text-stone-800 border border-[#e7dfd3] font-semibold rounded-lg text-xs transition flex items-center justify-center space-x-1.5 shadow-sm">
                                    <i data-lucide="compass" class="w-3.5 h-3.5 text-stone-600"></i>
                                    <span class="recs-btn-text">${recsBtnLabel}</span>${planTagHTML()}
                                </button>
                                
                                <button disabled class="flex-grow py-1.5 px-3 bg-amber-500/10 text-amber-900/60 border border-amber-500/20 font-semibold rounded-lg text-xs flex items-center justify-center space-x-1.5 cursor-not-allowed opacity-75 shadow-sm">
                                    <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-700/60"></i>
                                    <span>Coming Soon</span>
                                </button>
                            </div>
                            
                            <div id="recs-${g.id}" data-recs-section class="${isDrawerOpen ? '' : 'hidden'} p-3.5 bg-[#fbf8f2] border border-[#e7dfd3] rounded-xl space-y-3 shadow-sm">
                                <div class="flex items-start justify-between pb-2 border-b border-[#e7dfd3]/80 gap-2">
                                    <div class="min-w-0 flex-1 space-y-2">
                                        <button type="button" data-goal-action="toggle-concepts" class="concepts-toggle flex items-center space-x-1.5 text-xs font-bold text-stone-800 hover:text-amber-700 transition" data-goal-id="${g.id}" aria-expanded="false" aria-controls="concepts-${g.id}">
                                            <i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-700 shrink-0"></i>
                                            <span>Concepts</span>
                                            <span id="concepts-count-${g.id}" class="text-[10px] bg-amber-500/20 text-amber-700 px-1.5 py-0.5 rounded-md font-bold"></span>
                                            <i data-lucide="chevron-down" class="concepts-chevron w-3.5 h-3.5 text-stone-400 transition-transform"></i>
                                        </button>
                                        <div id="concepts-${g.id}" class="hidden text-[11px] text-stone-600 leading-relaxed break-words"></div>
                                    </div>
                                    <div class="flex items-center space-x-1 shrink-0">
                                        <button type="button" data-goal-action="reload-recs" data-goal-id="${g.id}" class="p-1.5 bg-stone-100 hover:bg-stone-200/80 text-stone-600 hover:text-amber-800 rounded-lg transition border border-stone-200/80 shadow-sm" title="Reload Recommendations">
                                            <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
                                        </button>
                                    </div>
                                </div>
                                <div id="vids-${g.id}" class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]"></div>
                            </div>
`;
}

async function loadGoals() {
    try {
        const data = await fetchAPI('/api/dashboard');
        const goals = data.goals || [];
        const archivedGoals = data.archived_goals || [];
        const videos = data.videos || [];
        const quizzes = data.quizzes || [];
        maybeShowQueueHint(videos.filter(v => v.is_watchlist === 1).length);

        // Cache video data for context operations
        window._videoCardCache = {};
        [...videos, ...(data.archived || [])].forEach(v => {
            window._videoCardCache[v.id] = v;
        });

        // 0. Starter set: ready-made example materials, in their own soft green block.
        const starterVideos = videos.filter(v => v.is_starter);
        const starterContainer = document.getElementById('goals-starter-container');
        if (starterContainer) {
            starterContainer.innerHTML = starterVideos.length === 0 ? '' : `
                <div class="bg-emerald-50 border border-emerald-200 rounded-2xl p-4 space-y-3 shadow-sm">
                    <div class="flex items-center justify-between">
                        <span class="text-[11px] font-bold text-emerald-700 flex items-center gap-1.5">
                            <i data-lucide="sprout" class="w-4 h-4"></i>Starter set
                        </span>
                        <button type="button" data-goal-action="remove-starter" class="p-1 text-stone-400 hover:text-stone-700 transition" title="Remove the starter set" aria-label="Remove the starter set">
                            <i data-lucide="x" class="w-4 h-4"></i>
                        </button>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 items-start">
                        ${starterVideos.map(item => renderVideoCard(item, quizzes, goals)).join('')}
                    </div>
                </div>`;
        }

        // 1. Render Watchlist Queue at top if populated
        const watchlistContainer = document.getElementById('goals-watchlist-container');
        if (watchlistContainer) {
            const watchlistVideos = videos.filter(v => v.is_watchlist === 1 && !v.is_starter);
            if (watchlistVideos.length > 0) {
                const isWatchlistOpen = localStorage.getItem('accordion-open-watchlist') !== 'false';
                watchlistContainer.innerHTML = `
                    <div class="bg-[#fbf8f2] border border-[#e7dfd3] rounded-2xl overflow-hidden mb-6 shadow-sm">
                        <button type="button" data-goal-action="toggle-accordion" data-cat="watchlist" class="w-full flex justify-between items-center px-5 py-4 bg-[#f7f2e8] hover:bg-[#f3ebd9] transition text-left">
                            <span class="flex items-center space-x-2.5 font-bold">
                                <i data-lucide="bookmark" class="w-5 h-5 text-amber-600 fill-amber-500"></i>
                                <span class="text-stone-800">Study Queue / Watchlist</span>
                                <span class="text-xs bg-amber-500/20 text-amber-800 px-2 py-0.5 rounded-md font-semibold border border-amber-500/30">${watchlistVideos.length}</span>
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
        window._goalsPageData = { goals, videos, quizzes, folders: data.folders || [] };
        window._goalsLoaded = true;
        window._archivedGoalsCache = {};
        archivedGoals.forEach(g => { window._archivedGoalsCache[g.id] = g; });
        if (typeof renderGoalBoxes === 'function') renderGoalBoxes(goals);

        // 2. Render Active Goals Grid
        const container = document.getElementById('goals-container');
        if (container) {
            container.innerHTML = '';
            if (goals.length === 0) {
                container.innerHTML = `
                    <div class="text-center py-16 px-6 bg-white rounded-2xl border border-dashed border-amber-500/30 shadow-xl max-w-xl mx-auto my-6 space-y-5">
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
                    const cardHTML = `
                        <div data-goal-card="${g.id}" class="goal-card p-5 rounded-2xl space-y-3 relative">
                            <div class="flex items-center space-x-3 min-w-0">
                                ${goalRankBadgeHTML(rankNumber)}
                                <h3 class="font-bold text-lg text-stone-900 leading-tight"><button type="button" data-goal-action="open-goal" data-goal-id="${g.id}" class="text-left focus:outline-none">${escapeHtml(g.title)}</button></h3>
                            </div>
                            ${goalStatsHTML(goalStats(g.id, videos, quizzes), goalVideos.length)}
                        </div>
                    `;

                    container.innerHTML += cardHTML;
                });

            }
        }

        // 3. Render Unassociated Videos Container
        const unassociatedContainer = document.getElementById('goals-unassociated-container');
        if (unassociatedContainer) {
            const unassociatedVideos = videos.filter(v => !v.learning_goal_id && v.is_watchlist !== 1 && !v.is_starter);
            if (unassociatedVideos.length > 0) {
                const isUnassocOpen = localStorage.getItem('accordion-open-unassociated') === 'true';
                unassociatedContainer.innerHTML = `
                    <div class="bg-white border border-stone-200 rounded-2xl overflow-hidden mt-6 mb-4 shadow-sm">
                        <div class="w-full flex justify-between items-center px-5 py-4 bg-stone-100 hover:bg-stone-200 transition text-left cursor-pointer" data-goal-action="toggle-accordion" data-cat="unassociated">
                            <span class="flex items-center space-x-2.5 font-bold">
                                <i data-lucide="help-circle" class="w-5 h-5 text-amber-400"></i>
                                <span class="text-stone-900">Unassociated / Quick Review Material</span>
                                <span class="text-xs bg-stone-200 text-stone-500 px-2 py-0.5 rounded-md font-semibold">${unassociatedVideos.length}</span>
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
        if (window._openGoalPageId) renderGoalPage();
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

    // Archive and Delete sit in the edit dialog; the dialog closes first so the confirmation is the only thing open.
    ['archive', 'delete'].forEach(action => {
        document.getElementById(`btn-goal-modal-${action}`)?.addEventListener('click', () => {
            const id = Number(document.getElementById('goal-modal-id').value);
            if (!id) return;
            closeCreateGoalModal();
            if (action === 'archive') archiveGoal(id); else deleteGoal(id);
        });
    });

    const btnInfo = document.getElementById('btn-goal-concepts-info');
    if (btnInfo) {
        btnInfo.addEventListener('click', () => {
            const hint = document.getElementById('goal-modal-concepts-hint');
            btnInfo.setAttribute('aria-expanded', String(hint.classList.toggle('hidden') === false));
        });
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
            // Only an edit sends concepts; a new goal gets them generated with its first recommendations.
            if (id) formData.append('key_concepts', document.getElementById('goal-modal-concepts').value);
            
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
    setGoalModalConcepts(false, '');
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
    setGoalModalConcepts(false, '');
}

// Shows the key concepts field for an edit and hides it for a new goal, collapsing its hint.
function setGoalModalConcepts(show, value) {
    document.getElementById('goal-modal-concepts-wrap').classList.toggle('hidden', !show);
    document.getElementById('goal-modal-more-wrap').classList.toggle('hidden', !show);
    document.getElementById('goal-modal-concepts').value = value;
    document.getElementById('goal-modal-concepts-hint').classList.add('hidden');
    document.getElementById('btn-goal-concepts-info').setAttribute('aria-expanded', 'false');
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
    // A goal whose recommendations loaded before concepts were stored on it still has them only
    // in the loaded drawer data; show those so the field matches the chips.
    const drawerData = window._openGoalRecommendations && window._openGoalRecommendations[id];
    const shownConcepts = (cached && cached.key_concepts) || ((drawerData && drawerData.key_concepts) || []).join(', ');
    setGoalModalConcepts(true, shownConcepts);
    
    const overlay = document.getElementById('overlay-goal-modal');
    if (overlay) {
        overlay.querySelector('h3 span').textContent = "Edit Learning Goal";
        openOverlay('overlay-goal-modal', closeCreateGoalModal);
        if (typeof renderIcons === 'function') renderIcons();
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
        // Awaited: the reorder sheet redraws from the reloaded list right after this returns.
        await loadGoals();
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
    const title = escapeHtml(v.title || '');
    const previewAttrs = `data-goal-action="preview-rec" data-goal-id="${goalId}" data-url="${encodedUrl}" data-title="${title}"`;
    const iconBtn = 'p-1.5 rounded-lg transition shrink-0';

    return `
        <div id="rec-card-${goalId}-${ytId}" class="flex items-center gap-2.5 bg-[#fcfaf6] p-2.5 rounded-xl border border-[#e7dfd3] transition hover:border-amber-500/40 hover:bg-white shadow-sm">
            <button type="button" ${previewAttrs} class="relative shrink-0 hover:opacity-80 transition" aria-label="Open in Study Studio: ${title}" title="Open in Study Studio">
                <img src="${v.thumbnail}" alt="" class="w-16 h-10 object-cover rounded-lg border border-[#e7dfd3] bg-[#f3ebd9]">
                ${durationStr !== 'N/A' ? `<span class="absolute bottom-0.5 right-0.5 bg-stone-900/90 text-amber-300 text-[8px] font-mono px-1 py-0.2 rounded font-bold">${durationStr}</span>` : ''}
            </button>
            <h6 class="min-w-0 flex-1 font-bold text-stone-900 text-xs line-clamp-2 leading-snug" title="${title}">${title}</h6>
            <div class="flex items-center gap-0.5 shrink-0">
                <button type="button" ${previewAttrs} class="${iconBtn} text-amber-700 hover:bg-amber-500/15" title="Open in Study Studio" aria-label="Open in Study Studio">
                    <i data-lucide="book-open" class="w-4 h-4"></i>
                </button>
                <button type="button" data-goal-action="import-rec" data-goal-id="${goalId}" data-yt-id="${escapeHtml(ytId)}" data-title="${title}" class="${iconBtn} text-amber-700 hover:bg-amber-500/15" title="Add to this goal" aria-label="Add to this goal">
                    <i data-lucide="plus-circle" class="w-4 h-4"></i>
                </button>
                <button type="button" data-goal-action="dismiss-rec" data-goal-id="${goalId}" data-yt-id="${escapeHtml(ytId)}" class="${iconBtn} text-stone-400 hover:bg-stone-200/80 hover:text-red-600" title="Dismiss video" aria-label="Dismiss video">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>
        </div>
    `;
}

// Drops an owned video from the drawer and from the copies of the recommendations kept in memory
// and in localStorage, so a redraw does not bring the card back.
function removeRecommendationCard(goalId, youtubeId) {
    document.getElementById(`rec-card-${goalId}-${youtubeId}`)?.remove();
    const data = window._openGoalRecommendations && window._openGoalRecommendations[goalId];
    if (data && data.videos) data.videos = data.videos.filter(v => v.youtube_id !== youtubeId);
    try {
        const key = `recs-cache-${goalId}`;
        const cached = JSON.parse(localStorage.getItem(key) || 'null');
        if (cached && cached.videos) {
            cached.videos = cached.videos.filter(v => v.youtube_id !== youtubeId);
            localStorage.setItem(key, JSON.stringify(cached));
        }
    } catch (e) { /* storage blocked or malformed */ }
}

// Adds a recommended video to the goal as a saved material: no AI call and no quiz, so it costs
// nothing. Its quiz is generated afterwards from the material's own button, like any saved one.
async function importGoalRecommendation(youtubeId, title, goalId, btnEl = null) {
    if (btnEl) btnEl.disabled = true;
    try {
        const formData = new FormData();
        formData.append('url', `https://www.youtube.com/watch?v=${youtubeId}`);
        if (title) formData.append('title', title);
        formData.append('learning_goal_id', goalId);
        const res = await fetchAPI('/api/videos/save', { method: 'POST', body: formData });
        // The save leaves a video the account already has exactly where it is (it may sit in the
        // Study Queue or another goal), so say that instead of claiming it was added.
        if (typeof showToast === 'function') {
            showToast(res && res.already_existed
                ? 'This video is already in your library, so nothing was added.'
                : 'Added to this goal. Generate its quiz from the goal page.',
                res && res.already_existed ? 'info' : 'saved');
        }
        removeRecommendationCard(goalId, youtubeId);
        if (typeof loadGoals === 'function') await loadGoals();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        if (typeof showToast === 'function') showToast('Could not add the video: ' + e.message, 'failed');
    } finally {
        if (btnEl) btnEl.disabled = false;
    }
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
    // The goal's own concepts (editable in the goal's Edit dialog) win over the cached blob's.
    const goalConcepts = String((window._goalsCache && window._goalsCache[goalId] && window._goalsCache[goalId].key_concepts) || '')
        .split(',').map(c => c.trim()).filter(Boolean);
    const concepts = goalConcepts.length ? goalConcepts : (data.key_concepts || []);
    if (conceptsList && concepts.length) {
        conceptsList.innerHTML = concepts.map(c => `<span class="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold bg-amber-500/10 text-amber-950 border border-amber-500/20 shadow-sm">${escapeHtml(c)}</span>`).join('');
        const countEl = document.getElementById(`concepts-count-${goalId}`);
        if (countEl) countEl.textContent = concepts.length;
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
    setSectionOpen(document.getElementById('archived-goals-wrapper'), document.getElementById('archived-goals-chevron'), expand);
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
        if (!el) {
            // A click on the card itself opens the goal page, except on anything interactive or
            // in the recommendations section, which has its own controls.
            const card = e.target.closest('[data-goal-card]');
            if (card && tab.contains(card) && !e.target.closest('button, a, input, select, textarea, [data-recs-section]')) {
                openGoalPage(Number(card.dataset.goalCard));
            }
            return;
        }
        // Some browsers deliver clicks on the icon inside a disabled button.
        if (!tab.contains(el) || el.disabled) return;
        const goalId = Number(el.dataset.goalId);
        switch (el.dataset.goalAction) {
            case 'toggle-accordion': toggleAccordion(el.dataset.cat); break;
            case 'create-goal': openCreateGoalModal(); break;
            case 'reorder': reorderGoal(goalId, el.dataset.direction); break;
            case 'open-reorder': openGoalReorder(); break;
            case 'add-material': openImportForGoal(goalId); break;
            case 'remove-starter': removeStarterSet(); break;
            case 'edit': openEditGoalModal(goalId); break;
            case 'open-goal': openGoalPage(goalId); break;
            case 'jump-material': navigateToVideoInGoals(el.dataset.videoId); break;
            case 'load-recs': loadRecommendations(goalId, el); break;
            case 'reload-recs': reloadGoalRecommendations(goalId, el); break;
            case 'close-recs': closeRecommendationsDrawer(goalId); break;
            case 'toggle-concepts': toggleConcepts(el); break;
            case 'archive': archiveGoal(goalId); break;
            case 'delete': deleteGoal(goalId); break;
            case 'preview-rec': previewRecommendedVideo(el.dataset.url, goalId, el.dataset.title); break;
            case 'import-rec': importGoalRecommendation(el.dataset.ytId, el.dataset.title, goalId, el); break;
            case 'dismiss-rec': dismissGoalRecommendation(el.dataset.ytId, goalId); break;
        }
    });
}

// --- Goals tab search ---
// Filters the cards loadGoals() already rendered, so it needs no API call. A goal whose title
// or description matches stays with all of its materials; otherwise it stays only if one of
// its materials matches (material titles only; the materials themselves are listed on the goal
// page, not on the card). Sections a match sits in are opened for the search and closed again when it is cleared, without touching the saved
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

function renderSearchMaterialResults(materials) {
    const box = document.getElementById('goals-search-materials');
    if (!box) return;
    box.classList.toggle('hidden', materials.length === 0);
    box.innerHTML = materials.map(v => {
        const goal = (window._goalsCache || {})[v.learning_goal_id];
        return `
        <div data-goal-action="jump-material" data-video-id="${v.id}" class="goal-card flex items-center gap-3 rounded-xl px-3 py-2.5">
            <i data-lucide="play-circle" class="w-4 h-4 text-amber-600 shrink-0"></i>
            <button type="button" data-goal-action="jump-material" data-video-id="${v.id}" class="min-w-0 flex-1 text-left focus:outline-none">
                <span class="block font-bold text-sm text-stone-900 truncate">${escapeHtml(v.title || 'Untitled')}</span>
                <span class="block text-[11px] text-stone-500 truncate">in ${escapeHtml(goal ? goal.title : 'a goal')}</span>
            </button>
        </div>`;
    }).join('');
    if (typeof renderIcons === 'function') renderIcons();
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
        renderSearchMaterialResults([]);
        if (status) status.textContent = '';
        if (empty) empty.classList.add('hidden');
        return;
    }

    let goalCount = 0;
    let materialCount = 0;

    // Materials in a goal are not listed on its card, so a match shows as its own result below
    // the goals and opens that goal's page.
    const matchedGoalMaterials = Object.values(window._videoCardCache || {}).filter(v =>
        v.learning_goal_id && v.is_watchlist !== 1 && !v.is_starter && !v.is_archived
        && (window._goalsCache || {})[v.learning_goal_id]
        && matchesSearchTerms(v.title, terms));
    renderSearchMaterialResults(matchedGoalMaterials);
    materialCount += matchedGoalMaterials.length;

    // Active goals
    const goalsContainer = document.getElementById('goals-container');
    let visibleGoals = 0;
    tab.querySelectorAll('[data-goal-card]').forEach(card => {
        const goalId = card.dataset.goalCard;
        const goal = (window._goalsCache || {})[goalId];
        const goalMatches = !!goal && matchesSearchTerms(`${goal.title} ${goal.description || ''}`, terms);
        const matchedMaterials = matchedGoalMaterials.filter(v => String(v.learning_goal_id) === goalId).length;
        const visible = goalMatches || matchedMaterials > 0;
        // A goal shown only because a material matched still counts as one result.
        if (visible) goalCount++;
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

// Removes every starter material after a confirmation. They are ordinary materials, so this is the
// normal delete; the account is not given the set again (user_profile.starter_set_added_at).
async function removeStarterSet() {
    const starters = ((window._goalsPageData && window._goalsPageData.videos) || []).filter(v => v.is_starter);
    if (starters.length === 0) return;
    const ok = await showConfirm({
        title: 'Remove the starter set?',
        message: 'The example videos and their quizzes are deleted from your account. They will not come back.',
        confirmText: 'Remove',
        icon: 'trash-2',
    });
    if (!ok) return;
    try {
        for (const v of starters) await fetchAPI(`/api/videos/${v.id}`, { method: 'DELETE' });
    } catch (e) {
        showToast('Could not remove the starter set: ' + (e.message || e), 'failed', 3500);
    }
    await loadGoals();
    if (typeof loadDashboard === 'function') loadDashboard();
}

// --- Add material to a goal --------------------------------------------------------------------

// Opens the Import tab with this goal already selected.
function openImportForGoal(goalId) {
    const selected = document.getElementById('input-goal-selected-id');
    if (selected) selected.value = String(goalId);
    if (typeof switchTab === 'function') switchTab('import');
    document.getElementById('new-goal-inline-fields')?.classList.add('hidden');
    if (typeof renderGoalBoxes === 'function') renderGoalBoxes(Object.values(window._goalsCache || {}));
}
window.openImportForGoal = openImportForGoal;

// --- Reorder goals -----------------------------------------------------------------------------

function renderGoalReorderList() {
    const list = document.getElementById('goal-reorder-list');
    if (!list) return;
    const goals = (window._goalsPageData && window._goalsPageData.goals) || [];
    list.innerHTML = goals.map((g, i) => `
        <div class="flex items-center gap-3 bg-white border border-stone-200 rounded-xl px-3 py-2.5 shadow-sm" data-reorder-row="${g.id}" draggable="true">
            <i data-lucide="grip-vertical" class="drag-handle w-4 h-4 text-stone-400 cursor-grab shrink-0"></i>
            ${goalRankBadgeHTML(i + 1)}
            <span class="font-bold text-sm text-stone-900 truncate flex-1">${escapeHtml(g.title)}</span>
            <button type="button" data-reorder-move="up" data-goal-id="${g.id}" ${i === 0 ? 'disabled' : ''} class="p-1.5 bg-stone-100 border border-stone-200 rounded-lg ${i === 0 ? 'text-stone-300' : 'text-stone-600'}" aria-label="Move up"><i data-lucide="arrow-up" class="w-4 h-4"></i></button>
            <button type="button" data-reorder-move="down" data-goal-id="${g.id}" ${i === goals.length - 1 ? 'disabled' : ''} class="p-1.5 bg-stone-100 border border-stone-200 rounded-lg ${i === goals.length - 1 ? 'text-stone-300' : 'text-stone-600'}" aria-label="Move down"><i data-lucide="arrow-down" class="w-4 h-4"></i></button>
        </div>`).join('') || '<p class="text-xs text-stone-500 py-4 text-center">No goals yet.</p>';
    if (typeof renderIcons === 'function') renderIcons();
}

function closeGoalReorder() {
    document.getElementById('overlay-goal-reorder')?.classList.add('hidden');
    closeOverlay('overlay-goal-reorder');
}

function openGoalReorder() {
    renderGoalReorderList();
    document.getElementById('overlay-goal-reorder')?.classList.remove('hidden');
    openOverlay('overlay-goal-reorder', closeGoalReorder);
}

// The sheet shows a new order at once and saves all of it in one request; only a failed save
// reloads the list from the server.
async function saveGoalOrder(ids) {
    const data = window._goalsPageData;
    const byId = new Map(data.goals.map(g => [g.id, g]));
    data.goals = ids.map(id => byId.get(id));
    renderGoalReorderList();
    const formData = new FormData();
    formData.append('ids', ids.join(','));
    try {
        await fetchAPI('/api/goals/order', { method: 'POST', body: formData });
        await loadGoals();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        showToast('Could not save the order: ' + (e.message || e), 'failed', 3000);
        await loadGoals();
    }
    renderGoalReorderList();
}

// An arrow moves one goal one step by the same endpoint the cards used, then redraws.
async function moveGoalInSheet(goalId, direction) {
    await reorderGoal(goalId, direction);
    renderGoalReorderList();
}

// Drag a goal onto another to place it where that one is.
function dropGoalOn(draggedId, targetId) {
    const ids = ((window._goalsPageData && window._goalsPageData.goals) || []).map(g => g.id);
    const from = ids.indexOf(Number(draggedId));
    const to = ids.indexOf(Number(targetId));
    if (from < 0 || to < 0 || from === to) return;
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    return saveGoalOrder(ids);
}

function initGoalReorderSheet() {
    const sheet = document.getElementById('overlay-goal-reorder');
    if (!sheet || sheet.dataset.bound) return;
    sheet.dataset.bound = '1';
    document.getElementById('btn-goal-reorder-done')?.addEventListener('click', closeGoalReorder);
    sheet.addEventListener('click', (e) => {
        if (e.target === sheet) { closeGoalReorder(); return; }
        const btn = e.target.closest('[data-reorder-move]');
        if (btn && !btn.disabled) moveGoalInSheet(Number(btn.dataset.goalId), btn.dataset.reorderMove);
    });
    let dragged = null;
    const clearMarks = () => sheet.querySelectorAll('.is-drop-target, .is-dragging').forEach(el => el.classList.remove('is-drop-target', 'is-dragging'));
    sheet.addEventListener('dragstart', (e) => {
        const row = e.target.closest('[data-reorder-row]');
        if (!row) return;
        dragged = row.dataset.reorderRow;
        e.dataTransfer.effectAllowed = 'move';
        row.classList.add('is-dragging');
    });
    sheet.addEventListener('dragover', (e) => {
        const row = dragged && e.target.closest('[data-reorder-row]');
        if (!row) return;
        e.preventDefault();
        sheet.querySelectorAll('.is-drop-target').forEach(el => { if (el !== row) el.classList.remove('is-drop-target'); });
        if (row.dataset.reorderRow !== dragged) row.classList.add('is-drop-target');
    });
    sheet.addEventListener('dragend', () => { dragged = null; clearMarks(); });
    sheet.addEventListener('drop', (e) => {
        const row = e.target.closest('[data-reorder-row]');
        if (!row || !dragged) return;
        e.preventDefault();
        const id = dragged;
        dragged = null;
        clearMarks();
        dropGoalOn(id, row.dataset.reorderRow);
    });
}

// --- Goal page ---------------------------------------------------------------------------------
// One goal on its own page, inside the Goals tab: style.css hides the rest of the tab while
// #tab-goals has .goal-page-open. It is a view, not a document: it gets a history entry so the
// back gesture of an installed app returns to the list, and loadGoals() redraws it with the rest.

const GOAL_PAGE_VIEW_KEY = 'goal-page-view';
// The goal page that is open, kept so a reload reopens it even when the address loses its hash.
const GOAL_PAGE_STORE_KEY = 'active_goal_page';
// query filters this goal's materials only (applyGoalPageSearch); searchOpen shows its input.
// folderId is the folder open inside the goal page (null: the goal itself).
const goalPageState = { reordering: false, query: '', searchOpen: false, folderId: null };

function goalPageView() {
    return localStorage.getItem(GOAL_PAGE_VIEW_KEY) === 'list' ? 'list' : 'detail';
}

function goalPageMaterials(goalId) {
    const data = window._goalsPageData || { videos: [] };
    return data.videos.filter(v => v.learning_goal_id === goalId && v.is_watchlist !== 1);
}

function goalPageFolders(goalId) {
    return ((window._goalsPageData && window._goalsPageData.folders) || []).filter(f => f.goal_id === goalId);
}

// The open folder's id, or null for the goal itself (also when the folder no longer exists).
function goalPageFolderId(goalId) {
    const id = goalPageState.folderId;
    return id && goalPageFolders(goalId).some(f => f.id === id) ? id : null;
}

// The materials in the view being shown: the open folder's, or the ones outside any folder.
function goalPageScopeMaterials(goalId) {
    const folderId = goalPageFolderId(goalId);
    return goalPageMaterials(goalId).filter(v => (v.folder_id || null) === folderId);
}

function materialKind(v) {
    if (v.material_type === 'link') return { icon: 'globe', label: 'Link' };
    if (v.youtube_id && !String(v.youtube_id).startsWith('doc_')) return { icon: 'play-circle', label: 'Video' };
    if (v.material_type === 'notes') return { icon: 'notebook-pen', label: 'Notes' };
    return { icon: 'file-text', label: 'File' };
}

function materialMetaText(v, quizzes) {
    const kind = materialKind(v).label;
    if (v.material_type === 'link') {
        let host = '';
        try { host = new URL(v.source_url).hostname; } catch (e) { /* not a URL */ }
        return `${kind}${host ? ', ' + host : ''}`;
    }
    if (v.status === 'saved') return `${kind}, saved`;
    if (v.status === 'processing') return `${kind}, importing`;
    if (v.status === 'failed') return `${kind}, import failed`;
    const quiz = (quizzes || []).find(q => String(q.video_id) === String(v.id));
    return `${kind}${quiz ? ', stage ' + (quiz.srs_stage || 0) : ''}`;
}

function goalPageRowHTML(v, quizzes, editing) {
    const kind = materialKind(v);
    const handle = editing ? '<i data-lucide="grip-vertical" class="drag-handle w-4 h-4 text-stone-400 cursor-grab shrink-0"></i>' : '';
    let action = '';
    if (editing) {
        const moveTo = goalPageFolders(v.learning_goal_id).length > 0
            ? `<button type="button" data-goalpage-moveto="${v.id}" class="p-1.5 bg-stone-100 border border-stone-200 rounded-lg text-stone-600" aria-label="Move to a folder" title="Move to a folder"><i data-lucide="folder-input" class="w-4 h-4"></i></button>`
            : '';
        action = `${moveTo}
            <button type="button" data-goalpage-move="up" data-video-id="${v.id}" class="p-1.5 bg-stone-100 border border-stone-200 rounded-lg text-stone-600" aria-label="Move up"><i data-lucide="arrow-up" class="w-4 h-4"></i></button>
            <button type="button" data-goalpage-move="down" data-video-id="${v.id}" class="p-1.5 bg-stone-100 border border-stone-200 rounded-lg text-stone-600" aria-label="Move down"><i data-lucide="arrow-down" class="w-4 h-4"></i></button>`;
    } else if (v.material_type === 'link') {
        action = `<button type="button" data-video-action="open-link" data-video-id="${v.id}" class="px-3 py-1.5 bg-stone-100 hover:bg-stone-200 border border-stone-200 rounded-lg text-xs font-extrabold text-stone-600 flex items-center gap-1"><i data-lucide="external-link" class="w-3.5 h-3.5"></i>Open</button>`;
    } else if (v.status === 'saved') {
        action = `<button type="button" data-video-action="generate-saved" data-video-id="${v.id}" class="px-3 py-1.5 bg-amber-50 hover:bg-amber-100 border border-amber-300 rounded-lg text-xs font-extrabold text-amber-900 flex items-center gap-1"><i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-600"></i>Generate</button>`;
    } else if (v.status === 'failed') {
        action = `<button type="button" data-video-action="retry" data-video-id="${v.id}" class="px-3 py-1.5 bg-red-50 border border-red-200 rounded-lg text-xs font-extrabold text-red-600">Retry</button>`;
    } else if (v.status !== 'processing') {
        const level = v.importance_rating || v.importance_level || 3;
        action = `<button type="button" data-video-action="study" data-video-id="${v.id}" data-level="${level}" class="px-3 py-1.5 bg-stone-100 hover:bg-stone-200 border border-stone-200 rounded-lg text-xs font-extrabold text-stone-600 flex items-center gap-1"><i data-lucide="brain" class="w-3.5 h-3.5"></i>Quiz</button>`;
    }
    const titleAction = 'open-studio';
    const metaClass = v.status === 'saved' ? 'text-amber-700' : 'text-stone-500';
    return `
        <div id="video-card-${v.id}" data-goalpage-row="${v.id}" ${editing ? 'draggable="true"' : ''} class="flex items-center gap-3 bg-white border border-stone-200 rounded-xl px-3 py-2.5 shadow-sm">
            ${handle}
            ${renderMediaThumbHTML(v, { sizeClasses: 'w-14 h-9', attrs: `data-video-action="${titleAction}" data-video-id="${v.id}" draggable="false"`, title: escapeHtml(kind.label) })}
            <div class="min-w-0 flex-1">
                <button type="button" data-video-action="${titleAction}" data-video-id="${v.id}" class="block font-bold text-sm text-stone-900 truncate text-left max-w-full hover:text-amber-700 transition">${escapeHtml(v.title)}</button>
                <p class="text-[11px] ${metaClass}">${escapeHtml(materialMetaText(v, quizzes))}</p>
            </div>
            <div class="flex items-center gap-1 shrink-0">${action}</div>
        </div>`;
}

function goalPageFolderRowHTML(f, count, editing) {
    return `
        <div data-goalpage-folder="${f.id}" class="goalpage-folder flex items-center bg-white border border-stone-200 rounded-xl shadow-sm">
            <button type="button" data-goalpage-action="open-folder" data-folder-id="${f.id}" class="flex items-center gap-3 min-w-0 flex-1 text-left px-3 py-2.5 focus:outline-none">
                <i data-lucide="folder" class="w-5 h-5 text-amber-600 shrink-0"></i>
                <span class="min-w-0 flex-1">
                    <span class="block font-bold text-sm text-stone-900 truncate">${escapeHtml(f.name)}</span>
                    <span class="block text-[11px] text-stone-500">${count} ${count === 1 ? 'material' : 'materials'}</span>
                </span>
                <i data-lucide="chevron-right" class="w-4 h-4 text-stone-400 shrink-0"></i>
            </button>
        </div>`;
}

function renderGoalPage() {
    const page = document.getElementById('goal-page');
    const goalId = window._openGoalPageId;
    if (!page || !goalId) return;
    const data = window._goalsPageData || { goals: [], videos: [], quizzes: [], folders: [] };
    const goal = data.goals.find(g => g.id === goalId);
    if (!goal) { goBackFromGoalPage(); return; }

    const rank = data.goals.findIndex(g => g.id === goalId) + 1;
    const allMaterials = goalPageMaterials(goalId);
    const folders = goalPageFolders(goalId);
    const folderId = goalPageFolderId(goalId);
    const folder = folders.find(f => f.id === folderId) || null;
    const materials = goalPageScopeMaterials(goalId);
    const view = goalPageView();
    const editing = goalPageState.reordering;
    const seg = (label, on, action) => `<button type="button" data-goalpage-action="${action}" class="px-3 py-1.5 rounded-lg text-xs font-bold ${on ? 'bg-amber-100 border border-amber-300 text-amber-900' : 'text-stone-600'}">${label}</button>`;
    const asList = view === 'list' || editing;
    const materialHTML = v => asList ? goalPageRowHTML(v, data.quizzes, editing) : renderVideoCard(v, data.quizzes, data.goals);
    const wrap = html => asList ? `<div class="space-y-2">${html}</div>` : `<div class="space-y-3">${html}</div>`;

    // Folders come first, then the materials outside any folder. While the search is open, the
    // materials inside folders are drawn hidden too so a match can reveal them (applyGoalPageSearch).
    let body = '';
    if (!folder && folders.length > 0) {
        body += `<div class="space-y-2">${folders.map(f => goalPageFolderRowHTML(f, allMaterials.filter(v => v.folder_id === f.id).length, editing)).join('')}</div>`;
    }
    if (folder && editing) {
        body += '<div data-goalpage-folder="0" class="goalpage-folder border-2 border-dashed border-amber-300 rounded-xl px-3 py-3 text-xs font-bold text-amber-800 text-center">Drop a material here to take it out of the folder</div>';
    }
    if (materials.length > 0) {
        body += wrap(materials.map(materialHTML).join(''))
            + (editing ? '<p class="text-[11px] text-stone-500 text-center"><span class="drag-hint">Drag the handle, drop a material on a folder, or use the buttons.</span><span class="touch-hint">Use the buttons.</span> Changes save as you go.</p>' : '');
    } else if (folder) {
        body += '<p class="text-xs text-stone-400 italic py-2 pl-2">This folder is empty. Use Rearrange on the goal to move materials in.</p>';
    } else if (folders.length === 0) {
        body += '<p class="text-xs text-stone-400 italic py-2 pl-2">No learning materials added to this goal yet.</p>';
    }
    if (!folder && goalPageState.searchOpen && !editing) {
        const inFolders = allMaterials.filter(v => v.folder_id);
        if (inFolders.length > 0) body += `<div data-folder-material class="hidden">${wrap(inFolders.map(materialHTML).join(''))}</div>`;
    }

    const actionBtn = 'px-3 py-2 bg-white hover:bg-stone-50 border border-stone-200 rounded-xl text-xs font-bold text-stone-700 flex items-center gap-1.5 shadow-sm transition';
    const header = folder ? `
        <button type="button" data-goalpage-action="close-folder" class="flex items-center gap-1.5 text-sm font-bold text-amber-700 hover:text-amber-900 transition">
            <i data-lucide="arrow-left" class="w-4 h-4"></i><span>${escapeHtml(goal.title)}</span>
        </button>
        <div class="flex items-center gap-3 min-w-0">
            <i data-lucide="folder" class="w-6 h-6 text-amber-600 shrink-0"></i>
            <h2 class="text-2xl font-bold tracking-tight leading-tight truncate">${escapeHtml(folder.name)}</h2>
        </div>
        <p class="text-xs text-stone-400">${materials.length} ${materials.length === 1 ? 'material' : 'materials'}</p>` : `
        <button type="button" data-goalpage-action="back" class="flex items-center gap-1.5 text-sm font-bold text-amber-700 hover:text-amber-900 transition">
            <i data-lucide="arrow-left" class="w-4 h-4"></i><span>Goals</span>
        </button>
        <div class="bg-white border border-stone-200 p-5 rounded-2xl space-y-4 shadow-sm">
            <div class="flex items-center justify-between gap-3">
                <div class="flex items-center space-x-3 min-w-0">${goalRankBadgeHTML(rank)}<h2 class="text-2xl font-bold tracking-tight leading-tight">${escapeHtml(goal.title)}</h2></div>
                <div class="flex items-center gap-2 shrink-0">
                    <button type="button" data-goal-action="edit" data-goal-id="${goalId}" class="${actionBtn}" aria-label="Edit goal"><i data-lucide="edit-3" class="w-3.5 h-3.5 text-amber-600"></i><span class="hidden sm:inline">Edit</span></button>
                </div>
            </div>
            ${goal.description ? `<p class="text-sm text-stone-500">${escapeHtml(goal.description)}</p>` : ''}
            ${goalRecsSectionHTML(goal)}
        </div>
        <p class="text-xs text-stone-400">${allMaterials.length} ${allMaterials.length === 1 ? 'material' : 'materials'}${folders.length ? `, ${folders.length} ${folders.length === 1 ? 'folder' : 'folders'}` : ''}</p>`;

    page.innerHTML = `
        ${header}
        <div class="flex items-center justify-between gap-2">
            <div class="flex gap-1 p-1 bg-stone-100 border border-stone-200 rounded-xl">${seg('Detail', view === 'detail' && !editing, 'view-detail')}${seg('List', view === 'list' || editing, 'view-list')}</div>
            <div class="flex items-center gap-2">
                ${allMaterials.length > 0 && !editing ? `<button type="button" data-goalpage-action="toggle-search" aria-pressed="${goalPageState.searchOpen}" class="p-2.5 border rounded-xl shadow-sm transition ${goalPageState.searchOpen ? 'bg-amber-100 border-amber-300 text-amber-900' : 'bg-white border-stone-200 text-stone-700 hover:bg-stone-50'}" title="Search this goal's materials" aria-label="Search this goal's materials"><i data-lucide="search" class="w-4 h-4"></i></button>` : ''}
                ${editing
                    ? '<button type="button" data-goalpage-action="toggle-reorder" class="btn-primary px-4 py-2 rounded-xl text-xs font-extrabold">Done</button>'
                    : '<button type="button" id="btn-goalpage-menu" data-goalpage-action="menu" class="p-2.5 bg-white border border-stone-200 rounded-xl text-stone-700 hover:bg-stone-50 shadow-sm transition" title="More options" aria-label="More options" aria-haspopup="menu"><i data-lucide="more-vertical" class="w-4 h-4"></i></button>'}
                <button type="button" data-goal-action="add-material" data-goal-id="${goalId}" class="btn-primary px-3 py-2 rounded-xl text-xs font-extrabold flex items-center gap-1.5 whitespace-nowrap"><i data-lucide="plus" class="w-3.5 h-3.5"></i>Add material</button>
            </div>
        </div>
        <div id="goalpage-search-bar" class="${goalPageState.searchOpen && !editing ? '' : 'hidden'}" role="search">
            <label for="goalpage-search-input" class="sr-only">Search this goal's materials</label>
            <div class="relative">
                <i data-lucide="search" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-400 pointer-events-none"></i>
                <input type="search" id="goalpage-search-input" value="${escapeHtml(goalPageState.query)}" placeholder="Search this goal's materials" autocomplete="off" enterkeyhint="search" maxlength="100"
                    class="goals-search-input w-full pl-10 pr-10 py-2.5 bg-[#fcfaf6] border border-[#e7dfd3] rounded-xl text-sm text-stone-900 focus:outline-none focus:border-amber-500 transition">
                <button type="button" data-goalpage-action="clear-search" id="btn-goalpage-search-clear" aria-label="Clear search" class="hidden absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>
        </div>
        <p id="goalpage-search-empty" class="hidden text-center text-sm text-stone-500 py-6">No materials in this goal match your search.</p>
        ${body}`;
    applyGoalPageSearch();
    // The drawer is drawn fresh with the page, so fill it from what is already loaded.
    if (!folder && window._openGoalRecommendations && window._openGoalRecommendations[goalId]) {
        populateRecommendationDrawer(goalId, window._openGoalRecommendations[goalId]);
    }
    if (typeof renderIcons === 'function') renderIcons();
}

// Hides the materials on the open goal page that do not match the query, by title. The page is
// redrawn from scratch on every state change, so this runs after each draw as well as on typing.
function applyGoalPageSearch() {
    const page = document.getElementById('goal-page');
    const goalId = window._openGoalPageId;
    if (!page || !goalId) return;
    const terms = normalizeSearchText(goalPageState.searchOpen ? goalPageState.query : '').split(/\s+/).filter(Boolean);
    const searching = terms.length > 0;
    const titles = {};
    goalPageMaterials(goalId).forEach(v => { titles[v.id] = v.title; });
    let shown = 0;
    page.querySelectorAll('[id^="video-card-"]').forEach(card => {
        const matches = !searching || matchesSearchTerms(titles[card.id.replace('video-card-', '')], terms);
        // A material inside a folder is drawn hidden and only appears when it matches.
        const folderWrap = card.closest('[data-folder-material]');
        if (folderWrap) folderWrap.classList.toggle('hidden', !(searching && matches));
        card.classList.toggle('search-miss', searching && !matches);
        if (searching ? matches : !folderWrap) shown++;
    });
    // While searching, the folders step aside: their materials are listed flat among the results.
    page.querySelectorAll('[data-goalpage-folder]').forEach(row => row.classList.toggle('search-miss', searching));
    page.querySelector('#goalpage-search-empty')?.classList.toggle('hidden', !searching || shown > 0);
    page.querySelector('#btn-goalpage-search-clear')?.classList.toggle('hidden', !searching);
}

function openGoalPage(goalId, push = true) {
    if (!window._goalsCache || !window._goalsCache[goalId]) return;
    const tab = document.getElementById('tab-goals');
    if (!tab) return;
    const alreadyOpen = window._openGoalPageId === goalId && tab.classList.contains('goal-page-open');
    if (!alreadyOpen) Object.assign(goalPageState, { reordering: false, query: '', searchOpen: false, folderId: null });
    window._openGoalPageId = goalId;
    tab.classList.add('goal-page-open');
    renderGoalPage();
    if (alreadyOpen) return;
    // Scroll to the top before the page fades in, so it does not appear to jump after it shows.
    window.scrollTo(0, 0);
    playPageAnimation(document.getElementById('goal-page'), 'goal-page-enter');
    try { localStorage.setItem(GOAL_PAGE_STORE_KEY, String(goalId)); } catch (e) { /* storage blocked */ }
    if (push) history.pushState({ goalPage: goalId }, '', `#goal-${goalId}`);
}

// Hides the page. Going back through history is the caller's job (see goBackFromGoalPage).
function closeGoalPage() {
    window._openGoalPageId = null;
    Object.assign(goalPageState, { reordering: false, query: '', searchOpen: false, folderId: null });
    try { localStorage.removeItem(GOAL_PAGE_STORE_KEY); } catch (e) { /* storage blocked */ }
    const tab = document.getElementById('tab-goals');
    tab?.classList.remove('goal-page-open');
    // A page reached without a history entry of its own (a reload that landed on it directly)
    // still has its hash in the address bar; drop it so a reload does not reopen the page.
    if (location.hash.startsWith('#goal-')) history.replaceState(history.state, '', location.pathname + location.search);
    // Emptied so the page's copy of the goal's per-goal ids is gone before the card draws its own.
    const page = document.getElementById('goal-page');
    if (page) page.innerHTML = '';
    // Redraw the goal cards: their counts may have changed on the page.
    loadGoals().then(() => playPageAnimation(document.getElementById('goals-container'), 'goal-page-enter'));
}

// Plays a short fade-in on an element and removes the class again when it ends, so the class is
// there to be added next time. Skipped for people who ask for reduced motion (see style.css).
function playPageAnimation(el, className) {
    if (!el) return;
    el.classList.remove(className);
    void el.offsetWidth;
    el.classList.add(className);
    el.addEventListener('animationend', () => el.classList.remove(className), { once: true });
}

// Reopens the goal page named by the address (#goal-<id>) after a reload, so reloading keeps you
// on the page instead of dropping you on the goals list. Waits for the goals to load: the page is
// drawn from them. Gives up quietly if the goal no longer exists.
function restoreGoalPageFromHash() {
    const match = /^#goal-(\d+)$/.exec(location.hash);
    let stored = null;
    try { stored = localStorage.getItem(GOAL_PAGE_STORE_KEY); } catch (e) { /* storage blocked */ }
    const raw = match ? match[1] : stored;
    if (!raw || !/^\d+$/.test(raw)) return;
    const goalId = Number(raw);
    const deadline = Date.now() + 6000;
    const attempt = () => {
        if (window._goalsCache && window._goalsCache[goalId]) { openGoalPage(goalId, false); return; }
        if (window._goalsLoaded || Date.now() >= deadline) {
            // The goal is gone (or never loaded): forget the page and drop a stale hash.
            try { localStorage.removeItem(GOAL_PAGE_STORE_KEY); } catch (e) { /* storage blocked */ }
            if (location.hash.startsWith('#goal-')) history.replaceState(null, '', location.pathname + location.search);
            return;
        }
        setTimeout(attempt, 150);
    };
    attempt();
}
window.restoreGoalPageFromHash = restoreGoalPageFromHash;

function goBackFromGoalPage() {
    if (history.state && history.state.goalPage) history.back();
    else closeGoalPage();
}

// The page shows the new order at once and saves it in the background; only a failed save
// reloads, to show what the server actually has.
async function saveMaterialOrder(goalId, ids) {
    const data = window._goalsPageData;
    if (data) {
        const byId = new Map(data.videos.filter(v => v.learning_goal_id === goalId).map(v => [v.id, v]));
        let next = 0;
        data.videos = data.videos.map(v => (byId.has(v.id) && ids.includes(v.id) ? byId.get(ids[next++]) : v));
        renderGoalPage();
    }
    const formData = new FormData();
    formData.append('ids', ids.join(','));
    try {
        await fetchAPI(`/api/goals/${goalId}/materials/order`, { method: 'POST', body: formData });
    } catch (e) {
        showToast('Could not save the order: ' + (e.message || e), 'failed', 3000);
        await loadGoals();
    }
}

// The order is stored for all of a goal's materials at once. A reorder inside one view (the goal
// or a folder) only permutes that view's materials, so it is written back into the full list at
// the positions those materials already held.
function saveScopeOrder(goalId, scopeIds) {
    const all = goalPageMaterials(goalId).map(v => v.id);
    const inScope = new Set(scopeIds);
    let next = 0;
    saveMaterialOrder(goalId, all.map(id => (inScope.has(id) ? scopeIds[next++] : id)));
}

function moveGoalMaterial(videoId, direction) {
    const goalId = window._openGoalPageId;
    const ids = goalPageScopeMaterials(goalId).map(v => v.id);
    const from = ids.indexOf(videoId);
    const to = direction === 'up' ? from - 1 : from + 1;
    if (from < 0 || to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to], ids[from]];
    saveScopeOrder(goalId, ids);
}

function dropGoalMaterial(draggedId, targetId) {
    const goalId = window._openGoalPageId;
    const ids = goalPageScopeMaterials(goalId).map(v => v.id);
    const from = ids.indexOf(draggedId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0 || from === to) return;
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    saveScopeOrder(goalId, ids);
}

// Moves a material into a folder of the open goal, or out of any folder when folderId is null.
// Shown at once, saved in the background; only a failed save reloads.
async function moveMaterialToFolder(videoId, folderId) {
    const goalId = window._openGoalPageId;
    const video = goalPageMaterials(goalId).find(v => v.id === videoId);
    if (video) {
        video.folder_id = folderId || null;
        renderGoalPage();
    }
    const formData = new FormData();
    if (folderId) formData.append('folder_id', folderId);
    try {
        await fetchAPI(`/api/goals/${goalId}/materials/${videoId}/folder`, { method: 'POST', body: formData });
    } catch (e) {
        showToast('Could not move it: ' + (e.message || e), 'failed', 3000);
        await loadGoals();
    }
}

function openFolderModal(folderId = null) {
    const goalId = window._openGoalPageId;
    const folder = folderId ? goalPageFolders(goalId).find(f => f.id === folderId) : null;
    document.getElementById('folder-modal-id').value = folder ? folder.id : '';
    document.getElementById('folder-modal-name').value = folder ? folder.name : '';
    document.getElementById('folder-modal-heading').textContent = folder ? 'Rename folder' : 'New folder';
    openOverlay('overlay-folder-modal', closeFolderModal);
    document.getElementById('folder-modal-name').focus();
}

function closeFolderModal() {
    closeOverlay('overlay-folder-modal');
    document.getElementById('overlay-folder-modal').classList.add('hidden');
}

function initFolderModal() {
    const form = document.getElementById('folder-modal-form');
    if (!form) return;
    document.getElementById('btn-close-folder-modal').addEventListener('click', closeFolderModal);
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const goalId = window._openGoalPageId;
        const folderId = document.getElementById('folder-modal-id').value;
        const formData = new FormData();
        formData.append('name', document.getElementById('folder-modal-name').value);
        try {
            const res = await fetchAPI(
                folderId ? `/api/goals/${goalId}/folders/${folderId}/rename` : `/api/goals/${goalId}/folders`,
                { method: 'POST', body: formData });
            closeFolderModal();
            await loadGoals();
            // A new folder is opened right away; a rename keeps the view where it was.
            if (!folderId && res && res.folder_id) { goalPageState.folderId = res.folder_id; renderGoalPage(); }
        } catch (err) {
            showToast(err.message || 'Could not save the folder.', 'failed', 3000);
        }
    });
}

async function deleteGoalFolder(folderId) {
    const goalId = window._openGoalPageId;
    const folder = goalPageFolders(goalId).find(f => f.id === folderId);
    if (!folder) return;
    const ok = await showConfirm({
        title: 'Delete this folder?',
        message: `"${folder.name}" is removed. Its materials stay in the goal.`,
        confirmText: 'Delete folder',
        icon: 'folder-x'
    });
    if (!ok) return;
    try {
        await fetchAPI(`/api/goals/${goalId}/folders/${folderId}`, { method: 'DELETE' });
        goalPageState.folderId = null;
    } catch (e) {
        showToast('Could not delete the folder: ' + (e.message || e), 'failed', 3000);
    }
    await loadGoals();
}

// The three-dot menu on the goal page: rearranging, folders.
function toggleGoalPageMenu(anchorEl) {
    const goalId = window._openGoalPageId;
    const folderId = goalPageFolderId(goalId);
    const item = (action, icon, label, cls = 'text-stone-700 hover:bg-stone-50') =>
        `<button type="button" data-goalpage-menu-action="${action}" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs ${cls} transition"><i data-lucide="${icon}" class="w-4 h-4 text-amber-600"></i><span>${label}</span></button>`;
    const canRearrange = goalPageScopeMaterials(goalId).length > 0
        && (goalPageScopeMaterials(goalId).length > 1 || goalPageFolders(goalId).length > 0 || folderId);
    const items = [];
    if (canRearrange) items.push(item('rearrange', 'move', 'Rearrange'));
    if (!folderId) items.push(item('new-folder', 'folder-plus', 'New folder'));
    if (folderId) {
        items.push(item('rename-folder', 'edit-3', 'Rename folder'));
        items.push('<div class="border-t border-stone-200 my-1"></div>');
        items.push(item('delete-folder', 'trash-2', 'Delete folder', 'text-red-500 hover:bg-red-50'));
    }
    toggleContextMenuPortal('portal-goalpage-menu', goalId, anchorEl, `<div class="py-1">${items.join('')}</div>`, {
        extraClasses: 'w-52 border border-stone-200',
        onMount: (portal) => portal.addEventListener('click', (e) => {
            const choice = e.target.closest('[data-goalpage-menu-action]');
            if (!choice) return;
            closeContextMenuPortal('portal-goalpage-menu');
            switch (choice.dataset.goalpageMenuAction) {
                case 'rearrange': goalPageState.reordering = true; Object.assign(goalPageState, { query: '', searchOpen: false }); renderGoalPage(); break;
                case 'new-folder': openFolderModal(); break;
                case 'rename-folder': openFolderModal(folderId); break;
                case 'delete-folder': deleteGoalFolder(folderId); break;
            }
        }),
    });
}

// "Move to a folder" for one material while rearranging: the goal's folders, or out of the open one.
function toggleMoveToMenu(anchorEl, videoId) {
    const goalId = window._openGoalPageId;
    const here = goalPageFolderId(goalId);
    const choices = goalPageFolders(goalId).filter(f => f.id !== here)
        .map(f => `<button type="button" data-moveto-folder="${f.id}" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 transition"><i data-lucide="folder" class="w-4 h-4 text-amber-600"></i><span class="truncate">${escapeHtml(f.name)}</span></button>`);
    if (here) choices.unshift('<button type="button" data-moveto-folder="" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 transition"><i data-lucide="corner-left-up" class="w-4 h-4 text-amber-600"></i><span>Out of this folder</span></button>');
    if (choices.length === 0) return;
    toggleContextMenuPortal('portal-goalpage-moveto', videoId, anchorEl, `<div class="py-1">${choices.join('')}</div>`, {
        extraClasses: 'w-52 border border-stone-200',
        onMount: (portal) => portal.addEventListener('click', (e) => {
            const choice = e.target.closest('[data-moveto-folder]');
            if (!choice) return;
            closeContextMenuPortal('portal-goalpage-moveto');
            moveMaterialToFolder(videoId, choice.dataset.movetoFolder ? Number(choice.dataset.movetoFolder) : null);
        }),
    });
}

function initGoalPage() {
    const page = document.getElementById('goal-page');
    if (!page || page.dataset.bound) return;
    page.dataset.bound = '1';
    page.addEventListener('click', (e) => {
        const act = e.target.closest('[data-goalpage-action]');
        if (act) {
            switch (act.dataset.goalpageAction) {
                case 'back': goBackFromGoalPage(); break;
                case 'view-detail': goalPageState.reordering = false; localStorage.setItem(GOAL_PAGE_VIEW_KEY, 'detail'); renderGoalPage(); break;
                case 'view-list': localStorage.setItem(GOAL_PAGE_VIEW_KEY, 'list'); renderGoalPage(); break;
                case 'toggle-reorder':
                    goalPageState.reordering = !goalPageState.reordering;
                    // Reordering works on the full list, so it starts from an unfiltered one.
                    if (goalPageState.reordering) Object.assign(goalPageState, { query: '', searchOpen: false });
                    renderGoalPage();
                    break;
                case 'toggle-search':
                    goalPageState.searchOpen = !goalPageState.searchOpen;
                    if (!goalPageState.searchOpen) goalPageState.query = '';
                    renderGoalPage();
                    if (goalPageState.searchOpen) document.getElementById('goalpage-search-input')?.focus();
                    break;
                case 'open-folder': goalPageState.folderId = Number(act.dataset.folderId); Object.assign(goalPageState, { query: '', searchOpen: false }); renderGoalPage(); window.scrollTo(0, 0); break;
                case 'close-folder': goalPageState.folderId = null; Object.assign(goalPageState, { reordering: false, query: '', searchOpen: false }); renderGoalPage(); window.scrollTo(0, 0); break;
                case 'menu': toggleGoalPageMenu(act); break;
                case 'clear-search':
                    goalPageState.query = '';
                    renderGoalPage();
                    document.getElementById('goalpage-search-input')?.focus();
                    break;
            }
            return;
        }
        const move = e.target.closest('[data-goalpage-move]');
        if (move) moveGoalMaterial(Number(move.dataset.videoId), move.dataset.goalpageMove);
        const moveTo = e.target.closest('[data-goalpage-moveto]');
        if (moveTo) toggleMoveToMenu(moveTo, Number(moveTo.dataset.goalpageMoveto));
    });
    page.addEventListener('input', (e) => {
        if (e.target.id !== 'goalpage-search-input') return;
        goalPageState.query = e.target.value;
        applyGoalPageSearch();
    });
    let dragged = null;
    page.addEventListener('dragstart', (e) => {
        const row = e.target.closest('[data-goalpage-row]');
        if (!row || !goalPageState.reordering) return;
        dragged = Number(row.dataset.goalpageRow);
        e.dataTransfer.effectAllowed = 'move';
    });
    page.addEventListener('dragover', (e) => {
        if (dragged === null) return;
        const folderRow = e.target.closest('[data-goalpage-folder]');
        page.querySelectorAll('.is-drop-target').forEach(el => { if (el !== folderRow) el.classList.remove('is-drop-target'); });
        if (folderRow) folderRow.classList.add('is-drop-target');
        if (folderRow || e.target.closest('[data-goalpage-row]')) e.preventDefault();
    });
    page.addEventListener('dragend', () => {
        dragged = null;
        page.querySelectorAll('.is-drop-target').forEach(el => el.classList.remove('is-drop-target'));
    });
    page.addEventListener('drop', (e) => {
        if (dragged === null) return;
        const id = dragged;
        // Dropped on a folder (0 is the zone that takes a material out of the open folder).
        const folderRow = e.target.closest('[data-goalpage-folder]');
        if (folderRow) {
            e.preventDefault();
            dragged = null;
            folderRow.classList.remove('is-drop-target');
            moveMaterialToFolder(id, Number(folderRow.dataset.goalpageFolder) || null);
            return;
        }
        const row = e.target.closest('[data-goalpage-row]');
        if (!row) return;
        e.preventDefault();
        dragged = null;
        dropGoalMaterial(id, Number(row.dataset.goalpageRow));
    });
    // The browser's back gesture closes the page; going forward again reopens it.
    window.addEventListener('popstate', (e) => {
        const goalsTabShown = !document.getElementById('tab-goals')?.classList.contains('hidden');
        if (e.state && e.state.goalPage) { if (goalsTabShown) openGoalPage(e.state.goalPage, false); }
        else if (window._openGoalPageId) closeGoalPage();
    });
}

window.setAllAccordions = setAllAccordions;
window.closeDeleteGoalModal = closeDeleteGoalModal;
window.confirmDeleteGoal = confirmDeleteGoal;

