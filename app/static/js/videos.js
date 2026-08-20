// --- Studiamo Videos & Content Import Module ---

const INVALID_SUMMARY_PLACEHOLDERS = [
    "no summary available",
    "no summary takeaways available.",
    "no summary takeaways available",
    "generating content in the background. please wait...",
    "generating content in the background"
];

function isRealSummaryBullet(s) {
    if (!s || typeof s !== 'string') return false;
    const clean = s.trim().toLowerCase();
    return clean.length > 0 &&
        !INVALID_SUMMARY_PLACEHOLDERS.includes(clean) &&
        !clean.startsWith("key concept preview for ") &&
        !clean.startsWith("import failed");
}

async function getUserQuestionCounts() {
    if (window._userQuestionCounts) return window._userQuestionCounts;
    try {
        const data = await fetchAPI('/api/settings');
        if (data && data.question_counts) {
            window._userQuestionCounts = {
                1: parseInt(data.question_counts.count_1) || 2,
                2: parseInt(data.question_counts.count_2) || 3,
                3: parseInt(data.question_counts.count_3) || 5,
                4: parseInt(data.question_counts.count_4) || 8,
                5: parseInt(data.question_counts.count_5) || 12
            };
            return window._userQuestionCounts;
        }
    } catch (e) {
        console.error("Failed to load user question counts from settings:", e);
    }
    return { 1: 2, 2: 3, 3: 5, 4: 8, 5: 12 };
}

function initImportanceStars() {
    const hiddenInput = document.getElementById('input-importance');
    const labelVal = document.getElementById('label-importance-value');
    const starBtns = document.querySelectorAll('.star-select-btn');
    const descTitle = document.getElementById('importance-desc-title');
    const descQs = document.getElementById('importance-desc-qs');
    const descText = document.getElementById('importance-desc-text');
    const infoToggle = document.getElementById('importance-info-toggle');
    const descBox = document.getElementById('importance-desc-box');

    if (infoToggle && descBox) {
        infoToggle.addEventListener('click', () => {
            const nowHidden = descBox.classList.toggle('hidden');
            infoToggle.setAttribute('aria-expanded', String(!nowHidden));
        });
    }

    async function updateStars(rating) {
        if (hiddenInput) hiddenInput.value = rating;
        const counts = await getUserQuestionCounts();

        const metaMap = {
            1: { title: "Reference Material (1 Star)", qs: `${counts[1] || 2} Recall Questions`, text: `Low recall density & scaled back repetition frequency. Generates ${counts[1] || 2} questions.` },
            2: { title: "Basic Concepts (2 Stars)", qs: `${counts[2] || 3} Recall Questions`, text: `Fundamental overview. Generates ${counts[2] || 3} active-recall questions.` },
            3: { title: "Standard Study (3 Stars)", qs: `${counts[3] || 5} Recall Questions`, text: `Standard quiz depth & review interval frequency. Generates ${counts[3] || 5} questions.` },
            4: { title: "High Detail (4 Stars)", qs: `${counts[4] || 8} Recall Questions`, text: `Comprehensive coverage with ${counts[4] || 8} recall questions for detailed retention.` },
            5: { title: "Crucial Retention (5 Stars)", qs: `${counts[5] || 12} Recall Questions`, text: `Maximum quiz density with ${counts[5] || 12} recall questions and high-priority SRS review schedule.` }
        };

        const info = metaMap[rating] || metaMap[3];
        if (labelVal) labelVal.textContent = info.title;
        if (descTitle) descTitle.textContent = info.title;
        if (descQs) descQs.textContent = info.qs;
        if (descText) descText.textContent = info.text;

        starBtns.forEach(btn => {
            const btnStar = parseInt(btn.dataset.star);
            const icon = btn.querySelector('.star-icon') || btn.querySelector('svg');
            if (icon) {
                if (btnStar <= rating) {
                    icon.setAttribute('fill', '#f59e0b');
                    icon.setAttribute('stroke', '#f59e0b');
                    icon.classList.add('scale-105');
                } else {
                    icon.setAttribute('fill', 'none');
                    icon.setAttribute('stroke', '#475569');
                    icon.classList.remove('scale-105');
                }
            }
        });
    }

    starBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const val = parseInt(btn.dataset.star);
            updateStars(val);
        });
    });

    updateStars(hiddenInput ? parseInt(hiddenInput.value) || 3 : 3);
}

window.getUserQuestionCounts = getUserQuestionCounts;
window.initImportanceStars = initImportanceStars;

window.renderGoalBoxes = function(goals) {
    const container = document.getElementById('input-goal-boxes');
    const selectedInput = document.getElementById('input-goal-selected-id');
    const newGoalFields = document.getElementById('new-goal-inline-fields');
    if (!container) return;

    let activeGoalId = selectedInput ? selectedInput.value : '';

    let html = `
        <div class="goal-select-card group border cursor-pointer rounded-xl p-3 flex items-center justify-between transition-all ${activeGoalId === '' ? 'border-amber-500 bg-amber-500/15 ring-1 ring-amber-500/30' : 'border-[#e7dfd3] bg-[#fcfaf6] hover:border-amber-500/40'}" data-goal-id="">
            <div class="flex items-center space-x-2.5 overflow-hidden">
                <div class="w-7 h-7 rounded-lg bg-[#f3ebd9] flex items-center justify-center text-amber-700 shrink-0">
                    <i data-lucide="inbox" class="w-4 h-4"></i>
                </div>
                <div class="truncate">
                    <h6 class="text-xs font-semibold ${activeGoalId === '' ? 'text-amber-900 font-bold' : 'text-stone-800'} truncate">Standalone / Unassociated</h6>
                    <p class="text-[10px] text-stone-500 truncate">General study material</p>
                </div>
            </div>
            <div class="w-4 h-4 rounded-full border flex items-center justify-center shrink-0 ${activeGoalId === '' ? 'border-amber-500 bg-[#fbbf24] text-[#78350f]' : 'border-stone-400'}">
                ${activeGoalId === '' ? '<i data-lucide="check" class="w-2.5 h-2.5"></i>' : ''}
            </div>
        </div>
    `;

    if (goals && Array.isArray(goals)) {
        goals.forEach((g, idx) => {
            const isSelected = activeGoalId === String(g.id);
            html += `
                <div class="goal-select-card group border cursor-pointer rounded-xl p-3 flex items-center justify-between transition-all ${isSelected ? 'border-amber-500 bg-amber-500/15 ring-1 ring-amber-500/30' : 'border-[#e7dfd3] bg-[#fcfaf6] hover:border-amber-500/40'}" data-goal-id="${g.id}">
                    <div class="flex items-center space-x-2.5 overflow-hidden">
                        <div class="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-600 font-bold text-[10px] flex items-center justify-center shrink-0">
                            #${idx + 1}
                        </div>
                        <div class="truncate">
                            <h6 class="text-xs font-semibold ${isSelected ? 'text-amber-900 font-bold' : 'text-stone-800'} truncate">${escapeHtml(g.title)}</h6>
                            <p class="text-[10px] text-stone-500 truncate">${escapeHtml(g.description) || 'Learning Goal'}</p>
                        </div>
                    </div>
                    <div class="w-4 h-4 rounded-full border flex items-center justify-center shrink-0 ${isSelected ? 'border-amber-500 bg-[#fbbf24] text-[#78350f]' : 'border-stone-400'}">
                        ${isSelected ? '<i data-lucide="check" class="w-2.5 h-2.5"></i>' : ''}
                    </div>
                </div>
            `;
        });
    }

    const isNewSelected = activeGoalId === 'new';
    html += `
        <div class="goal-select-card group border cursor-pointer rounded-xl p-3 flex items-center justify-between transition-all ${isNewSelected ? 'border-amber-500 bg-amber-500/15 ring-1 ring-amber-500/30' : 'border-dashed border-[#e7dfd3] bg-[#fcfaf6] hover:border-amber-500/50'}" data-goal-id="new">
            <div class="flex items-center space-x-2.5 overflow-hidden">
                <div class="w-7 h-7 rounded-lg bg-amber-500/20 text-amber-800 flex items-center justify-center shrink-0">
                    <i data-lucide="plus" class="w-4 h-4"></i>
                </div>
                <div class="truncate">
                    <h6 class="text-xs font-bold ${isNewSelected ? 'text-amber-700' : 'text-amber-700'} truncate">+ Create New Goal</h6>
                    <p class="text-[10px] text-stone-500 truncate">Define goal on import</p>
                </div>
            </div>
            <div class="w-4 h-4 rounded-full border flex items-center justify-center shrink-0 ${isNewSelected ? 'border-amber-200 bg-[#fbbf24] text-[#78350f]' : 'border-stone-200'}">
                ${isNewSelected ? '<i data-lucide="check" class="w-2.5 h-2.5"></i>' : ''}
            </div>
        </div>
    `;

    container.innerHTML = html;
    if (typeof renderIcons === 'function') renderIcons();

    const cards = container.querySelectorAll('.goal-select-card');
    cards.forEach(card => {
        card.addEventListener('click', () => {
            const goalId = card.dataset.goalId;
            if (selectedInput) selectedInput.value = goalId;
            if (newGoalFields) {
                if (goalId === 'new') {
                    newGoalFields.classList.remove('hidden');
                } else {
                    newGoalFields.classList.add('hidden');
                }
            }
            renderGoalBoxes(goals);
        });
    });
};

function initImportTab() {
    const form = document.getElementById('import-form');
    const inputImportance = document.getElementById('input-importance');
    
    initImportanceStars();

    if (window._goalsCache) {
        window.renderGoalBoxes(Object.values(window._goalsCache));
    }
    
    const btnYt = document.getElementById('import-btn-youtube');
    const btnDoc = document.getElementById('import-btn-document');
    const btnNotes = document.getElementById('import-btn-notes');
    
    const panelYt = document.getElementById('panel-youtube');
    const panelDoc = document.getElementById('panel-document');
    const panelNotes = document.getElementById('panel-notes');
    
    function resetImportPanels() {
        if (panelYt) panelYt.classList.add('hidden');
        if (panelDoc) panelDoc.classList.add('hidden');
        if (panelNotes) panelNotes.classList.add('hidden');
        
        const inactiveClass = "py-2.5 text-xs font-semibold rounded-lg text-stone-600 hover:text-amber-900 transition-all flex items-center justify-center space-x-1.5";
        if (btnYt) btnYt.className = inactiveClass;
        if (btnDoc) btnDoc.className = inactiveClass;
        if (btnNotes) btnNotes.className = inactiveClass;
    }
    
    function setTab(tab) {
        resetImportPanels();
        const activeClass = "py-2.5 text-xs font-bold rounded-lg text-amber-900 bg-amber-500/20 border border-amber-500/40 shadow-2xs transition-all flex items-center justify-center space-x-1.5";
        if (tab === 'youtube') {
            if (panelYt) panelYt.classList.remove('hidden');
            if (btnYt) btnYt.className = activeClass;
        } else if (tab === 'document') {
            if (panelDoc) panelDoc.classList.remove('hidden');
            if (btnDoc) btnDoc.className = activeClass;
        } else if (tab === 'notes') {
            if (panelNotes) panelNotes.classList.remove('hidden');
            if (btnNotes) btnNotes.className = activeClass;
        }
    }

    if (btnYt) btnYt.addEventListener('click', () => setTab('youtube'));
    if (btnDoc) btnDoc.addEventListener('click', () => setTab('document'));
    if (btnNotes) btnNotes.addEventListener('click', () => setTab('notes'));
    
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('input-file-upload');
    const fileInfo = document.getElementById('selected-file-info');
    const fileNameText = document.getElementById('selected-file-name');
    const btnClearFile = document.getElementById('btn-clear-file');
    
    if (dropZone && fileInput) {
        dropZone.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleFileSelected(e.target.files[0]);
        });
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('border-amber-500', 'bg-amber-50');
        });
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('border-amber-500', 'bg-amber-50');
        });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('border-amber-500', 'bg-amber-50');
            if (e.dataTransfer.files.length > 0) handleFileSelected(e.dataTransfer.files[0]);
        });
    }
    
    function handleFileSelected(file) {
        if (fileNameText) fileNameText.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        if (fileInfo) fileInfo.classList.remove('hidden');
        if (dropZone) dropZone.classList.add('hidden');
    }
    
    if (btnClearFile) {
        btnClearFile.addEventListener('click', () => {
            if (fileInput) fileInput.value = '';
            if (fileInfo) fileInfo.classList.add('hidden');
            if (dropZone) dropZone.classList.remove('hidden');
        });
    }
    
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const isYoutubeVisible = panelYt && !panelYt.classList.contains('hidden');
            const isDocVisible = panelDoc && !panelDoc.classList.contains('hidden');
            
            if (isDocVisible || (!isYoutubeVisible && !isDocVisible)) {
                showLoader("Analyzing Document Content", "Gemini is analyzing document sections, auto-categorizing, and generating active recall questions.");
            } else {
                showLoader("Generating AI Quizzes & Summaries", "Gemini is extracting video content, auto-categorizing, and generating active recall questions.");
            }
            
            const formData = new FormData();
            formData.append('importance_rating', inputImportance ? inputImportance.value : 3);

            if (isYoutubeVisible) {
                const urlVal = document.getElementById('input-youtube-url').value;
                if (!urlVal) {
                    if (typeof showToast === 'function') {
                        showToast('Please enter a YouTube video URL', 'failed');
                    } else {
                        alert('Please enter a YouTube video URL');
                    }
                    hideLoader();
                    return;
                }
                formData.append('url', urlVal);
            } else if (isDocVisible) {
                if (!fileInput || fileInput.files.length === 0) {
                    if (typeof showToast === 'function') {
                        showToast('Please select a PDF or Text file to upload', 'failed');
                    } else {
                        alert('Please select a PDF or Text file to upload');
                    }
                    hideLoader();
                    return;
                }
                formData.append('file', fileInput.files[0]);
            } else {
                const titleVal = document.getElementById('input-notes-title').value;
                const textVal = document.getElementById('input-notes-text').value;
                if (!textVal) {
                    if (typeof showToast === 'function') {
                        showToast('Please paste some text content', 'failed');
                    } else {
                        alert('Please paste some text content');
                    }
                    hideLoader();
                    return;
                }
                formData.append('title', titleVal);
                formData.append('text_content', textVal);
            }

            const selectedGoalInput = document.getElementById('input-goal-selected-id');
            let learningGoalId = selectedGoalInput ? selectedGoalInput.value : '';

            if (learningGoalId === 'new') {
                const newTitleInput = document.getElementById('input-new-goal-title');
                const newDescInput = document.getElementById('input-new-goal-desc');
                const newTitle = newTitleInput ? newTitleInput.value.trim() : '';
                const newDesc = newDescInput ? newDescInput.value.trim() : '';

                if (!newTitle) {
                    if (typeof showToast === 'function') {
                        showToast('Please enter a title for your learning goal', 'failed');
                    } else {
                        alert('Please enter a title for your new learning goal.');
                    }
                    hideLoader();
                    return;
                }

                try {
                    const goalForm = new FormData();
                    goalForm.append('title', newTitle);
                    if (newDesc) goalForm.append('description', newDesc);
                    const newGoal = await fetchAPI('/api/goals', { method: 'POST', body: goalForm });
                    // POST /api/goals returns the new id as `goal_id`, not `id` (see the
                    // recommended-goal call further down, which reads the right one). Reading
                    // the wrong key left learningGoalId as the literal string 'new', which the
                    // guard below then skipped, so the material imported with no goal attached
                    // and turned up under Unassociated.
                    const newGoalId = newGoal && (newGoal.goal_id ?? newGoal.id);
                    if (newGoalId) {
                        learningGoalId = newGoalId;
                    } else {
                        console.error('Goal created but no id in response:', newGoal);
                        if (typeof showToast === 'function') {
                            showToast('Goal created, but the material could not be linked to it.', 'failed', 4000);
                        }
                    }
                } catch (errGoal) {
                    // Surface the server's reason, which since goal titles became unique is
                    // usually "You already have a goal called X" rather than a real failure.
                    const reason = errGoal.detail || errGoal.message || errGoal;
                    if (typeof showToast === 'function') {
                        showToast('Could not create the goal: ' + reason, 'failed', 4000);
                    } else {
                        alert('Failed to create new learning goal: ' + reason);
                    }
                    hideLoader();
                    return;
                }
            }

            if (learningGoalId && learningGoalId !== 'new') {
                formData.append('learning_goal_id', learningGoalId);
            }

            try {
                if (typeof showToast === 'function') {
                    showToast('Importing material & generating questions...', 'loading', 0);
                }
                const result = await fetchAPI('/api/videos', {
                    method: 'POST',
                    body: formData
                });
                
                document.getElementById('input-youtube-url').value = '';
                document.getElementById('input-notes-title').value = '';
                document.getElementById('input-notes-text').value = '';
                if (fileInput) fileInput.value = '';
                if (fileInfo) fileInfo.classList.add('hidden');
                if (dropZone) dropZone.classList.remove('hidden');
                
                if (result.recommended_new_goal) {
                    const confirmFn = window.showConfirm || (typeof showConfirm === 'function' ? showConfirm : null);
                    let conf = false;
                    if (confirmFn) {
                        conf = await confirmFn({
                            title: "Create Recommended Goal?",
                            message: `AI Recommendation:\nThis material doesn't fit your active goals.\nShould we create a new Goal: "${result.recommended_new_goal.title}"?`,
                            confirmText: "Create Goal",
                            icon: "sparkles"
                        });
                    } else {
                        conf = confirm(`AI Recommendation:\nThis material doesn't fit your active goals. Should we create a new Goal: "${result.recommended_new_goal.title}"?`);
                    }
                    if (conf) {
                        const goalForm = new FormData();
                        goalForm.append('title', result.recommended_new_goal.title);
                        goalForm.append('description', result.recommended_new_goal.description);
                        const newGoal = await fetchAPI('/api/goals', { method: 'POST', body: goalForm });
                        
                        const mapForm = new FormData();
                        mapForm.append('learning_goal_id', newGoal.goal_id);
                        await fetchAPI(`/api/videos/${result.video_id}/goal`, { method: 'POST', body: mapForm });
                    }
                }
                // Switch first so the dashboard is the visible tab, then await the reload:
                // the new card cannot be scrolled to before loadDashboard has rendered it.
                if (typeof switchTab === 'function') switchTab('dashboard');
                if (typeof loadDashboard === 'function') await loadDashboard();
                if (typeof loadGoals === 'function') loadGoals();

                if (window.globalImportBacklog) {
                    window.globalImportBacklog.toggleDrawer(true);
                    window.globalImportBacklog.poll();
                }

                scrollToVideoCard(result.video_id);

                // Only queued at this point , the completion toast fires from the
                // import backlog poll once the task actually finishes.
                if (typeof showToast === 'function') {
                    showToast('Import started, you can keep working.', 'saved', 2500);
                }
            } catch (err) {
                console.error("Video creation error:", err);
                if (typeof showToast === 'function') {
                    showToast('Import failed: ' + (err.detail || err.message || err), 'failed', 4000);
                } else {
                    alert('Failed to add video resource: ' + (err.detail || err.message || err));
                }
            }
        });
    }
}

// --- Learning Focus overlay ---------------------------------------------------------------
// Lets the user pick which topics feed their active recall quiz, per SRS stage. Everything is
// local once the pool is fetched: the questions already exist in quizzes.concept_pool, so
// changing focus costs no AI call and no regeneration.

let focusState = null;

function renderFocusStageTabs() {
    const tabs = document.getElementById('focus-stage-tabs');
    if (!tabs || !focusState) return;

    tabs.innerHTML = focusState.stages.map(s => {
        const active = s.stage === focusState.activeStage;
        const cls = active
            ? 'bg-amber-100 border-amber-300 text-amber-900'
            : 'bg-white border-[#e7dfd3] text-stone-600 hover:bg-stone-50';
        return `<button data-stage-tab="${s.stage}" title="${escapeHtml(s.label)}"
            class="shrink-0 px-3 py-1.5 rounded-lg border text-[11px] font-bold transition ${cls}">
            Stage ${s.stage}
        </button>`;
    }).join('');

    tabs.querySelectorAll('[data-stage-tab]').forEach(btn => {
        btn.addEventListener('click', () => {
            focusState.activeStage = parseInt(btn.dataset.stageTab, 10);
            renderFocusStageTabs();
            renderFocusTopics();
        });
    });
}

function currentFocusStage() {
    if (!focusState) return null;
    return focusState.stages.find(s => s.stage === focusState.activeStage) || null;
}

function renderFocusTopics() {
    const list = document.getElementById('focus-topic-list');
    const stage = currentFocusStage();
    if (!list || !stage) return;

    list.innerHTML = stage.topics.map((t, i) => `
        <label class="flex items-center justify-between gap-2 p-2.5 rounded-xl border border-[#e7dfd3] hover:bg-stone-50 cursor-pointer transition">
            <span class="flex items-center gap-2.5 min-w-0">
                <input type="checkbox" data-topic-index="${i}" ${t.selected ? 'checked' : ''}
                    class="w-4 h-4 rounded border-stone-300 text-amber-600 focus:ring-amber-500 shrink-0">
                <span class="text-xs font-semibold text-stone-800 truncate">${escapeHtml(t.topic)}</span>
            </span>
            <span class="flex items-center gap-1.5 shrink-0">
                ${t.recommended ? '<span class="text-[9px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5">AI</span>' : ''}
                <span class="text-[10px] text-stone-500 font-medium">${t.count} ${t.count === 1 ? 'question' : 'questions'}</span>
            </span>
        </label>
    `).join('');

    list.querySelectorAll('[data-topic-index]').forEach(box => {
        box.addEventListener('change', () => {
            stage.topics[parseInt(box.dataset.topicIndex, 10)].selected = box.checked;
            renderFocusStatus();
        });
    });

    renderFocusStatus();
}

function renderFocusStatus() {
    const el = document.getElementById('focus-status');
    const stage = currentFocusStage();
    if (!el || !stage) return;

    const selected = stage.topics.filter(t => t.selected).reduce((n, t) => n + t.count, 0);
    const target = focusState.targetCount;

    // Selecting more than the star rating serves is fine, the quiz takes the first `target`.
    // Selecting fewer is the case worth warning about, because it shortens the session.
    let cls, text;
    if (selected === 0) {
        cls = 'bg-red-50 border-red-200 text-red-700';
        text = 'No topics selected. Pick at least one to keep reviewing this material.';
    } else if (selected < target) {
        cls = 'bg-amber-50 border-amber-200 text-amber-800';
        text = `Only ${selected} question${selected === 1 ? '' : 's'} selected. This material is set to ${target} per session.`;
    } else {
        cls = 'bg-emerald-50 border-emerald-200 text-emerald-800';
        text = `${selected} questions selected. The ${target} best-fitting will be used each session.`;
    }
    el.className = `text-xs font-semibold rounded-xl px-3 py-2 border ${cls}`;
    el.textContent = text;
}

async function openFocusModal(videoId) {
    const overlay = document.getElementById('overlay-focus');
    if (!overlay) return;

    try {
        const data = await fetchAPI(`/api/videos/${videoId}/concept-pool`);
        if (!data.stages || data.stages.length === 0) {
            showToast('No topics were extracted for this material.', 'failed', 3500);
            return;
        }

        focusState = {
            videoId: videoId,
            targetCount: data.target_count,
            stages: data.stages,
            // Open on the stage the learner is actually on, not always stage 0.
            activeStage: data.stages.some(s => s.stage === data.current_stage)
                ? data.current_stage
                : data.stages[0].stage
        };

        const subtitle = document.getElementById('focus-modal-subtitle');
        if (subtitle) subtitle.textContent = data.title || '';

        overlay.classList.remove('hidden');
        renderFocusStageTabs();
        renderFocusTopics();
        renderIcons();
    } catch (e) {
        showToast('Could not load topics: ' + (e.detail || e.message || e), 'failed', 4000);
    }
}

function closeFocusModal() {
    const overlay = document.getElementById('overlay-focus');
    if (overlay) overlay.classList.add('hidden');
    focusState = null;
}

async function saveFocusSelection() {
    if (!focusState) return;
    const btn = document.getElementById('btn-focus-save');

    const payload = {};
    focusState.stages.forEach(s => {
        payload[`stage_${s.stage}`] = s.topics.filter(t => t.selected).map(t => t.topic);
    });

    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }
    try {
        const form = new FormData();
        form.append('focus_topics', JSON.stringify(payload));
        const res = await fetchAPI(`/api/videos/${focusState.videoId}/focus`, { method: 'POST', body: form });
        showToast(`Focus saved, ${res.active_questions} question${res.active_questions === 1 ? '' : 's'} active.`, 'saved', 3000);
        closeFocusModal();
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        showToast('Could not save focus: ' + (e.detail || e.message || e), 'failed', 4000);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Save focus'; }
    }
}

function resetFocusToRecommendation() {
    if (!focusState) return;
    focusState.stages.forEach(s => s.topics.forEach(t => { t.selected = t.recommended; }));
    renderFocusTopics();
}

function initFocusModalEvents() {
    const close = document.getElementById('btn-close-focus');
    const save = document.getElementById('btn-focus-save');
    const reset = document.getElementById('btn-focus-reset');
    const overlay = document.getElementById('overlay-focus');

    if (close) close.addEventListener('click', closeFocusModal);
    if (save) save.addEventListener('click', saveFocusSelection);
    if (reset) reset.addEventListener('click', resetFocusToRecommendation);
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeFocusModal();
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        const ov = document.getElementById('overlay-focus');
        if (ov && !ov.classList.contains('hidden')) closeFocusModal();
    });
}

// Brings a freshly queued import's card into view and flashes it, so the user can see where
// the material landed instead of hunting for it in the list.
//
// Polls rather than looking once: the card is created by loadDashboard's render pass, and a
// card placed under a goal can take an extra frame to appear. Gives up quietly, since failing
// to scroll must never look like the import itself failed.
async function scrollToVideoCard(videoId, timeoutMs = 4000) {
    if (!videoId) return false;

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const card = document.getElementById(`video-card-${videoId}`);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.classList.add('video-card-arriving');
            setTimeout(() => card.classList.remove('video-card-arriving'), 2400);
            return true;
        }
        await new Promise(resolve => setTimeout(resolve, 120));
    }
    return false;
}

function renderVideoCard(video, quizzes, goals) {
    const activeQuiz = quizzes && (
        quizzes.find(q => String(q.video_id) === String(video.id) && Number(q.importance_level) === Number(video.importance_rating)) ||
        quizzes.find(q => String(q.video_id) === String(video.id))
    );
    const srsStage = activeQuiz ? activeQuiz.srs_stage : 0;
    const isPaused = video.is_paused ? true : false;
    
    const username = typeof activeUsername !== 'undefined' ? activeUsername : 'default';
    const savedProgress = activeQuiz ? localStorage.getItem(`quiz-progress-${username}-${activeQuiz.id}`) : null;
    const isContinued = activeQuiz && ((activeQuiz.in_progress_index !== undefined && activeQuiz.in_progress_index !== null && activeQuiz.in_progress_index > 0) || (savedProgress && parseInt(savedProgress, 10) > 0));
    const studyLabel = isContinued ? 'Continue Quiz' : 'Study';
    
    let starsHTML = '';
    for (let i = 1; i <= 5; i++) {
        const starClass = i <= video.importance_rating ? 'fill-amber-500 text-amber-500' : 'text-stone-300';
        starsHTML += `
            <button onclick="changeVideoRating(event, ${video.id}, ${i})" class="focus:outline-none transition hover:scale-120 px-0.5" title="Set quiz to Level ${i}">
                <i data-lucide="star" class="w-4 h-4 ${starClass}"></i>
            </button>
        `;
    }
    
    let actionControlsHTML = '';
    if (video.is_temporary === 1 || video.is_temporary === true) {
        actionControlsHTML = `
            <button onclick="confirmPreviewImport(${video.id}, this)" class="btn-primary w-full py-2 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 h-[38px]">
                 <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i>
                 <span>Import to Goal</span>
            </button>
        `;
    } else if (video.status === 'processing') {
        actionControlsHTML = `
            <div class="w-full py-2 bg-amber-100 border border-amber-300 text-amber-900 font-bold rounded-xl text-xs flex items-center justify-center space-x-2 h-[38px]">
                <div class="animate-spin rounded-full h-4 w-4 border-2 border-amber-600 border-t-transparent"></div>
                <span>Importing...</span>
            </div>
        `;
    } else if (video.status === 'failed') {
        actionControlsHTML = `
            <button onclick="retryVideoImport(${video.id})" class="w-full py-2 bg-red-50 hover:bg-red-100 border border-red-200 text-red-600 font-bold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 h-[38px]" title="Retry Video Import: ${video.status_error || 'Import Failed'}">
                 <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
                 <span>Retry</span>
            </button>
        `;
    } else {
        const levelToUse = video.importance_rating || video.importance_level || 3;
        actionControlsHTML = `
            <button onclick="handleStudyButtonClick(event, ${video.id}, ${levelToUse})" class="btn-primary w-full py-2 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 h-[38px]">
                 <i data-lucide="${isContinued ? 'play-circle' : 'brain'}" class="w-3.5 h-3.5"></i>
                 <span>${studyLabel}</span>
            </button>
        `;
    }

    const titleHTML = `<a href="javascript:void(0)" onclick="openStudyStudio(${video.id})" class="block font-bold text-sm text-stone-900 truncate hover:text-amber-700 transition" title="Open in Study Studio: ${escapeHtml(video.title)}">${escapeHtml(video.title)}</a>`;
    
    const stageBadgeHTML = (video.is_temporary === 1 || video.is_temporary === true)
        ? `<span class="text-[9px] bg-amber-500/15 border border-amber-500/30 text-amber-900 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider flex items-center space-x-1" title="Preview mode: expires in ~24h unless imported"><i data-lucide="clock" class="w-3 h-3 text-amber-700"></i><span>24h Preview</span></span>`
        : (isPaused
            ? `<span class="text-[9px] bg-stone-100 border border-stone-200 text-stone-600 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider flex items-center space-x-1" title="SRS Review Intervals Paused"><i data-lucide="pause-circle" class="w-3 h-3 text-stone-500"></i><span>Stage ${srsStage} (Paused)</span></span>`
            : `<span class="text-[9px] bg-amber-100 border border-amber-200 text-amber-800 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">Stage ${srsStage}</span>`);

    
    const isWatchlist = video.is_watchlist === 1 || video.is_watchlist === true;

    const failedNoticeHTML = video.status === 'failed' ? `
        <div class="p-2.5 bg-red-50 border border-red-100 rounded-xl flex items-start space-x-2 text-xs text-red-700" title="${video.status_error || 'Unknown Error'}">
            <i data-lucide="alert-triangle" class="w-4 h-4 shrink-0 text-red-500 mt-0.5"></i>
            <div class="min-w-0 flex-1">
                <p class="font-semibold text-red-800 text-xs">Import Failed</p>
                <p class="text-[11px] text-red-600/90 break-words whitespace-normal leading-tight mt-0.5">${video.status_error || 'Unknown error occurred during processing.'}</p>
            </div>
        </div>
    ` : '';

    const validSummaryBullets = Array.isArray(video.summary) ? video.summary.filter(isRealSummaryBullet) : [];

    const isTemp = video.is_temporary === 1 || video.is_temporary === true;
    const hasTakeaways = validSummaryBullets.length > 0;
    const hasNotes = typeof video.custom_notes === 'string' && video.custom_notes.trim().length > 0;
    const hasDetails = !isTemp && (hasTakeaways || hasNotes);
    
    const detailsSectionHTML = hasDetails ? `
        <div class="pt-2 space-y-2">
            <button onclick="toggleVideoDetails(event, ${video.id})" class="flex items-center space-x-1.5 text-xs font-bold text-stone-500 hover:text-stone-700 transition">
                <i data-lucide="align-left" class="w-3.5 h-3.5 text-amber-600"></i>
                <span>${hasTakeaways && hasNotes ? 'AI Takeaways & Personal Notes' : (hasTakeaways ? 'AI Takeaways' : 'Personal Notes')}</span>
                <i data-lucide="chevron-down" id="details-chevron-${video.id}" class="w-3.5 h-3.5 text-stone-400 transition-transform"></i>
            </button>
            
            <div id="details-content-${video.id}" class="hidden space-y-3 pt-1 text-xs">
                ${hasTakeaways ? `
                <div class="space-y-1.5">
                    <h5 class="font-semibold text-stone-400 text-[10px] uppercase tracking-wider">Key Takeaways</h5>
                    <ul class="list-disc list-inside space-y-1 text-stone-600 pl-1 leading-relaxed">
                        ${validSummaryBullets.map(s => `<li>${s}</li>`).join('')}
                    </ul>
                </div>
                ` : ''}
                
                ${hasNotes ? `
                <div class="pt-2 space-y-1">
                    <h5 class="font-semibold text-stone-400 text-[10px] uppercase tracking-wider">My Notes</h5>
                    <div class="bg-stone-50 border border-stone-200 p-2.5 rounded-xl text-stone-700 leading-relaxed break-words prose prose-sm prose-stone max-w-none">
                        ${renderMarkdownSafe(video.custom_notes)}
                    </div>
                </div>
                ` : ''}
            </div>
        </div>
    ` : '';

    const mediaPreviewHTML = renderMediaThumbHTML(video, {
        sizeClasses: 'w-16 h-10',
        onClick: `openStudyStudio(${video.id})`,
        title: 'Open Study Studio Workspace'
    });

    return `
        <div id="video-card-${video.id}" class="bg-white border border-[#e7dfd3] rounded-2xl p-4 flex flex-col justify-between space-y-4 shadow-sm relative">
            <div class="flex space-x-3 items-start">
                ${mediaPreviewHTML}
                <div class="min-w-0 flex-grow">
                    ${titleHTML}
                    <div class="flex items-center space-x-1.5 mt-1.5 flex-wrap gap-y-1">
                        <div class="flex">${starsHTML}</div>
                        ${stageBadgeHTML}
                    </div>
                </div>
            </div>
            
            ${failedNoticeHTML ? `<div class="pt-2">${failedNoticeHTML}</div>` : ''}
            ${detailsSectionHTML}
            
            
            <div class="flex items-center justify-between pt-1 gap-2">
                <div id="action-btn-container-${video.id}" class="flex-grow min-w-0">
                    ${actionControlsHTML}
                </div>
                <div class="flex items-center space-x-2 shrink-0">
                    <button onclick="event.stopPropagation(); openStudyStudio(${video.id})" class="p-2 bg-stone-100 hover:bg-stone-200 text-stone-600 hover:text-stone-900 rounded-xl border border-stone-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Open Study Studio">
                        <i data-lucide="book-open" class="w-4 h-4"></i>
                    </button>
                    ${isWatchlist ? `
                        <button onclick="event.stopPropagation(); toggleWatchlist(${video.id})" class="p-2 bg-amber-50 hover:bg-amber-100 text-amber-600 hover:text-amber-700 rounded-xl border border-amber-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Remove from Study Queue">
                            <i data-lucide="bookmark" class="w-4 h-4 fill-amber-500 text-amber-500"></i>
                        </button>
                    ` : ''}
                    ${isTemp ? `
                        <button onclick="event.stopPropagation(); discardPreviewVideo(${video.id})" class="p-2 bg-stone-100 hover:bg-red-100 text-stone-500 hover:text-red-700 rounded-xl border border-stone-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Discard Preview">
                            <i data-lucide="x" class="w-4 h-4"></i>
                        </button>
                    ` : `
                        <button onclick="toggleVideoMenu(event, ${video.id})" data-menuid="${video.id}" class="p-2 bg-stone-100 hover:bg-stone-200 text-stone-600 hover:text-stone-900 rounded-xl border border-stone-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Material Options">
                            <i data-lucide="more-vertical" class="w-4 h-4"></i>
                        </button>
                    `}
                </div>
            </div>
        </div>
    `;
}

function toggleVideoDetails(event, id) {
    if (event) event.stopPropagation();
    const el = document.getElementById(`details-content-${id}`);
    const chevron = document.getElementById(`details-chevron-${id}`);
    if (!el) return;
    if (el.classList.contains('hidden')) {
        el.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
    } else {
        el.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
    }
}

function closeVideoMenu() {
    const portal = document.getElementById('video-context-menu-portal');
    if (portal) portal.remove();
}

function toggleVideoMenu(event, id) {
    if (event) event.stopPropagation();
    
    const existingPortal = document.getElementById('video-context-menu-portal');
    if (existingPortal) {
        if (existingPortal.dataset.forId === String(id)) {
            existingPortal.remove();
            return;
        }
        existingPortal.remove();
    }
    
    const btn = event ? event.currentTarget : document.querySelector(`[data-menuid="${id}"]`);
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    
    const cardData = window._videoCardCache && window._videoCardCache[id];
    const isPaused = cardData ? cardData.is_paused : false;
    const isWatchlist = cardData ? cardData.is_watchlist : false;
    const isArchived = cardData ? cardData.is_archived : false;
    const isImported = !cardData || (cardData.status !== 'processing' && cardData.status !== 'failed');
    // Material imported before topic extraction existed has an empty concept_pool, and its
    // overlay would have nothing to show, so the entry is hidden rather than opening empty.
    const hasConceptPool = !!(cardData && cardData.has_concept_pool);

    const portal = document.createElement('div');
    portal.id = 'video-context-menu-portal';
    portal.dataset.forId = String(id);
    portal.className = 'fixed w-56 rounded-xl bg-white border border-[#e7dfd3] shadow-2xl z-[9999] overflow-hidden';
    portal.innerHTML = `<div class="py-1">
        ${isImported && hasConceptPool ? `
        <button data-focus-video="${id}" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="target" class="w-4 h-4 text-amber-600"></i><span>Adjust Learning Focus</span>
        </button>
        ` : ''}
        ${isImported ? `
        <button onclick="closeVideoMenu(); showFactCheck(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="shield-alert" class="w-4 h-4 text-amber-500"></i><span>Verify Accuracy</span>
        </button>
        ` : ''}
        <button onclick="closeVideoMenu(); openVideoStatsModal(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="bar-chart-2" class="w-4 h-4 text-amber-600"></i><span>View Material Analytics</span>
        </button>
        <button onclick="closeVideoMenu(); pauseVideo(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="${isPaused ? 'play' : 'pause'}" class="w-4 h-4 text-amber-600"></i><span>${isPaused ? 'Resume intervals' : 'Pause intervals'}</span>
        </button>
        ${!isWatchlist ? `
        <button onclick="closeVideoMenu(); toggleWatchlist(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="bookmark" class="w-4 h-4 text-stone-400"></i><span>Queue to Watchlist</span>
        </button>
        ` : ''}
        <button onclick="closeVideoMenu(); openEditVideoModal(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="repeat" class="w-4 h-4 text-amber-600"></i><span>Swap Goal / Edit Details</span>
        </button>
        <button onclick="closeVideoMenu(); archiveVideo(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-stone-700 hover:bg-stone-50 hover:text-stone-900 transition">
            <i data-lucide="archive" class="w-4 h-4 text-amber-600"></i><span>${isArchived ? 'Send to Active' : 'Archive Video'}</span>
        </button>
        <div class="border-t border-[#e7dfd3] my-1"></div>
        <button onclick="closeVideoMenu(); deleteVideo(${id})" class="flex items-center space-x-2.5 w-full text-left px-4 py-2.5 text-xs text-rose-600 hover:bg-rose-50 hover:text-rose-700 transition">
            <i data-lucide="trash-2" class="w-4 h-4 text-rose-500"></i><span>Permanently Delete</span>
        </button>
    </div>`;
    
    document.body.appendChild(portal);

    const focusBtn = portal.querySelector('[data-focus-video]');
    if (focusBtn) {
        focusBtn.addEventListener('click', () => {
            closeVideoMenu();
            openFocusModal(id);
        });
    }

    renderIcons();

    // Measured rather than assumed. This was a hardcoded 250px, which silently stopped
    // matching the moment the menu gained or lost an entry, flipping it to the wrong side
    // of the button near a viewport edge.
    const menuH = portal.offsetHeight || 250;
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    if (spaceBelow >= menuH || spaceBelow >= spaceAbove) {
        portal.style.top = `${rect.bottom + 6}px`;
    } else {
        portal.style.top = `${rect.top - menuH - 6}px`;
    }
    const rightEdge = rect.right;
    portal.style.right = `${window.innerWidth - rightEdge}px`;
}

// Global window event listener to remove context menus on outside click / scroll
window.addEventListener('click', (e) => {
    const portal = document.getElementById('video-context-menu-portal');
    if (portal && !portal.contains(e.target)) portal.remove();
});

window.addEventListener('scroll', () => {
    const portal = document.getElementById('video-context-menu-portal');
    if (portal) portal.remove();
}, true);

async function pauseVideo(id) {
    await fetchAPI(`/api/videos/${id}/pause`, { method: 'POST' });
    if (typeof loadDashboard === 'function') loadDashboard();
    if (typeof loadGoals === 'function') loadGoals();
}

async function discardPreviewVideo(id) {
    const cardData = (window._videoCardCache && window._videoCardCache[id]) || null;
    const hasNotes = Boolean(cardData && cardData.custom_notes && cardData.custom_notes.trim().length > 0);

    let promptMessage = "Are you sure you want to discard this draft preview material?";
    if (hasNotes) {
        promptMessage = "Warning: Discarding this draft preview will permanently delete all your notes taken for this video. Are you sure you want to discard it?";
    }

    const confirmFn = window.showConfirm || (typeof showConfirm === 'function' ? showConfirm : null);
    let confirmed = false;
    if (confirmFn) {
        confirmed = await confirmFn({
            title: "Discard Draft Preview?",
            message: promptMessage,
            confirmText: "Discard Draft",
            confirmClass: "bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-xs shadow-sm transition",
            icon: "trash-2"
        });
    } else {
        confirmed = confirm(promptMessage);
    }

    if (confirmed) {
        try {
            await fetchAPI(`/api/videos/${id}`, { method: 'DELETE' });

            // Also dismiss the matching recommendation so it doesn't just reappear
            // as "Add to Queue" on the home page the moment this preview is gone.
            if (cardData && cardData.youtube_id) {
                try {
                    const dismissForm = new FormData();
                    dismissForm.append('youtube_id', cardData.youtube_id);
                    await fetchAPI('/api/daily-recommendations/dismiss', { method: 'POST', body: dismissForm });
                } catch (dismissErr) {
                    console.error("Dismiss matching recommendation error:", dismissErr);
                }
            }

            if (typeof showToast === 'function') {
                showToast("Draft preview discarded", "saved", 2000);
            }
            if (typeof loadDashboard === 'function') loadDashboard();
            if (typeof loadGoals === 'function') loadGoals();
        } catch (e) {
            console.error("Discard preview error:", e);
            if (typeof showToast === 'function') showToast("Failed to discard draft: " + e.message, "failed");
        }
    }
}

async function archiveVideo(id) {
    await fetchAPI(`/api/videos/${id}/archive`, { method: 'POST' });
    if (typeof loadDashboard === 'function') loadDashboard();
    if (typeof loadGoals === 'function') loadGoals();
}

async function deleteVideo(id) {
    const confirmFn = window.showConfirm || (typeof showConfirm === 'function' ? showConfirm : null);
    let confirmed = false;
    if (confirmFn) {
        confirmed = await confirmFn({
            title: "Delete Material?",
            message: "Are you sure you want to permanently delete this video? All historical quiz data will be deleted.",
            confirmText: "Delete Material",
            confirmClass: "bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-xs shadow-sm transition",
            icon: "trash-2"
        });
    } else {
        confirmed = confirm("Are you sure you want to permanently delete this video? All historical quiz data will be deleted.");
    }
    if (confirmed) {
        await fetchAPI(`/api/videos/${id}`, { method: 'DELETE' });
        if (typeof showToast === 'function') {
            showToast("Material deleted", "saved", 2000);
        }
        if (typeof loadDashboard === 'function') loadDashboard();
        if (typeof loadGoals === 'function') loadGoals();
    }
}

async function toggleWatchlist(id) {
    await fetchAPI(`/api/videos/${id}/watchlist`, { method: 'POST' });
    if (typeof loadDashboard === 'function') loadDashboard();
    if (typeof loadGoals === 'function') loadGoals();
}

async function retryVideoImport(id) {
    const actionBtnContainer = document.getElementById(`action-btn-container-${id}`);
    if (actionBtnContainer) {
        actionBtnContainer.innerHTML = `
            <div class="w-full py-2 bg-amber-100 border border-amber-300 text-amber-900 font-bold rounded-xl text-xs flex items-center justify-center space-x-2 h-[38px] opacity-90">
                <div class="animate-spin rounded-full h-4 w-4 border-2 border-amber-600 border-t-transparent"></div>
                <span>Importing...</span>
            </div>
        `;
    }
    
    try {
        await fetchAPI(`/api/videos/${id}/retry`, { method: 'POST' });
        if (window.globalImportBacklog) window.globalImportBacklog.poll();
        if (typeof loadDashboard === 'function') loadDashboard();
        if (typeof loadGoals === 'function') loadGoals();
    } catch (e) {
        if (typeof showToast === 'function') {
            showToast("Retry failed: " + (e.detail || e.message || e), "failed");
        } else {
            alert("Retry failed: " + (e.detail || e.message || e));
        }
        if (window.globalImportBacklog) window.globalImportBacklog.poll();
        if (typeof loadDashboard === 'function') loadDashboard();
        if (typeof loadGoals === 'function') loadGoals();
    }
}

async function changeVideoRating(event, id, rating) {
    if (event) event.stopPropagation();
    
    // 1. Instant optimistic DOM update for star icons on video card
    const cardEl = document.getElementById(`video-card-${id}`);
    if (cardEl) {
        const starBtns = cardEl.querySelectorAll('button[onclick*="changeVideoRating"]');
        starBtns.forEach((btn, index) => {
            const starNum = index + 1;
            const icon = btn.querySelector('[data-lucide="star"], svg, i');
            if (icon) {
                if (starNum <= rating) {
                    icon.setAttribute('class', 'w-4 h-4 fill-amber-500 text-amber-500');
                } else {
                    icon.setAttribute('class', 'w-4 h-4 text-stone-300');
                }
            }
        });
    }

    if (window._videoCardCache && window._videoCardCache[id]) {
        window._videoCardCache[id].importance_rating = rating;
    }

    // 2. Silent background API sync. Tracked on window._pendingRatingSync so a Study
    // click on this video (see startQuiz in quiz.js) can await it instead of racing
    // it, that race was the cause of a stale question count on the first quiz open
    // right after a rating change.
    const cardData = window._videoCardCache?.[id];
    const formData = new FormData();
    formData.append('importance_rating', rating);
    if (cardData && cardData.title) formData.append('title', cardData.title);

    window._pendingRatingSync = window._pendingRatingSync || {};
    const syncPromise = (async () => {
        try {
            await fetchAPI(`/api/videos/${id}/edit`, { method: 'POST', body: formData });
            const genData = new FormData();
            genData.append('level', rating);
            await fetchAPI(`/api/videos/${id}/generate_quiz`, { method: 'POST', body: genData });
            if (typeof showToast === 'function') showToast("Star rating updated", "saved", 2000);
            if (typeof loadDashboard === 'function') loadDashboard();
        } catch (e) {
            console.error("Failed to update rating:", e);
            if (typeof showToast === 'function') showToast("Failed to update star rating", "failed");
            if (typeof loadDashboard === 'function') loadDashboard();
        } finally {
            if (window._pendingRatingSync[id] === syncPromise) delete window._pendingRatingSync[id];
        }
    })();
    window._pendingRatingSync[id] = syncPromise;
    await syncPromise;
}

async function showFactCheck(id) {
    showLoader("Verifying Factual Accuracy", "Gemini is analyzing the transcript against scientific and historical consensus...");
    try {
        const data = await fetchAPI(`/api/videos/${id}/factcheck`);
        const overlay = document.getElementById('overlay-factcheck');
        if (overlay) overlay.classList.remove('hidden');
        
        const claimsContainer = document.getElementById('factcheck-claims-container');
        if (claimsContainer) {
            claimsContainer.innerHTML = '';
            const disputed = data.disputed_claims || [];
            const verified = data.verified_claims || [];

            if (disputed.length === 0 && verified.length === 0) {
                claimsContainer.innerHTML = `
                    <div class="text-center py-8 text-stone-500 bg-stone-50 border border-dashed border-stone-200 rounded-2xl">
                        <i data-lucide="shield-check" class="w-8 h-8 text-emerald-500 mx-auto mb-2"></i>
                        <p class="text-sm font-semibold text-stone-700">No Specific Claims Flagged</p>
                        <p class="text-xs text-stone-400 mt-1 max-w-sm mx-auto">No distinct factual contradictions or verified key claims were extracted for this content.</p>
                    </div>
                `;
            } else {
                disputed.forEach(claim => {
                    const isMajor = (claim.severity || '').toLowerCase().includes('falsehood') || (claim.severity || '').toLowerCase().includes('major');
                    const badgeColor = isMajor
                        ? 'bg-rose-500/10 text-rose-600 border border-rose-500/20'
                        : 'bg-amber-500/10 text-amber-700 border border-amber-500/20';
                    const badgeLabel = claim.severity || 'Disputed';
                    const citationHtml = claim.source_citation ? `
                        <div class="space-y-0.5 border-t border-stone-200/60 pt-2">
                            <span class="text-[10px] font-bold text-stone-400 uppercase tracking-wider block">Source:</span>
                            <p class="text-[11px] text-stone-500 leading-relaxed">${claim.source_citation}</p>
                        </div>
                    ` : '';

                    claimsContainer.innerHTML += `
                        <div class="p-4 bg-stone-50 border border-stone-200 rounded-2xl space-y-3 shadow-sm">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-bold ${badgeColor} px-2.5 py-0.5 rounded-full uppercase tracking-wider">${badgeLabel}</span>
                            </div>
                            <div class="space-y-1">
                                <span class="text-[10px] font-bold text-stone-500 uppercase tracking-wider block">Claim made in video:</span>
                                <p class="text-sm text-stone-900 leading-relaxed font-semibold">"${claim.claim}"</p>
                            </div>
                            <div class="space-y-1 border-t border-stone-200 pt-2.5">
                                <span class="text-[10px] font-bold text-amber-700 uppercase tracking-wider block">Accepted Factual Consensus:</span>
                                <p class="text-xs text-stone-600 leading-relaxed">${claim.actual_consensus}</p>
                            </div>
                            ${citationHtml}
                        </div>
                    `;
                });

                verified.forEach(claim => {
                    claimsContainer.innerHTML += `
                        <div class="p-4 bg-stone-50 border border-stone-200 rounded-2xl space-y-3 shadow-sm">
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-bold bg-emerald-500/10 text-emerald-700 border border-emerald-500/20 px-2.5 py-0.5 rounded-full uppercase tracking-wider">Verified</span>
                            </div>
                            <div class="space-y-1">
                                <span class="text-[10px] font-bold text-stone-500 uppercase tracking-wider block">Claim made in video:</span>
                                <p class="text-sm text-stone-900 leading-relaxed font-semibold">"${claim.claim}"</p>
                            </div>
                            <div class="space-y-1 border-t border-stone-200 pt-2.5">
                                <span class="text-[10px] font-bold text-emerald-700 uppercase tracking-wider block">Evidence:</span>
                                <p class="text-xs text-stone-600 leading-relaxed">${claim.evidence}</p>
                            </div>
                        </div>
                    `;
                });
            }
        }
        renderIcons();
    } catch (e) {
        console.error("Fact check failed:", e);
        if (typeof showToast === 'function') {
            showToast("Fact check failed: " + (e.detail || e.message || e), "failed");
        } else {
            alert("Fact check failed: " + (e.detail || e.message || e));
        }
    } finally {
        hideLoader();
    }
}

async function openEditVideoModal(id, category, goalId, rating, notes) {
    const cardData = window._videoCardCache && window._videoCardCache[id];
    const overlay = document.getElementById('overlay-edit-video');
    if (!overlay) return;
    
    const hiddenId = document.getElementById('edit-video-id');
    if (hiddenId) hiddenId.value = id;
    
    const titleEl = document.getElementById('edit-video-title');
    if (titleEl) titleEl.value = cardData ? (cardData.title || '') : '';
    
    const ratingEl = document.getElementById('edit-video-rating');
    if (ratingEl) ratingEl.value = cardData ? (cardData.importance_rating || rating || 3) : (rating || 3);
    
    const notesEl = document.getElementById('edit-video-notes');
    if (notesEl) notesEl.value = cardData ? (cardData.custom_notes || notes || '') : (notes || '');
    
    const goalSelect = document.getElementById('edit-video-goal-select') || document.getElementById('edit-video-goal');
    if (goalSelect) {
        let goalsList = window._goalsCache ? Object.values(window._goalsCache) : [];
        if (goalsList.length === 0) {
            try {
                const dash = await fetchAPI('/api/dashboard');
                if (dash && dash.goals) {
                    goalsList = dash.goals;
                }
            } catch (e) {
                console.error("Failed to load goals for dropdown:", e);
            }
        }
        
        let selectHTML = '<option value="0">-- Unassociated / Quick Review Material --</option>';
        goalsList.forEach(g => {
            selectHTML += `<option value="${g.id}">Goal: ${escapeHtml(g.title)}</option>`;
        });
        goalSelect.innerHTML = selectHTML;
        
        const activeGoalId = (cardData && cardData.learning_goal_id) ? String(cardData.learning_goal_id) : (goalId ? String(goalId) : "0");
        goalSelect.value = activeGoalId;
    }
    
    overlay.classList.remove('hidden');
}

function initEditVideoEvents() {
    const btnClose = document.getElementById('btn-close-edit-video');
    const form = document.getElementById('edit-video-form');
    
    if (btnClose) {
        btnClose.onclick = () => {
            document.getElementById('overlay-edit-video')?.classList.add('hidden');
        };
    }
    if (form) {
        form.onsubmit = async (e) => {
            e.preventDefault();
            const id = document.getElementById('edit-video-id')?.value;
            if (!id) return;
            
            const titleEl = document.getElementById('edit-video-title');
            const ratingEl = document.getElementById('edit-video-rating');
            const goalSelect = document.getElementById('edit-video-goal-select') || document.getElementById('edit-video-goal');
            const notesEl = document.getElementById('edit-video-notes');
            
            const formData = new FormData();
            if (titleEl) formData.append('title', titleEl.value);
            if (ratingEl) formData.append('importance_rating', ratingEl.value);
            if (goalSelect) formData.append('learning_goal_id', goalSelect.value);
            if (notesEl) formData.append('custom_notes', notesEl.value);
            
            try {
                await fetchAPI(`/api/videos/${id}/edit`, { method: 'POST', body: formData });
                document.getElementById('overlay-edit-video')?.classList.add('hidden');
                if (typeof loadDashboard === 'function') loadDashboard();
                if (typeof loadGoals === 'function') loadGoals();
            } catch (err) {
                console.error(err);
                alert("Failed to edit video: " + err.message);
            }
        };
    }
}

async function openVideoStatsModal(id) {
    const cardData = window._videoCardCache && window._videoCardCache[id];
    const overlay = document.getElementById('overlay-video-stats');
    if (!overlay) return;
    
    document.getElementById('stats-video-title').textContent = cardData ? cardData.title : `Material #${id}`;
    
    const stageEl = document.getElementById('stats-srs-stage');
    const reviewEl = document.getElementById('stats-next-review');
    const attemptsContainer = document.getElementById('stats-attempts-container');
    
    if (stageEl) stageEl.textContent = '...';
    if (reviewEl) reviewEl.textContent = '...';
    if (attemptsContainer) {
        attemptsContainer.innerHTML = `
            <div class="flex items-center justify-center py-8 text-stone-500 space-x-2">
                <div class="animate-spin rounded-full h-4 w-4 border-2 border-amber-600 border-t-transparent"></div>
                <span class="text-xs font-semibold">Loading stats...</span>
            </div>
        `;
    }
    
    overlay.classList.remove('hidden');
    
    try {
        const stats = await fetchAPI(`/api/videos/${id}/stats`);
        
        if (stats.title) {
            document.getElementById('stats-video-title').textContent = stats.title;
        }
        
        if (stageEl) {
            stageEl.textContent = `Stage ${stats.srs_stage ?? 0}`;
        }
        
        if (reviewEl) {
            if (!stats.next_review_at) {
                reviewEl.textContent = "Not scheduled";
                reviewEl.className = "text-xs font-semibold text-stone-500";
            } else {
                const dtStr = typeof parseDate === 'function' ? parseDate(stats.next_review_at) : stats.next_review_at;
                const dt = new Date(dtStr);
                const now = new Date();
                if (dt <= now) {
                    reviewEl.textContent = "Due now";
                    reviewEl.className = "text-xs font-bold text-amber-400";
                } else {
                    reviewEl.textContent = dt.toLocaleString(undefined, {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                    });
                    reviewEl.className = "text-xs font-semibold text-stone-500";
                }
            }
        }
        
        renderVideoStatsAttempts(attemptsContainer, stats.attempts || []);
    } catch (e) {
        console.error("Failed to fetch video stats:", e);
        if (attemptsContainer) {
            attemptsContainer.innerHTML = `<p class="text-xs text-red-400 text-center py-4">Failed to load statistics.</p>`;
        }
    }
}

function renderVideoStatsAttempts(container, attempts) {
    if (!container) return;
    if (!attempts || attempts.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8 bg-stone-50 rounded-2xl border border-dashed border-stone-200 space-y-2">
                <i data-lucide="history" class="w-8 h-8 text-stone-400 mx-auto"></i>
                <p class="text-xs font-semibold text-stone-500">No Quiz Attempts Yet</p>
                <p class="text-[10px] text-stone-500 max-w-xs mx-auto">Study this material to complete active recall practice and track your history here.</p>
            </div>
        `;
        if (typeof renderIcons === 'function') renderIcons();
        return;
    }
    
    // Group attempts into sessions by quiz_id and timestamp proximity (20 mins)
    const sessions = [];
    let currentSession = null;
    
    const sorted = [...attempts].sort((a, b) => {
        const dA = new Date(typeof parseDate === 'function' ? parseDate(a.created_at) : a.created_at);
        const dB = new Date(typeof parseDate === 'function' ? parseDate(b.created_at) : b.created_at);
        return dB - dA;
    });
    
    sorted.forEach(att => {
        const t = new Date(typeof parseDate === 'function' ? parseDate(att.created_at) : att.created_at);
        if (currentSession && 
            currentSession.quiz_id === att.quiz_id && 
            Math.abs(currentSession.lastTime - t) < 20 * 60 * 1000) {
            currentSession.attempts.push(att);
            currentSession.lastTime = t;
        } else {
            currentSession = {
                id: att.id,
                quiz_id: att.quiz_id,
                srs_stage: att.srs_stage,
                lastTime: t,
                created_at: att.created_at,
                attempts: [att]
            };
            sessions.push(currentSession);
        }
    });
    
    container.innerHTML = '';
    
    sessions.forEach((session, idx) => {
        const dtStr = typeof parseDate === 'function' ? parseDate(session.created_at) : session.created_at;
        const dateObj = new Date(dtStr);
        const dateStr = dateObj.toLocaleString(undefined, {
            month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        const passes = session.attempts.filter(a => a.grade === 'remembered').length;
        const total = session.attempts.length;
        const scorePct = Math.round((passes / total) * 100);
        const scoreClass = scorePct >= 80 ? 'text-emerald-400' : (scorePct >= 50 ? 'text-amber-400' : 'text-red-400');
        
        const isExpanded = idx === 0 || (window._expandedVideoStatSessions && window._expandedVideoStatSessions[session.id]);
        
        let qItemsHTML = '';
        const sessionAttempts = [...session.attempts].sort((a, b) => (a.question_index ?? 0) - (b.question_index ?? 0));
        
        sessionAttempts.forEach(att => {
            const isPass = att.grade === 'remembered';
            const gradeBadge = isPass
                ? `<span class="text-[9px] font-bold px-2 py-0.5 rounded border border-emerald-500/20 bg-emerald-500/10 text-emerald-400 uppercase tracking-wider">Pass (+10 XP)</span>`
                : `<span class="text-[9px] font-bold px-2 py-0.5 rounded border border-red-500/20 bg-red-500/10 text-red-400 uppercase tracking-wider">Fail (+3 XP)</span>`;
                
            qItemsHTML += `
                <div class="p-3 bg-stone-50 border border-stone-200 rounded-xl space-y-2 text-xs">
                    <div class="flex justify-between items-center">
                        <span class="text-[10px] font-bold text-stone-500 uppercase tracking-wider">Question ${(att.question_index ?? 0) + 1}</span>
                        ${gradeBadge}
                    </div>
                    <p class="text-xs text-stone-900 font-semibold leading-relaxed">${att.question || ''}</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] pt-1">
                        <div>
                            <span class="text-stone-500 block text-[9px] uppercase font-bold tracking-wider mb-0.5">Your Answer:</span>
                            <div class="text-stone-500 font-mono bg-stone-50 p-2 rounded-lg border border-stone-200 break-words whitespace-pre-wrap">${att.given_answer || '<span class="text-stone-400 italic">No answer recorded</span>'}</div>
                        </div>
                        <div>
                            <span class="text-emerald-500 block text-[9px] uppercase font-bold tracking-wider mb-0.5">Correct Answer:</span>
                            <div class="text-emerald-400 font-mono bg-stone-50 p-2 rounded-lg border border-stone-200 break-words whitespace-pre-wrap">${att.correct_answer || ''}</div>
                        </div>
                    </div>
                    ${att.explanation ? `
                        <div class="text-[11px] text-stone-500 bg-stone-50 p-2 rounded-lg border border-stone-200">
                            <span class="font-bold text-amber-700">Explanation:</span> ${att.explanation}
                        </div>
                    ` : ''}
                </div>
            `;
        });
        
        container.innerHTML += `
            <div class="bg-stone-50 border border-stone-200 rounded-xl overflow-hidden shadow-sm">
                <button type="button" onclick="toggleVideoStatSession(${session.id})" class="w-full p-3 flex justify-between items-center text-left hover:bg-stone-100 transition focus:outline-none">
                    <div class="min-w-0 flex-grow pr-2 space-y-1">
                        <div class="flex items-center space-x-2">
                            <span class="text-[9px] bg-amber-100 border border-amber-200 text-amber-800 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">Stage ${session.srs_stage ?? 0}</span>
                            <span class="text-[10px] text-stone-500 font-medium">${dateStr}</span>
                        </div>
                    </div>
                    <div class="flex items-center space-x-2.5 shrink-0">
                        <span class="text-xs font-extrabold ${scoreClass}">${scorePct}% (${passes}/${total})</span>
                        <i data-lucide="chevron-down" id="vstat-chevron-${session.id}" class="w-4 h-4 text-stone-400 transition-transform ${isExpanded ? 'rotate-180' : ''}"></i>
                    </div>
                </button>
                <div id="vstat-session-${session.id}" class="${isExpanded ? '' : 'hidden'} p-3 bg-stone-50 border-t border-stone-200 space-y-2">
                    ${qItemsHTML}
                </div>
            </div>
        `;
    });
    
    if (typeof renderIcons === 'function') renderIcons();
}

function toggleVideoStatSession(sessionId) {
    if (!window._expandedVideoStatSessions) window._expandedVideoStatSessions = {};
    const details = document.getElementById(`vstat-session-${sessionId}`);
    const chevron = document.getElementById(`vstat-chevron-${sessionId}`);
    if (!details) return;
    if (details.classList.contains('hidden')) {
        details.classList.remove('hidden');
        if (chevron) chevron.classList.add('rotate-180');
        window._expandedVideoStatSessions[sessionId] = true;
    } else {
        details.classList.add('hidden');
        if (chevron) chevron.classList.remove('rotate-180');
        window._expandedVideoStatSessions[sessionId] = false;
    }
}

function closeVideoStatsModal() {
    const overlay = document.getElementById('overlay-video-stats');
    if (overlay) overlay.classList.add('hidden');
}

function closeFactCheckModal() {
    const overlay = document.getElementById('overlay-factcheck');
    if (overlay) overlay.classList.add('hidden');
}

function initFactCheckEvents() {
    const btnClose = document.getElementById('btn-close-factcheck');
    if (btnClose) {
        btnClose.addEventListener('click', closeFactCheckModal);
    }
}

// --- Study Studio Module ---
let _currentStudioVideoId = null;
let _studioNotesSaveTimeout = null;

let _currentStudioPlayer = null;
let _studioPositionSaveInterval = null;
let _currentStudioVideoCurrentTime = 0;

let _studioIsPlaying = true;
let _isYTAPILoading = false;
let _ytReadyCallbacks = [];

function ensureYouTubeAPI(callback) {
    if (window.YT && window.YT.Player) {
        if (callback) callback();
        return;
    }
    if (callback) _ytReadyCallbacks.push(callback);

    if (!_isYTAPILoading) {
        _isYTAPILoading = true;
        const prevOnReady = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => {
            if (typeof prevOnReady === 'function') {
                try { prevOnReady(); } catch (e) {}
            }
            while (_ytReadyCallbacks.length > 0) {
                const cb = _ytReadyCallbacks.shift();
                try { cb(); } catch (e) {}
            }
        };
        if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
            const tag = document.createElement('script');
            tag.src = "https://www.youtube.com/iframe_api";
            const firstScriptTag = document.getElementsByTagName('script')[0];
            if (firstScriptTag && firstScriptTag.parentNode) {
                firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);
            }
        }
    }
}

function callStudioPlayer(func, ...args) {
    const iframe = document.getElementById('studio-yt-iframe');
    if (iframe && iframe.contentWindow) {
        try {
            iframe.contentWindow.postMessage(JSON.stringify({
                event: 'command',
                func: func,
                args: args
            }), '*');
        } catch (e) {}
    }
    if (_currentStudioPlayer && typeof _currentStudioPlayer[func] === 'function') {
        try {
            _currentStudioPlayer[func](...args);
        } catch (e) {}
    }
}

function initStudioYTPlayerTracker() {
    if (_studioPositionSaveInterval) clearInterval(_studioPositionSaveInterval);
    _currentStudioPlayer = null;
    _studioIsPlaying = true;

    const setupYTPlayer = () => {
        try {
            const iframe = document.getElementById('studio-yt-iframe');
            if (!iframe) return;
            _currentStudioPlayer = new YT.Player('studio-yt-iframe', {
                events: {
                    'onStateChange': (event) => {
                        if (event && (event.data === 2 || event.data === 0)) { // PAUSED or ENDED
                            _studioIsPlaying = false;
                            updateStudioPlayIcons(false);
                            saveStudioVideoPosition();
                        }
                        if (event && event.data === 1) { // PLAYING
                            _studioIsPlaying = true;
                            updateStudioPlayIcons(true);
                        }
                    }
                }
            });
        } catch (e) {}
    };

    ensureYouTubeAPI(setupYTPlayer);

    _studioPositionSaveInterval = setInterval(() => {
        saveStudioVideoPosition();
    }, 5000);
}

async function openStudyStudio(id) {
    _currentStudioVideoId = id;
    _currentStudioVideoCurrentTime = 0;
    const cardData = (window._videoCardCache && window._videoCardCache[id]) || null;
    
    const overlay = document.getElementById('overlay-study-studio');
    if (!overlay) return;
    
    const titleEl = document.getElementById('studio-video-title');
    if (titleEl) titleEl.textContent = cardData ? cardData.title : `Material #${id}`;

    const editor = document.getElementById('studio-notes-editor');
    if (editor) {
        editor.innerHTML = renderMarkdownSafe(cardData ? (cardData.custom_notes || '') : '');
        editor.oninput = () => {
            if (_studioNotesSaveTimeout) clearTimeout(_studioNotesSaveTimeout);
            _studioNotesSaveTimeout = setTimeout(() => {
                saveStudioNotes();
            }, 1000);
        };
        if (!editor._studioEditorEventsBound) {
            editor.addEventListener('click', handleStudioTimestampChipClick);
            // Focusing this field is what pulls up the on-screen keyboard, which
            // covers roughly half the screen on mobile - removing the video pane
            // entirely (studio-keyboard-mode, see style.css) gives notes the room
            // the keyboard would otherwise eat into. Driven off actual focus
            // rather than a visualViewport size heuristic, which mobile browsers
            // fire inconsistently.
            editor.addEventListener('focus', () => {
                if (window.innerWidth >= 640) return;
                const overlay = document.getElementById('overlay-study-studio');
                const modal = overlay ? overlay.querySelector('.studio-resizable-modal') : null;
                if (modal) modal.classList.add('studio-keyboard-mode');
            });
            editor.addEventListener('blur', () => {
                const overlay = document.getElementById('overlay-study-studio');
                const modal = overlay ? overlay.querySelector('.studio-resizable-modal') : null;
                if (modal) modal.classList.remove('studio-keyboard-mode');
            });
            editor._studioEditorEventsBound = true;
        }
    }

    const ytWrapper = document.getElementById('studio-yt-wrapper');
    const videoControls = document.getElementById('studio-video-controls');
    const pdfWrapper = document.getElementById('studio-pdf-wrapper');
    const docWrapper = document.getElementById('studio-doc-wrapper');
    const pdfViewer = document.getElementById('studio-pdf-viewer');
    const docContent = document.getElementById('studio-doc-content');
    const pdfDownloadBtn = document.getElementById('studio-pdf-download-btn');
    const pdfOpenBtn = document.getElementById('studio-pdf-open-btn');
    const pdfTitle = document.getElementById('studio-pdf-title');
    const docDownloadBtn = document.getElementById('studio-doc-download-btn');
    const docHeaderTitle = document.getElementById('studio-doc-header-title');

    if (ytWrapper) ytWrapper.classList.add('hidden');
    if (videoControls) videoControls.classList.add('hidden');
    if (pdfWrapper) pdfWrapper.classList.add('hidden');
    if (docWrapper) docWrapper.classList.add('hidden');
    if (docDownloadBtn) docDownloadBtn.classList.add('hidden');

    if (cardData && cardData.youtube_id) {
        const startSec = Math.floor(parseFloat(cardData.last_position_seconds) || 0);
        if (docHeaderTitle) docHeaderTitle.textContent = "Video Key Takeaways";
        if (ytWrapper) {
            ytWrapper.classList.remove('hidden');
            ytWrapper.innerHTML = `<iframe id="studio-yt-iframe" class="w-full aspect-video" src="https://www.youtube.com/embed/${cardData.youtube_id}?enablejsapi=1&autoplay=1&start=${startSec}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
        }
        if (videoControls) videoControls.classList.remove('hidden');
        _studioCaptionsOn = false;
        [document.getElementById('mini-btn-captions'), document.getElementById('studio-btn-captions')].forEach(btn => {
            if (btn) btn.classList.remove('bg-amber-100', 'text-amber-700');
        });
        initStudioYTPlayerTracker();

        if (docWrapper) {
            docWrapper.classList.remove('hidden');
            if (docContent) {
                const validStudioBullets = Array.isArray(cardData.summary) ? cardData.summary.filter(isRealSummaryBullet) : [];
                docContent.innerHTML = (validStudioBullets.length > 0)
                    ? `<ul class="list-disc list-inside space-y-1.5">${validStudioBullets.map(s => `<li>${s}</li>`).join('')}</ul>`
                    : '<p class="text-stone-500 italic">No video takeaways recorded.</p>';
            }
        }
    } else if (cardData && cardData.title && cardData.title.toLowerCase().endsWith('.pdf')) {
        if (pdfWrapper) {
            pdfWrapper.classList.remove('hidden');
            if (pdfTitle) pdfTitle.textContent = cardData.title;
            // Iframe is hidden below the sm breakpoint (see markup), but setting .src still
            // triggers a background fetch even while hidden , skip it on mobile so phones
            // aren't silently downloading the PDF just to throw the render away.
            if (pdfViewer && window.innerWidth >= 640) pdfViewer.src = `/api/videos/${id}/pdf`;
            if (pdfOpenBtn) pdfOpenBtn.href = `/api/videos/${id}/pdf`;
            if (pdfDownloadBtn) pdfDownloadBtn.href = `/api/videos/${id}/document`;
        }
    } else {
        if (docHeaderTitle) docHeaderTitle.textContent = "Document Source Text";
        if (docWrapper) {
            docWrapper.classList.remove('hidden');
            if (docDownloadBtn) {
                docDownloadBtn.href = `/api/videos/${id}/document`;
                docDownloadBtn.classList.remove('hidden');
            }
            if (docContent) {
                const text = cardData && cardData.summary ? cardData.summary.join('\n\n') : '';
                docContent.innerHTML = text ? `<div class="whitespace-pre-line">${text}</div>` : '<p class="text-stone-500 italic">Document text content workspace.</p>';
            }
        }
    }
    
    overlay.classList.remove('hidden');
    initStudioResizer();
    if (typeof renderIcons === 'function') renderIcons();
}

function initStudioResizer() {
    const resizer = document.getElementById('studio-resizer');
    const leftPane = document.getElementById('studio-pane-left');
    const rightPane = document.getElementById('studio-pane-right');
    const workspace = document.getElementById('studio-workspace');
    if (!resizer || !leftPane || !rightPane || !workspace || resizer._resizerBound) return;
    resizer._resizerBound = true;

    let dragging = false;

    // Pointer events + setPointerCapture (not document-level mousemove/mouseup) because the
    // left pane holds the PDF/video iframe: once the cursor crosses into it while shrinking
    // that pane, a separate document swallows plain mouse events and the drag gets stuck.
    // Capturing the pointer on the handle keeps events routed here regardless of what's
    // under the cursor - same fix already used for the mini-player drag handle.
    resizer.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        dragging = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        resizer.setPointerCapture(e.pointerId);
    });
    resizer.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        const rect = workspace.getBoundingClientRect();
        let pct = ((e.clientX - rect.left) / rect.width) * 100;
        pct = Math.min(75, Math.max(25, pct));
        leftPane.style.width = pct + '%';
        rightPane.style.width = (100 - pct) + '%';
    });
    resizer.addEventListener('pointerup', () => {
        if (!dragging) return;
        dragging = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
}

async function saveStudioVideoPosition() {
    if (!_currentStudioVideoId) return;
    
    let pos = _currentStudioVideoCurrentTime;
    if (_currentStudioPlayer && typeof _currentStudioPlayer.getCurrentTime === 'function') {
        try {
            const playerTime = _currentStudioPlayer.getCurrentTime();
            if (typeof playerTime === 'number' && playerTime > 0) {
                pos = playerTime;
            }
        } catch (e) {}
    }

    if (pos <= 0) return;

    if (window._videoCardCache && window._videoCardCache[_currentStudioVideoId]) {
        window._videoCardCache[_currentStudioVideoId].last_position_seconds = pos;
    }

    try {
        const formData = new FormData();
        formData.append('position', pos.toFixed(1));
        await fetchAPI(`/api/videos/${_currentStudioVideoId}/position`, { method: 'POST', body: formData });
    } catch (e) {
        console.warn("Failed to auto-save video position:", e);
    }
}

function closeStudyStudio() {
    saveStudioVideoPosition();
    saveStudioNotes(true);
    if (_studioPositionSaveInterval) clearInterval(_studioPositionSaveInterval);
    _currentStudioPlayer = null;
    _currentStudioVideoCurrentTime = 0;

    const overlay = document.getElementById('overlay-study-studio');
    if (overlay) overlay.classList.add('hidden');

    const ytWrapper = document.getElementById('studio-yt-wrapper');
    if (ytWrapper) ytWrapper.innerHTML = '';
    const miniVideo = document.getElementById('mini-player-video');
    if (miniVideo) miniVideo.innerHTML = '';
    const miniPlayer = document.getElementById('studio-mini-player');
    if (miniPlayer) miniPlayer.classList.add('hidden');
}

// Re-parenting the YT iframe (minimize/restore) makes the browser reload it,
// which would otherwise snap playback back to the `start=` baked into the src
// when Study Studio was first opened. Reads the live position synchronously
// before the move, then forces a controlled reload at that position and
// rebinds the YT.Player - the old binding dies with the implicit reload.
function relocateStudioPlayer(iframe) {
    let resumeSec = _currentStudioVideoCurrentTime;
    if (_currentStudioPlayer && typeof _currentStudioPlayer.getCurrentTime === 'function') {
        try {
            const t = _currentStudioPlayer.getCurrentTime();
            if (typeof t === 'number' && t > 0) resumeSec = t;
        } catch (e) {}
    }

    try {
        const url = new URL(iframe.src);
        url.searchParams.set('start', Math.floor(resumeSec || 0));
        url.searchParams.set('autoplay', '1');
        iframe.src = url.toString();
    } catch (e) {}

    initStudioYTPlayerTracker();
}

function minimizeStudio() {
    const iframe = document.getElementById('studio-yt-iframe');
    const miniVideo = document.getElementById('mini-player-video');
    const miniPlayer = document.getElementById('studio-mini-player');
    const overlay = document.getElementById('overlay-study-studio');

    if (!iframe || !miniVideo || !miniPlayer) {
        closeStudyStudio();
        return;
    }

    saveStudioVideoPosition();
    saveStudioNotes();

    // No inline sizing here - the .yt-downscale-wrapper class on
    // #mini-player-video (same trick used for the main studio player)
    // handles cropping YouTube's own chrome out of the tiny embed.
    miniVideo.appendChild(iframe);
    relocateStudioPlayer(iframe);

    const miniTitle = document.getElementById('mini-player-title');
    const cardData = (window._videoCardCache && window._videoCardCache[_currentStudioVideoId]) || null;
    if (miniTitle) miniTitle.textContent = cardData ? cardData.title : 'Now Playing';

    if (overlay) overlay.classList.add('hidden');
    miniPlayer.classList.remove('hidden');
    initMiniPlayerDrag();
}

function restoreStudio() {
    const iframe = document.getElementById('studio-yt-iframe');
    const ytWrapper = document.getElementById('studio-yt-wrapper');
    const miniPlayer = document.getElementById('studio-mini-player');
    const overlay = document.getElementById('overlay-study-studio');

    if (iframe && ytWrapper) {
        ytWrapper.appendChild(iframe);
        relocateStudioPlayer(iframe);
    }
    if (miniPlayer) miniPlayer.classList.add('hidden');
    if (overlay) overlay.classList.remove('hidden');
}

function closeMiniPlayer() {
    saveStudioVideoPosition();
    saveStudioNotes(true);
    if (_studioPositionSaveInterval) clearInterval(_studioPositionSaveInterval);
    _currentStudioPlayer = null;
    _currentStudioVideoCurrentTime = 0;

    const miniPlayer = document.getElementById('studio-mini-player');
    const miniVideo = document.getElementById('mini-player-video');
    if (miniPlayer) miniPlayer.classList.add('hidden');
    if (miniVideo) miniVideo.innerHTML = '';
}

function updateStudioPlayIcons(isPlaying) {
    const playIcons = [document.getElementById('mini-icon-play'), document.getElementById('studio-icon-play')];
    const pauseIcons = [document.getElementById('mini-icon-pause'), document.getElementById('studio-icon-pause')];
    playIcons.forEach(el => { if (el) el.classList.toggle('hidden', isPlaying); });
    pauseIcons.forEach(el => { if (el) el.classList.toggle('hidden', !isPlaying); });
}

function studioTogglePlay() {
    let isPlaying = _studioIsPlaying;
    if (_currentStudioPlayer && typeof _currentStudioPlayer.getPlayerState === 'function') {
        try {
            const state = _currentStudioPlayer.getPlayerState();
            if (state === 1) isPlaying = true;
            else if (state === 2 || state === 0 || state === -1) isPlaying = false;
        } catch (e) {}
    }

    if (isPlaying) {
        callStudioPlayer('pauseVideo');
        _studioIsPlaying = false;
        updateStudioPlayIcons(false);
    } else {
        callStudioPlayer('playVideo');
        _studioIsPlaying = true;
        updateStudioPlayIcons(true);
    }
}

function studioSetSpeed(rate) {
    const numRate = parseFloat(rate);
    if (isNaN(numRate)) return;
    callStudioPlayer('setPlaybackRate', numRate);
}

let _studioCaptionsOn = false;

// The YouTube IFrame Player API has no officially documented captions toggle;
// this loadModule/setOption('track', ...) / unloadModule pair is the common
// workaround, and it silently no-ops if the video has no caption track.
function studioToggleCaptions() {
    try {
        _studioCaptionsOn = !_studioCaptionsOn;
        if (_studioCaptionsOn) {
            callStudioPlayer('loadModule', 'captions');
            callStudioPlayer('setOption', 'captions', 'track', { languageCode: 'en' });
        } else {
            callStudioPlayer('setOption', 'captions', 'track', {});
            callStudioPlayer('unloadModule', 'captions');
        }
        [document.getElementById('mini-btn-captions'), document.getElementById('studio-btn-captions')].forEach(btn => {
            if (btn) btn.classList.toggle('bg-amber-100', _studioCaptionsOn);
            if (btn) btn.classList.toggle('text-amber-700', _studioCaptionsOn);
        });
    } catch (e) {}
}

function studioSeek(deltaSeconds) {
    let cur = _currentStudioVideoCurrentTime || 0;
    if (_currentStudioPlayer && typeof _currentStudioPlayer.getCurrentTime === 'function') {
        try {
            const t = _currentStudioPlayer.getCurrentTime();
            if (typeof t === 'number' && !isNaN(t) && t > 0) cur = t;
        } catch (e) {}
    }
    const target = Math.max(0, cur + deltaSeconds);
    _currentStudioVideoCurrentTime = target;
    callStudioPlayer('seekTo', target, true);
}

function initMiniPlayerDrag() {
    const handle = document.getElementById('mini-player-drag-handle');
    const panel = document.getElementById('studio-mini-player');
    if (!handle || !panel || handle._dragBound) return;
    handle._dragBound = true;

    let dragging = false, startX = 0, startY = 0, startRight = 0, startBottom = 0;

    // Clicks on the restore/close buttons nested in this handle must not start a
    // drag - setPointerCapture below would swallow their click if we captured the
    // pointer from a press that started on them.
    handle.addEventListener('pointerdown', (e) => {
        if (e.target.closest('button')) return;
        dragging = true;
        startX = e.clientX;
        startY = e.clientY;
        const rect = panel.getBoundingClientRect();
        startRight = window.innerWidth - rect.right;
        startBottom = window.innerHeight - rect.bottom;
        handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        const rect = panel.getBoundingClientRect();
        const maxRight = Math.max(4, window.innerWidth - rect.width - 4);
        const maxBottom = Math.max(4, window.innerHeight - rect.height - 4);
        panel.style.right = Math.min(maxRight, Math.max(4, startRight - dx)) + 'px';
        panel.style.bottom = Math.min(maxBottom, Math.max(4, startBottom - dy)) + 'px';
    });
    handle.addEventListener('pointerup', () => { dragging = false; });
}

async function saveStudioNotes(showToastOnSave = false) {
    if (!_currentStudioVideoId) return;
    const editor = document.getElementById('studio-notes-editor');
    if (!editor) return;
    const notesContent = htmlToMarkdown(editor.innerHTML);

    try {
        const formData = new FormData();
        formData.append('custom_notes', notesContent);
        await fetchAPI(`/api/videos/${_currentStudioVideoId}/edit`, { method: 'POST', body: formData });
        if (window._videoCardCache && window._videoCardCache[_currentStudioVideoId]) {
            window._videoCardCache[_currentStudioVideoId].custom_notes = notesContent;
        }
        if (showToastOnSave && typeof showToast === 'function') {
            showToast('Studio notes & position saved', 'saved', 2000);
        }
    } catch (e) {
        console.error("Auto-save studio notes error:", e);
    }
}

function formatSecondsToClock(totalSecRaw) {
    const totalSec = Math.floor(totalSecRaw);
    const hrs = Math.floor(totalSec / 3600);
    const mins = Math.floor((totalSec % 3600) / 60);
    const secs = totalSec % 60;
    const pad = (n) => (n < 10 ? '0' + n : n);
    return hrs > 0 ? `${hrs}:${pad(mins)}:${pad(secs)}` : `${pad(mins)}:${pad(secs)}`;
}

let _studioMarkdownExtensionsRegistered = false;
function ensureStudioMarkdownExtensions() {
    if (_studioMarkdownExtensionsRegistered || typeof marked === 'undefined') return;
    marked.use({
        extensions: [{
            name: 'studioTimestamp',
            level: 'inline',
            start(src) {
                const m = src.match(/\{\{ts=\d+\}\}/);
                return m ? m.index : undefined;
            },
            tokenizer(src) {
                const match = /^\{\{ts=(\d+)\}\}/.exec(src);
                if (match) {
                    return { type: 'studioTimestamp', raw: match[0], seconds: parseInt(match[1], 10) };
                }
            },
            renderer(token) {
                const label = formatSecondsToClock(token.seconds);
                return `<span class="studio-ts-chip inline-block px-1.5 py-0.5 bg-amber-500/20 text-amber-800 rounded font-mono text-xs font-bold my-0.5 cursor-pointer hover:bg-amber-500/30" data-seconds="${token.seconds}" contenteditable="false" title="Jump to ${label}">[${label}]</span>`;
            }
        }]
    });
    _studioMarkdownExtensionsRegistered = true;
}

let _studioTurndownService = null;
function getStudioTurndownService() {
    if (_studioTurndownService || typeof TurndownService === 'undefined') return _studioTurndownService;
    _studioTurndownService = new TurndownService({ headingStyle: 'atx', bulletListMarker: '-' });
    _studioTurndownService.addRule('studioTimestampChip', {
        filter: (node) => node.nodeName === 'SPAN' && node.classList.contains('studio-ts-chip'),
        replacement: (content, node) => `{{ts=${node.getAttribute('data-seconds')}}}`
    });
    return _studioTurndownService;
}

function htmlToMarkdown(html) {
    const service = getStudioTurndownService();
    if (!service) return html;
    return service.turndown(html || '');
}

const STUDIO_MARKDOWN_SANITIZE_CONFIG = { ADD_ATTR: ['data-seconds', 'contenteditable'] };

function renderMarkdownSafe(text) {
    if (!text) return '';
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') return text;
    ensureStudioMarkdownExtensions();
    return DOMPurify.sanitize(marked.parse(text), STUDIO_MARKDOWN_SANITIZE_CONFIG);
}

function handleStudioTimestampChipClick(event) {
    const chip = event.target.closest('.studio-ts-chip[data-seconds]');
    if (!chip) return;
    event.preventDefault();
    const seconds = parseInt(chip.getAttribute('data-seconds'), 10);
    if (!Number.isFinite(seconds)) return;
    _currentStudioVideoCurrentTime = seconds;
    callStudioPlayer('seekTo', seconds, true);
    callStudioPlayer('playVideo');
    _studioIsPlaying = true;
    updateStudioPlayIcons(true);
}

function execEditorCommand(cmd, value = null) {
    document.execCommand(cmd, false, value);
}

function insertStudioTimestamp() {
    const editor = document.getElementById('studio-notes-editor');
    if (!editor) return;
    editor.focus();

    let pos = _currentStudioVideoCurrentTime;
    if (_currentStudioPlayer && typeof _currentStudioPlayer.getCurrentTime === 'function') {
        try {
            const pTime = _currentStudioPlayer.getCurrentTime();
            if (typeof pTime === 'number' && pTime > 0) pos = pTime;
        } catch (e) {}
    }

    if (pos > 0) {
        const seconds = Math.floor(pos);
        const label = formatSecondsToClock(seconds);
        document.execCommand('insertHTML', false, `<span class="studio-ts-chip inline-block px-1.5 py-0.5 bg-amber-500/20 text-amber-800 rounded font-mono text-xs font-bold my-0.5 cursor-pointer hover:bg-amber-500/30" data-seconds="${seconds}" contenteditable="false" title="Jump to ${label}">[${label}]</span>&nbsp;`);
    } else {
        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        document.execCommand('insertHTML', false, `<span class="inline-block px-1.5 py-0.5 bg-stone-200 text-stone-600 rounded font-mono text-xs font-bold my-0.5" contenteditable="false">[${timeStr}]</span>&nbsp;`);
    }
}

async function handleStudyButtonClick(event, videoId, level = 3) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    console.log("handleStudyButtonClick fired:", { videoId, level });
    
    if (!videoId || videoId === 'null' || videoId === 'undefined') {
        if (typeof showToast === 'function') {
            showToast("Video ID is missing.", "failed");
        } else {
            alert("Video ID is missing.");
        }
        return;
    }

    try {
        // The passed-in `level` is baked into the button's onclick HTML at the last
        // render, changeVideoRating() patches the star icons and _videoCardCache
        // directly without re-rendering the card, so onclick can still carry the
        // pre-change rating. Prefer the live cached value so a rating change followed
        // immediately by Study doesn't call generate_quiz with a stale level and flip
        // the quiz's importance_level back.
        const liveLevel = (window._videoCardCache && window._videoCardCache[videoId] && window._videoCardCache[videoId].importance_rating) || level;
        const formData = new FormData();
        formData.append('level', liveLevel);
        const res = await fetchAPI(`/api/videos/${videoId}/generate_quiz`, {
            method: 'POST',
            body: formData
        });
        if (res && res.quiz_id) {
            const startFn = window.startQuiz || (typeof startQuiz === 'function' ? startQuiz : null);
            if (startFn) {
                return startFn(res.quiz_id, videoId, liveLevel);
            } else {
                if (typeof showToast === 'function') {
                    showToast("Quiz module is still loading. Please try again in a moment.", "info");
                } else {
                    alert("Quiz module is still loading. Please try again in a moment.");
                }
            }
        } else {
            if (typeof showToast === 'function') {
                showToast("Quiz generation response missing quiz_id.", "failed");
            } else {
                alert("Quiz generation response did not contain a valid quiz_id.");
            }
        }
    } catch (e) {
        console.error("Study click error:", e);
        if (typeof showToast === 'function') {
            showToast("Could not start quiz session: " + (e.detail || e.message || e), "failed");
        } else {
            alert("Could not start quiz session: " + (e.detail || e.message || e));
        }
    }
}

// Window bindings for inline HTML attribute calls
window.handleStudyButtonClick = handleStudyButtonClick;
window.initImportTab = initImportTab;
window.renderVideoCard = renderVideoCard;
window.scrollToVideoCard = scrollToVideoCard;
window.openFocusModal = openFocusModal;
window.closeFocusModal = closeFocusModal;
window.initFocusModalEvents = initFocusModalEvents;
window.toggleVideoDetails = toggleVideoDetails;
window.toggleVideoMenu = toggleVideoMenu;
window.closeVideoMenu = closeVideoMenu;
window.pauseVideo = pauseVideo;
window.archiveVideo = archiveVideo;
window.deleteVideo = deleteVideo;
window.toggleWatchlist = toggleWatchlist;
window.retryVideoImport = retryVideoImport;
window.changeVideoRating = changeVideoRating;
window.showFactCheck = showFactCheck;
window.closeFactCheckModal = closeFactCheckModal;
window.initFactCheckEvents = initFactCheckEvents;
window.openEditVideoModal = openEditVideoModal;
window.initEditVideoEvents = initEditVideoEvents;
window.openVideoStatsModal = openVideoStatsModal;
window.closeVideoStatsModal = closeVideoStatsModal;
window.toggleVideoStatSession = toggleVideoStatSession;
window.openStudyStudio = openStudyStudio;
window.closeStudyStudio = closeStudyStudio;
window.minimizeStudio = minimizeStudio;
window.saveStudioNotes = saveStudioNotes;
window.execEditorCommand = execEditorCommand;
window.insertStudioTimestamp = insertStudioTimestamp;
window.restoreStudio = restoreStudio;
window.closeMiniPlayer = closeMiniPlayer;
window.studioTogglePlay = studioTogglePlay;
window.studioSetSpeed = studioSetSpeed;
window.studioSeek = studioSeek;
async function confirmPreviewImport(id, btnEl = null) {
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Importing...</span>`;
        if (typeof renderIcons === 'function') renderIcons();
        else if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    try {
        const res = await fetchAPI(`/api/videos/${id}/confirm_import`, { method: 'POST' });
        if (typeof showToast === 'function') {
            showToast('Import started, you can keep working.', 'saved', 3000);
        }
        if (window.globalImportBacklog) {
            window.globalImportBacklog.toggleDrawer(true);
            window.globalImportBacklog.poll();
        }
        if (typeof loadGoals === 'function') await loadGoals();
        if (typeof loadDashboard === 'function') await loadDashboard();
    } catch (e) {
        console.error("Confirm import error:", e);
        if (typeof showToast === 'function') showToast('Failed to import material', 'failed', 3000);
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = `<i data-lucide="plus-circle" class="w-3.5 h-3.5"></i><span>Import to Goal</span>`;
            if (typeof renderIcons === 'function') renderIcons();
            else if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
}
window.confirmPreviewImport = confirmPreviewImport;




