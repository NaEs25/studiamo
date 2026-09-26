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

async function getImportanceMeta(rating) {
    const counts = await getUserQuestionCounts();
    const metaMap = {
        1: { title: "Reference Material (1 Star)", qs: `${counts[1] || 2} Recall Questions`, text: `Low recall density & scaled back repetition frequency. Generates ${counts[1] || 2} questions.` },
        2: { title: "Basic Concepts (2 Stars)", qs: `${counts[2] || 3} Recall Questions`, text: `Fundamental overview. Generates ${counts[2] || 3} active-recall questions.` },
        3: { title: "Standard Study (3 Stars)", qs: `${counts[3] || 5} Recall Questions`, text: `Standard quiz depth & review interval frequency. Generates ${counts[3] || 5} questions.` },
        4: { title: "High Detail (4 Stars)", qs: `${counts[4] || 8} Recall Questions`, text: `Comprehensive coverage with ${counts[4] || 8} recall questions for detailed retention.` },
        5: { title: "Crucial Retention (5 Stars)", qs: `${counts[5] || 12} Recall Questions`, text: `Maximum quiz density with ${counts[5] || 12} recall questions and high-priority SRS review schedule.` }
    };
    return metaMap[rating] || metaMap[3];
}

// Fills the stars up to `rating` in the container rendered by partials/_star_selector.html.
function paintStars(container, rating) {
    container.querySelectorAll('.star-select-btn').forEach(btn => {
        const icon = btn.querySelector('.star-icon') || btn.querySelector('svg');
        if (!icon) return;
        const filled = parseInt(btn.dataset.star) <= rating;
        icon.setAttribute('fill', filled ? '#f59e0b' : 'none');
        icon.setAttribute('stroke', filled ? '#f59e0b' : '#475569');
        icon.classList.toggle('scale-105', filled);
    });
}

// Wires the click handlers once per container and returns a setter that repaints the stars.
// onSelect fires only for user clicks, not for programmatic set calls.
function initStarSelector(containerId, onSelect) {
    const container = document.getElementById(containerId);
    if (!container) return null;
    if (!container._setStars) {
        container._onSelect = onSelect;
        container._setStars = (rating) => paintStars(container, rating);
        container.querySelectorAll('.star-select-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const val = parseInt(btn.dataset.star);
                paintStars(container, val);
                if (container._onSelect) container._onSelect(val);
            });
        });
    }
    return container._setStars;
}

function initImportanceStars() {
    const hiddenInput = document.getElementById('input-importance');
    const labelVal = document.getElementById('label-importance-value');
    const descTitle = document.getElementById('importance-desc-title');
    const descQs = document.getElementById('importance-desc-qs');
    const descText = document.getElementById('importance-desc-text');
    const infoToggle = document.getElementById('importance-info-toggle');
    const descBox = document.getElementById('importance-desc-box');

    if (infoToggle && descBox && !infoToggle._bound) {
        infoToggle._bound = true;
        infoToggle.addEventListener('click', () => {
            const nowHidden = descBox.classList.toggle('hidden');
            infoToggle.setAttribute('aria-expanded', String(!nowHidden));
        });
    }

    async function updateStars(rating) {
        if (hiddenInput) hiddenInput.value = rating;
        const info = await getImportanceMeta(rating);
        if (labelVal) labelVal.textContent = info.title;
        if (descTitle) descTitle.textContent = info.title;
        if (descQs) descQs.textContent = info.qs;
        if (descText) descText.textContent = info.text;
    }

    const setStars = initStarSelector('importance-star-container', updateStars);
    const initial = hiddenInput ? parseInt(hiddenInput.value) || 3 : 3;
    if (setStars) setStars(initial);
    updateStars(initial);
}

// The edit modal's picker. #edit-video-rating is a hidden input so the submit handler reads it
// like any other field.
function initEditVideoStars() {
    const ratingEl = document.getElementById('edit-video-rating');
    const labelEl = document.getElementById('edit-video-rating-label');
    if (!ratingEl) return null;

    async function setRating(rating) {
        ratingEl.value = rating;
        if (!labelEl) return;
        const info = await getImportanceMeta(rating);
        // A later call may have landed while the counts were loading.
        if (ratingEl.value === String(rating)) labelEl.textContent = `${info.title}: ${info.qs}`;
    }

    const setStars = initStarSelector('edit-video-star-container', setRating);
    return (rating) => {
        if (setStars) setStars(rating);
        return setRating(rating);
    };
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
    
    // Only .is-active moves. The buttons' own .segmented-tab styling and their padding
    // stay in the template: this used to reassign .className with a full utility chain
    // per state, which meant the same two chains were maintained here and in the markup.
    function resetImportPanels() {
        if (panelYt) panelYt.classList.add('hidden');
        if (panelDoc) panelDoc.classList.add('hidden');
        if (panelNotes) panelNotes.classList.add('hidden');

        [btnYt, btnDoc, btnNotes].forEach(b => b && b.classList.remove('is-active'));
    }

    function setTab(tab) {
        resetImportPanels();
        if (tab === 'youtube') {
            if (panelYt) panelYt.classList.remove('hidden');
            if (btnYt) btnYt.classList.add('is-active');
        } else if (tab === 'document') {
            if (panelDoc) panelDoc.classList.remove('hidden');
            if (btnDoc) btnDoc.classList.add('is-active');
        } else if (tab === 'notes') {
            if (panelNotes) panelNotes.classList.remove('hidden');
            if (btnNotes) btnNotes.classList.add('is-active');
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
                    const conf = await showConfirm({
                        title: "Create Recommended Goal?",
                        message: `AI Recommendation:\nThis material doesn't fit your active goals.\nShould we create a new Goal: "${result.recommended_new_goal.title}"?`,
                        confirmText: "Create Goal",
                        icon: "sparkles"
                    });
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
                // Refresh header stats/goal boxes first (they're visible across tabs),
                // then land on the goals tab with the new card highlighted, the same
                // way clicking a thumbnail on the dashboard does (navigateToVideoInGoals).
                if (typeof loadDashboard === 'function') await loadDashboard();

                if (window.globalImportBacklog) {
                    window.globalImportBacklog.toggleDrawer(true);
                    window.globalImportBacklog.poll();
                }

                if (typeof navigateToVideoInGoals === 'function') navigateToVideoInGoals(result.video_id);

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

    // One "Stage:" label and number-only buttons: five "Stage N" pills overflowed a phone and
    // repeated the word. The full name of each stage stays in the tooltip and aria-label.
    const buttons = focusState.stages.map(s => {
        const active = s.stage === focusState.activeStage;
        const cls = active
            ? 'bg-amber-100 border-amber-300 text-amber-900'
            : 'bg-white border-[#e7dfd3] text-stone-600 hover:bg-stone-50';
        return `<button type="button" data-stage-tab="${s.stage}" title="${escapeHtml(s.label)}"
            aria-label="Stage ${s.stage}: ${escapeHtml(s.label)}" aria-pressed="${active}"
            class="shrink-0 min-w-[2rem] h-8 px-2 rounded-lg border text-xs font-bold transition ${cls}">${s.stage}</button>`;
    }).join('');

    tabs.innerHTML = `<span class="text-[11px] font-bold uppercase tracking-wider text-stone-500 mr-1.5 shrink-0">Stage</span>${buttons}`;

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

// A card action (add, edit, remove or rename) disables every card control for at least this
// long, with a spinner on the one that fired, so a double-click cannot queue a second edit
// behind the first. The server serializes edits regardless; this only keeps the interface
// honest about it.
const FOCUS_CARD_COOLDOWN_MS = 1000;

const FOCUS_FIELD_CLASS = 'w-full bg-[#fcfaf6] border border-[#e7dfd3] rounded-lg px-2.5 py-1.5 text-xs text-stone-900 focus:outline-none focus:border-amber-500';

function focusTopicKey(stageIndex, topic) {
    return `${stageIndex}|${topic}`;
}

function focusSpinnerHTML() {
    return '<span class="inline-block animate-spin rounded-full h-3.5 w-3.5 border-2 border-amber-600 border-t-transparent" role="status" aria-label="Working"></span>';
}

const FOCUS_ICON_BUTTON = 'p-1 rounded-lg transition shrink-0 disabled:opacity-40 disabled:cursor-not-allowed';

// The one inline editor open at a time: adding a question, editing one, or renaming a topic.
//   { kind: 'add' | 'edit' | 'rename', stage, topic, cardId, draft: { topic, question, answer } }
// `topic` is the topic being added to (null for a brand new topic), or the one being renamed.
function focusEditorIs(kind, test) {
    const ed = focusState && focusState.editor;
    return !!(ed && ed.kind === kind && (!test || test(ed)));
}

function renderFocusEditorButtons(kind) {
    const busy = focusState.busy;
    const label = kind === 'add' ? 'Add' : 'Save';
    return `
        <div class="flex items-center gap-2">
            <button type="button" data-editor-submit ${busy ? 'disabled' : ''}
                class="btn-primary px-3 py-1.5 font-extrabold rounded-lg text-[11px] transition flex items-center gap-1.5 disabled:opacity-60 disabled:cursor-not-allowed">
                ${focusState.busyTarget === kind ? focusSpinnerHTML() : ''}<span>${label}</span>
            </button>
            <button type="button" data-editor-cancel ${busy ? 'disabled' : ''}
                class="px-3 py-1.5 rounded-lg text-[11px] font-bold text-stone-600 hover:bg-stone-100 transition disabled:opacity-40">
                Cancel
            </button>
        </div>`;
}

function renderFocusFields(draft, withTopic) {
    return `
        ${withTopic ? `<input type="text" data-draft-field="topic" list="focus-topic-options" maxlength="60" placeholder="Topic" value="${escapeHtml(draft.topic)}" class="${FOCUS_FIELD_CLASS}">` : ''}
        <textarea data-draft-field="question" rows="2" maxlength="500" placeholder="Question" class="${FOCUS_FIELD_CLASS}">${escapeHtml(draft.question)}</textarea>
        <textarea data-draft-field="answer" rows="2" maxlength="1000" placeholder="Answer" class="${FOCUS_FIELD_CLASS}">${escapeHtml(draft.answer)}</textarea>`;
}

function renderFocusQuestion(q) {
    if (focusEditorIs('edit', ed => ed.cardId === q.id)) {
        return `
            <div class="py-2 space-y-1.5">
                ${renderFocusFields(focusState.editor.draft, true)}
                ${renderFocusEditorButtons('edit')}
            </div>`;
    }

    const busy = focusState.busy;
    const pending = focusState.busyTarget === q.id;
    let badge = '';
    if (q.origin === 'human') {
        badge = '<span class="text-[9px] font-bold uppercase tracking-wider text-stone-600 bg-stone-100 border border-stone-200 rounded px-1.5 py-0.5 shrink-0">You</span>';
    } else if (q.edited) {
        badge = '<span class="text-[9px] font-bold uppercase tracking-wider text-sky-700 bg-sky-50 border border-sky-200 rounded px-1.5 py-0.5 shrink-0">Edited</span>';
    }
    return `
        <div class="flex items-start gap-1.5 py-1.5">
            <div class="min-w-0 grow">
                <p class="text-xs font-semibold text-stone-800 break-words">${escapeHtml(q.question)}</p>
                <p class="text-[11px] text-stone-500 break-words mt-0.5">${escapeHtml(q.answer)}</p>
            </div>
            ${badge}
            <button type="button" data-card-edit="${escapeHtml(q.id)}" ${busy ? 'disabled' : ''}
                aria-label="Edit this question" title="Edit this question"
                class="${FOCUS_ICON_BUTTON} text-stone-400 hover:text-stone-800 hover:bg-stone-100">
                <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
            </button>
            <button type="button" data-card-remove="${escapeHtml(q.id)}" ${busy ? 'disabled' : ''}
                aria-label="Remove this question" title="Remove this question"
                class="${FOCUS_ICON_BUTTON} text-stone-400 hover:text-red-600 hover:bg-red-50">
                ${pending ? focusSpinnerHTML() : '<i data-lucide="x" class="w-3.5 h-3.5"></i>'}
            </button>
        </div>`;
}

function renderFocusAddControl(stageIndex, topic) {
    const busy = focusState.busy;
    if (focusEditorIs('add', ed => ed.stage === stageIndex && ed.topic === topic)) {
        return `
            <div class="mt-1.5 space-y-1.5">
                ${renderFocusFields(focusState.editor.draft, topic === null)}
                ${renderFocusEditorButtons('add')}
            </div>`;
    }
    return `
        <button type="button" data-card-add-open="${escapeHtml(topic === null ? '' : topic)}" data-new-topic="${topic === null ? '1' : '0'}" ${busy ? 'disabled' : ''}
            class="mt-1 flex items-center gap-1.5 text-[11px] font-bold text-amber-700 hover:text-amber-900 transition disabled:opacity-40 disabled:cursor-not-allowed">
            <i data-lucide="plus" class="w-3.5 h-3.5"></i>
            <span>${topic === null ? 'New topic' : 'Add question'}</span>
        </button>`;
}

function renderFocusTopicHeader(t, i, expanded) {
    const busy = focusState.busy;
    if (focusEditorIs('rename', ed => ed.topic === t.topic)) {
        const saving = focusState.busyTarget === 'rename';
        return `
            <div class="flex items-center gap-1.5 p-2.5">
                <input type="text" data-draft-field="topic" maxlength="60" aria-label="Topic name"
                    value="${escapeHtml(focusState.editor.draft.topic)}" class="${FOCUS_FIELD_CLASS} grow min-w-0">
                <button type="button" data-editor-submit ${busy ? 'disabled' : ''} aria-label="Save topic name" title="Save topic name"
                    class="${FOCUS_ICON_BUTTON} text-emerald-700 hover:bg-emerald-50">
                    ${saving ? focusSpinnerHTML() : '<i data-lucide="check" class="w-4 h-4"></i>'}
                </button>
                <button type="button" data-editor-cancel ${busy ? 'disabled' : ''} aria-label="Cancel" title="Cancel"
                    class="${FOCUS_ICON_BUTTON} text-stone-500 hover:bg-stone-100">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>`;
    }

    return `
        <div class="flex items-center justify-between gap-2 p-2.5">
            <label class="flex items-center gap-2.5 min-w-0 grow cursor-pointer">
                <input type="checkbox" data-topic-check="${i}" ${t.selected ? 'checked' : ''}
                    class="w-4 h-4 rounded border-stone-300 text-amber-600 focus:ring-amber-500 shrink-0">
                <span class="text-xs font-semibold text-stone-800 truncate">${escapeHtml(t.topic)}</span>
            </label>
            <span class="flex items-center gap-1 shrink-0">
                ${t.recommended ? '<span class="text-[9px] font-bold uppercase tracking-wider text-amber-700 bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5">AI</span>' : ''}
                <button type="button" data-topic-rename="${i}" ${busy ? 'disabled' : ''} aria-label="Rename this topic" title="Rename this topic (all stages)"
                    class="${FOCUS_ICON_BUTTON} text-stone-400 hover:text-stone-800 hover:bg-stone-100">
                    <i data-lucide="pencil" class="w-3.5 h-3.5"></i>
                </button>
                <button type="button" data-topic-toggle="${i}" aria-expanded="${expanded}"
                    class="flex items-center gap-1 text-[10px] text-stone-500 font-medium rounded-lg px-1.5 py-1 hover:bg-stone-100 transition">
                    <span>${t.count} ${t.count === 1 ? 'question' : 'questions'}</span>
                    <i data-lucide="chevron-down" class="w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}"></i>
                </button>
            </span>
        </div>`;
}

function renderFocusTopics() {
    const list = document.getElementById('focus-topic-list');
    const stage = currentFocusStage();
    if (!list || !stage) return;

    const topicsHTML = stage.topics.map((t, i) => {
        const expanded = focusState.expanded.has(focusTopicKey(stage.stage, t.topic));
        const body = expanded ? `
            <div class="border-t border-[#e7dfd3] px-3 py-1.5 divide-y divide-[#f0e9de]">
                ${t.questions.map(renderFocusQuestion).join('')}
                <div class="pt-1.5">${renderFocusAddControl(stage.stage, t.topic)}</div>
            </div>` : '';
        return `
        <div class="rounded-xl border border-[#e7dfd3]">
            ${renderFocusTopicHeader(t, i, expanded)}
            ${body}
        </div>`;
    }).join('');

    // Suggestions for the topic field of the edit and new-topic forms, so moving a question to
    // an existing topic is a pick rather than a retype.
    const options = stage.topics.map(t => `<option value="${escapeHtml(t.topic)}"></option>`).join('');

    list.innerHTML = `<datalist id="focus-topic-options">${options}</datalist>`
        + topicsHTML
        + `<div class="pt-1">${renderFocusAddControl(stage.stage, null)}</div>`;

    renderIcons();
    renderFocusStatus();
}

// Folds a fresh server listing into the overlay without losing what the user has not saved:
// the ticked topics, which topics are open, and the active stage. A topic the listing has not
// seen before is one the user just created, so it starts ticked. `renamed` ({from, to}) carries
// the state of a renamed topic across to its new name in every stage.
function mergeFocusListing(data, renamed) {
    const previous = new Map();
    focusState.stages.forEach(s => s.topics.forEach(t => previous.set(focusTopicKey(s.stage, t.topic), t.selected)));
    const expanded = new Set(focusState.expanded);

    if (renamed) {
        for (let stageIndex = 0; stageIndex < 5; stageIndex++) {
            const from = focusTopicKey(stageIndex, renamed.from);
            const to = focusTopicKey(stageIndex, renamed.to);
            if (previous.has(from)) previous.set(to, previous.get(from));
            if (expanded.delete(from)) expanded.add(to);
        }
    }

    data.stages.forEach(s => s.topics.forEach(t => {
        const key = focusTopicKey(s.stage, t.topic);
        t.selected = previous.has(key) ? previous.get(key) : true;
    }));

    focusState.stages = data.stages;
    focusState.targetCount = data.target_count;
    focusState.expanded = expanded;
    if (!focusState.stages.some(s => s.stage === focusState.activeStage) && focusState.stages.length) {
        focusState.activeStage = focusState.stages[0].stage;
    }
}

async function runFocusCardAction(target, request, renamed) {
    const state = focusState;
    if (!state || state.busy) return false;

    state.busy = true;
    state.busyTarget = target;
    renderFocusTopics();

    const started = Date.now();
    let ok = false;
    try {
        const data = await request();
        if (focusState === state) {
            mergeFocusListing(data, renamed);
            ok = true;
        }
    } catch (e) {
        showToast(e.detail || e.message || 'Could not update the questions.', 'failed', 4000);
    }

    const remaining = FOCUS_CARD_COOLDOWN_MS - (Date.now() - started);
    if (remaining > 0) await new Promise(resolve => setTimeout(resolve, remaining));

    if (focusState === state) {
        state.busy = false;
        state.busyTarget = null;
        renderFocusTopics();
    }
    return ok;
}

async function removeFocusCard(cardId) {
    await runFocusCardAction(cardId, () =>
        fetchAPI(`/api/videos/${focusState.videoId}/cards/${encodeURIComponent(cardId)}`, { method: 'DELETE' })
    );
}

function findFocusTopic(stageIndex, name) {
    const stage = focusState.stages.find(s => s.stage === stageIndex);
    return stage && stage.topics.find(t => t.topic.toLowerCase() === name.toLowerCase());
}

async function submitFocusEditor() {
    const ed = focusState && focusState.editor;
    if (!ed || focusState.busy) return;

    const draft = ed.draft;
    const topic = (draft.topic || '').trim();
    const question = (draft.question || '').trim();
    const answer = (draft.answer || '').trim();
    const videoId = focusState.videoId;

    if (ed.kind === 'rename') {
        if (!topic) { showToast('Give the topic a name.', 'failed', 3000); return; }
        if (topic === ed.topic) { focusState.editor = null; renderFocusTopics(); return; }
        const body = new FormData();
        body.append('old_topic', ed.topic);
        body.append('new_topic', topic);
        const ok = await runFocusCardAction('rename',
            () => fetchAPI(`/api/videos/${videoId}/topics/rename`, { method: 'POST', body }),
            { from: ed.topic, to: topic });
        if (ok && focusState) { focusState.editor = null; renderFocusTopics(); }
        return;
    }

    if (ed.kind === 'add') {
        const targetTopic = ed.topic === null ? topic : ed.topic;
        if (!targetTopic || !question || !answer) {
            showToast(ed.topic === null ? 'Add a topic, a question and an answer.' : 'Add both a question and an answer.', 'failed', 3000);
            return;
        }
        const body = new FormData();
        body.append('stage', String(ed.stage));
        body.append('topic', targetTopic);
        body.append('question', question);
        body.append('answer', answer);
        const ok = await runFocusCardAction('add',
            () => fetchAPI(`/api/videos/${videoId}/cards`, { method: 'POST', body }));
        if (ok && focusState) {
            // Open the topic the card landed in. The server may have matched an existing topic
            // with different capitalization, so look it up rather than trusting what was typed.
            const landed = findFocusTopic(ed.stage, targetTopic);
            if (landed) focusState.expanded.add(focusTopicKey(ed.stage, landed.topic));
            focusState.editor = null;
            renderFocusTopics();
        }
        return;
    }

    // edit
    if (!topic || !question || !answer) {
        showToast('A question needs a topic, a question and an answer.', 'failed', 3000);
        return;
    }
    const body = new FormData();
    body.append('topic', topic);
    body.append('question', question);
    body.append('answer', answer);
    const ok = await runFocusCardAction('edit',
        () => fetchAPI(`/api/videos/${videoId}/cards/${encodeURIComponent(ed.cardId)}`, { method: 'PATCH', body }));
    if (ok && focusState) {
        const landed = findFocusTopic(ed.stage, topic);
        if (landed) focusState.expanded.add(focusTopicKey(ed.stage, landed.topic));
        focusState.editor = null;
        renderFocusTopics();
    }
}

function openFocusEditor(editor, focusSelector) {
    focusState.editor = editor;
    renderFocusTopics();
    const field = document.querySelector(focusSelector) || document.querySelector('[data-draft-field]');
    if (field) {
        field.focus();
        if (field.select && field.tagName === 'INPUT') field.select();
    }
}

function cancelFocusEditor() {
    if (!focusState || focusState.busy || !focusState.editor) return;
    focusState.editor = null;
    renderFocusTopics();
}

// Editing questions and topics is built for a keyboard and a wide screen. On a phone the
// controls stay visible so the feature can be discovered, but they explain instead of acting.
// Same width the rest of the app treats as "small" (Tailwind's sm breakpoint).
function focusEditingUnavailable() {
    if (window.innerWidth >= 640) return false;
    showToast('Editing questions is not available on phones yet. Open Studiamo on a computer to edit.', 'info', 5000);
    return true;
}

let focusRemoveTimer = null;

function armFocusRemove(btn) {
    disarmFocusRemove();
    focusState.pendingRemove = btn.dataset.cardRemove;
    btn.dataset.idleHtml = btn.innerHTML;
    btn.innerHTML = '<span class="text-[10px] font-bold px-1">Remove?</span>';
    btn.classList.add('text-red-600', 'bg-red-50');
    btn.title = 'Tap again to remove';
    // An armed button that is never followed up should not stay armed indefinitely.
    focusRemoveTimer = setTimeout(disarmFocusRemove, 4000);
}

function disarmFocusRemove() {
    clearTimeout(focusRemoveTimer);
    if (focusState) focusState.pendingRemove = null;
    document.querySelectorAll('[data-card-remove]').forEach(b => {
        if (b.dataset.idleHtml) {
            b.innerHTML = b.dataset.idleHtml;
            delete b.dataset.idleHtml;
        }
        b.classList.remove('text-red-600', 'bg-red-50');
        b.title = 'Remove this question';
    });
}

function handleFocusListClick(e) {
    if (!focusState) return;
    const stage = currentFocusStage();

    // Any click that is not on the armed remove button disarms it.
    const clickedRemove = e.target.closest('[data-card-remove]');
    if (focusState.pendingRemove && (!clickedRemove || clickedRemove.dataset.cardRemove !== focusState.pendingRemove)) {
        disarmFocusRemove();
    }

    const toggle = e.target.closest('[data-topic-toggle]');
    if (toggle && stage) {
        const key = focusTopicKey(stage.stage, stage.topics[parseInt(toggle.dataset.topicToggle, 10)].topic);
        if (focusState.expanded.has(key)) focusState.expanded.delete(key);
        else focusState.expanded.add(key);
        renderFocusTopics();
        return;
    }

    if (clickedRemove) {
        if (clickedRemove.disabled) return;
        // Two taps: the first arms the button, the second removes. Removal is permanent and
        // the question may be one the user wrote, so a stray tap must not be enough.
        if (focusEditingUnavailable()) return;
        if (focusState.pendingRemove !== clickedRemove.dataset.cardRemove) {
            armFocusRemove(clickedRemove);
            return;
        }
        disarmFocusRemove();
        removeFocusCard(clickedRemove.dataset.cardRemove);
        return;
    }

    const add = e.target.closest('[data-card-add-open]');
    if (add && stage) {
        if (add.disabled || focusState.busy || focusEditingUnavailable()) return;
        const isNewTopic = add.dataset.newTopic === '1';
        openFocusEditor({
            kind: 'add', stage: stage.stage, topic: isNewTopic ? null : add.dataset.cardAddOpen,
            draft: { topic: '', question: '', answer: '' }
        }, isNewTopic ? '[data-draft-field="topic"]' : '[data-draft-field="question"]');
        return;
    }

    const edit = e.target.closest('[data-card-edit]');
    if (edit && stage) {
        if (edit.disabled || focusState.busy || focusEditingUnavailable()) return;
        const cardId = edit.dataset.cardEdit;
        for (const t of stage.topics) {
            const q = t.questions.find(item => item.id === cardId);
            if (q) {
                openFocusEditor({
                    kind: 'edit', stage: stage.stage, topic: t.topic, cardId,
                    draft: { topic: t.topic, question: q.question, answer: q.answer }
                }, '[data-draft-field="question"]');
                break;
            }
        }
        return;
    }

    const rename = e.target.closest('[data-topic-rename]');
    if (rename && stage) {
        if (rename.disabled || focusState.busy || focusEditingUnavailable()) return;
        const t = stage.topics[parseInt(rename.dataset.topicRename, 10)];
        openFocusEditor({
            kind: 'rename', stage: stage.stage, topic: t.topic,
            draft: { topic: t.topic, question: '', answer: '' }
        }, '[data-draft-field="topic"]');
        return;
    }

    if (e.target.closest('[data-editor-cancel]')) {
        cancelFocusEditor();
        return;
    }

    if (e.target.closest('[data-editor-submit]')) {
        submitFocusEditor();
    }
}

function handleFocusListChange(e) {
    const box = e.target.closest('[data-topic-check]');
    const stage = currentFocusStage();
    if (!box || !stage) return;
    stage.topics[parseInt(box.dataset.topicCheck, 10)].selected = box.checked;
    renderFocusStatus();
}

function handleFocusListInput(e) {
    const field = e.target.closest('[data-draft-field]');
    if (field && focusState && focusState.editor) {
        focusState.editor.draft[field.dataset.draftField] = field.value;
    }
}

function handleFocusListKeydown(e) {
    if (!focusState || !focusState.editor) return;
    if (e.key === 'Escape') {
        // Cancels the inline editor without also closing the overlay (core.js closes on Escape
        // at document level, which this stops before it gets there).
        e.stopPropagation();
        cancelFocusEditor();
    } else if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
        e.preventDefault();
        submitFocusEditor();
    }
}

function renderFocusStatus() {
    const el = document.getElementById('focus-status');
    const stage = currentFocusStage();
    if (!el || !stage) return;

    const selected = stage.topics.filter(t => t.selected).reduce((n, t) => n + t.count, 0);
    const target = focusState.targetCount;

    // Phrased around what saving does, not what is ticked. A saved selection is honoured
    // exactly, so picking fewer than the star rating genuinely shortens the session, whereas
    // leaving it untouched lets the AI's picks be topped up to the full length.
    let cls, text;
    if (selected === 0) {
        cls = 'bg-red-50 border-red-200 text-red-700';
        text = 'No topics selected. Pick at least one before saving.';
    } else if (selected < target) {
        cls = 'bg-amber-50 border-amber-200 text-amber-800';
        text = `Saving now gives ${selected} question${selected === 1 ? '' : 's'} per session, fewer than the ${target} this material is set to.`;
    } else {
        cls = 'bg-emerald-50 border-emerald-200 text-emerald-800';
        text = `${selected} questions selected. The ${target} best-fitting will be used each session.`;
    }
    // Swaps only the tint, leaving the box's shape (text-xs font-semibold rounded-xl px-3
    // py-2 border) on the element where the template put it. Rewriting .className here
    // meant that shape was declared twice and only one copy was ever applied.
    el.classList.remove(
        'bg-red-50', 'border-red-200', 'text-red-700',
        'bg-amber-50', 'border-amber-200', 'text-amber-800',
        'bg-emerald-50', 'border-emerald-200', 'text-emerald-800'
    );
    el.classList.add(...cls.split(' '));
    el.textContent = text;
}

async function openFocusModal(videoId) {
    const overlay = document.getElementById('overlay-focus');
    if (!overlay) {
        // Returning quietly here meant a click did nothing at all, with no way to tell why.
        // The markup ships with the page, so its absence means the document is older than
        // this script: either a stale cached page, or a server that did not render the
        // include.
        console.error('Focus overlay markup (#overlay-focus) is not in the page.');
        showToast('Please reload the page to finish loading this feature.', 'failed', 5000);
        return;
    }

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
            expanded: new Set(),
            editor: null,
            pendingRemove: null,
            busy: false,
            busyTarget: null,
            // Open on the stage the learner is actually on, not always stage 0.
            activeStage: data.stages.some(s => s.stage === data.current_stage)
                ? data.current_stage
                : data.stages[0].stage
        };

        const subtitle = document.getElementById('focus-modal-subtitle');
        if (subtitle) subtitle.textContent = data.title || '';

        openOverlay('overlay-focus', closeFocusModal);
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
    closeOverlay('overlay-focus');
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

    const list = document.getElementById('focus-topic-list');
    if (list) {
        list.addEventListener('click', handleFocusListClick);
        list.addEventListener('change', handleFocusListChange);
        list.addEventListener('input', handleFocusListInput);
        list.addEventListener('keydown', handleFocusListKeydown);
    }

    if (close) close.addEventListener('click', closeFocusModal);
    if (save) save.addEventListener('click', saveFocusSelection);
    if (reset) reset.addEventListener('click', resetFocusToRecommendation);
    if (overlay) {
        // Click-outside-to-close. Escape is handled centrally by openOverlay/closeOverlay
        // in core.js now, which this modal's own open/close functions already call into.
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeFocusModal();
        });
    }
}

function renderVideoCard(video, quizzes, goals) {
    const activeQuiz = quizzes && (
        quizzes.find(q => String(q.video_id) === String(video.id) && Number(q.importance_level) === Number(video.importance_rating)) ||
        quizzes.find(q => String(q.video_id) === String(video.id))
    );
    const srsStage = activeQuiz ? activeQuiz.srs_stage : 0;
    const isMastered = activeQuiz ? !!activeQuiz.mastered : false;
    const isPaused = video.is_paused ? true : false;

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
    let isNormalState = false;
    if (isTemporaryVideo(video)) {
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
            <button onclick="retryVideoImport(${video.id})" class="w-full py-2 bg-red-50 hover:bg-red-100 border border-red-200 text-red-600 font-bold rounded-xl text-xs transition flex items-center justify-center space-x-1.5 h-[38px]" title="Retry Video Import: ${escapeHtml(video.status_error) || 'Import Failed'}">
                 <i data-lucide="rotate-cw" class="w-3.5 h-3.5"></i>
                 <span>Retry</span>
            </button>
        `;
    } else {
        isNormalState = true;
        const levelToUse = video.importance_rating || video.importance_level || 3;
        actionControlsHTML = `
            <button onclick="handleStudyButtonClick(event, ${video.id}, ${levelToUse})" class="w-full px-3 py-2 bg-stone-100 hover:bg-stone-200 text-stone-600 hover:text-stone-900 font-extrabold rounded-xl border border-stone-200 text-xs transition flex items-center justify-center space-x-2 h-[38px]">
                 <i data-lucide="brain" class="w-3.5 h-3.5"></i>
                 <span>Quiz</span>
            </button>
        `;
    }

    const titleHTML = `<a href="javascript:void(0)" onclick="openStudyStudio(${video.id})" class="block font-bold text-sm text-stone-900 truncate hover:text-amber-700 transition" title="Open in Study Studio: ${escapeHtml(video.title)}">${escapeHtml(video.title)}</a>`;
    
    const stageBadgeHTML = isTemporaryVideo(video)
        ? `<span class="text-[9px] bg-amber-500/15 border border-amber-500/30 text-amber-900 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider flex items-center space-x-1" title="Preview mode: expires in ~24h unless imported"><i data-lucide="clock" class="w-3 h-3 text-amber-700"></i><span>24h Preview</span></span>`
        : (isPaused
            ? `<span class="text-[9px] bg-stone-100 border border-stone-200 text-stone-600 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider flex items-center space-x-1" title="SRS Review Intervals Paused"><i data-lucide="pause-circle" class="w-3 h-3 text-stone-500"></i><span>${isMastered ? 'Mastered' : `Stage ${srsStage}`} (Paused)</span></span>`
            : `<span class="text-[9px] bg-amber-100 border border-amber-200 text-amber-800 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">${isMastered ? 'Mastered' : `Stage ${srsStage}`}</span>`);

    
    const isWatchlist = video.is_watchlist === 1 || video.is_watchlist === true;

    const failedNoticeHTML = video.status === 'failed' ? `
        <div class="p-2.5 bg-red-50 border border-red-100 rounded-xl flex items-start space-x-2 text-xs text-red-700" title="${escapeHtml(video.status_error) || 'Unknown Error'}">
            <i data-lucide="alert-triangle" class="w-4 h-4 shrink-0 text-red-500 mt-0.5"></i>
            <div class="min-w-0 flex-1">
                <p class="font-semibold text-red-800 text-xs">Import Failed</p>
                <p class="text-[11px] text-red-600/90 break-words whitespace-normal leading-tight mt-0.5">${escapeHtml(video.status_error) || 'Unknown error occurred during processing.'}</p>
            </div>
        </div>
    ` : '';

    const validSummaryBullets = Array.isArray(video.summary) ? video.summary.filter(isRealSummaryBullet) : [];

    const isTemp = isTemporaryVideo(video);
    const hasTakeaways = validSummaryBullets.length > 0;
    const hasNotes = typeof video.custom_notes === 'string' && video.custom_notes.trim().length > 0;
    const hasDetails = !isTemp && (hasTakeaways || hasNotes);
    
    const detailsSectionHTML = hasDetails ? `
        <div class="mt-2 space-y-1">
            <button onclick="toggleVideoDetails(event, ${video.id})" class="flex items-center space-x-1.5 text-xs font-bold text-stone-500 hover:text-stone-700 transition">
                <i data-lucide="align-left" class="w-3.5 h-3.5 text-amber-600"></i>
                <span>${hasTakeaways && hasNotes ? 'AI Takeaways & Personal Notes' : (hasTakeaways ? 'AI Takeaways' : 'Personal Notes')}</span>
                <i data-lucide="chevron-down" id="details-chevron-${video.id}" class="w-3.5 h-3.5 text-stone-400 transition-transform"></i>
            </button>

            <div id="details-content-${video.id}" class="hidden space-y-2 pt-0.5 text-xs">
                ${hasTakeaways ? `
                <div class="space-y-1">
                    ${hasNotes ? '<h5 class="font-semibold text-stone-400 text-[10px] uppercase tracking-wider">Key Takeaways</h5>' : ''}
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

    const watchNotesButtonHTML = isNormalState ? `
        <button onclick="event.stopPropagation(); openStudyStudio(${video.id})" class="btn-primary w-full py-2 font-extrabold rounded-xl text-xs transition flex items-center justify-center space-x-2 min-h-[38px]" title="Watch the video and take notes side by side">
            <i data-lucide="book-open" class="w-3.5 h-3.5 shrink-0"></i>
            <span class="leading-tight">Watch &amp; Notes</span>
        </button>
    ` : `
        <button onclick="event.stopPropagation(); openStudyStudio(${video.id})" class="px-3 py-2 bg-stone-100 hover:bg-stone-200 text-stone-600 hover:text-stone-900 font-extrabold rounded-xl border border-stone-200 text-xs transition flex items-center justify-center space-x-2 min-h-[38px] shrink-0" title="Open Study Studio: watch the video and take notes side by side">
            <i data-lucide="book-open" class="w-3.5 h-3.5 shrink-0"></i>
            <span class="leading-tight">Watch &amp; Notes</span>
        </button>
    `;

    const bookmarkButtonHTML = isWatchlist ? `
        <button onclick="event.stopPropagation(); toggleWatchlist(${video.id})" class="p-2 bg-amber-50 hover:bg-amber-100 text-amber-600 hover:text-amber-700 rounded-xl border border-amber-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Remove from Study Queue">
            <i data-lucide="bookmark" class="w-4 h-4 fill-amber-500 text-amber-500"></i>
        </button>
    ` : '';

    const trailingButtonHTML = isTemp ? `
        <button onclick="event.stopPropagation(); discardPreviewVideo(${video.id})" class="p-2 bg-stone-100 hover:bg-red-100 text-stone-500 hover:text-red-700 rounded-xl border border-stone-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Discard Preview">
            <i data-lucide="x" class="w-4 h-4"></i>
        </button>
    ` : `
        <button onclick="toggleVideoMenu(event, ${video.id})" data-menuid="${video.id}" class="p-2 bg-stone-100 hover:bg-stone-200 text-stone-600 hover:text-stone-900 rounded-xl border border-stone-200 transition flex items-center justify-center h-[38px] w-[38px] shrink-0" title="Material Options">
            <i data-lucide="more-vertical" class="w-4 h-4"></i>
        </button>
    `;

    const actionRowHTML = isNormalState ? `
        <div class="flex-grow">
            ${watchNotesButtonHTML}
        </div>
        <div class="flex-grow">
            ${actionControlsHTML}
        </div>
        <div class="flex items-center space-x-2 shrink-0">
            ${bookmarkButtonHTML}
            ${trailingButtonHTML}
        </div>
    ` : `
        <div id="action-btn-container-${video.id}" class="flex-grow min-w-0">
            ${actionControlsHTML}
        </div>
        <div class="flex items-center space-x-2 shrink-0">
            ${video.status === 'processing' ? '' : watchNotesButtonHTML}
            ${bookmarkButtonHTML}
            ${trailingButtonHTML}
        </div>
    `;

    const actionRowMarginClass = hasDetails ? 'mt-2' : 'mt-3';

    return `
        <div id="video-card-${video.id}" class="bg-white border border-[#e7dfd3] rounded-2xl p-4 flex flex-col justify-between shadow-sm relative">
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

            ${failedNoticeHTML ? `<div class="mt-3">${failedNoticeHTML}</div>` : ''}
            ${detailsSectionHTML}

            <div class="flex items-center justify-between ${actionRowMarginClass} gap-2">
                ${actionRowHTML}
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
    closeContextMenuPortal('video-context-menu-portal');
}

function toggleVideoMenu(event, id) {
    if (event) event.stopPropagation();

    const btn = event ? event.currentTarget : document.querySelector(`[data-menuid="${id}"]`);

    const cardData = window._videoCardCache && window._videoCardCache[id];
    const isPaused = cardData ? cardData.is_paused : false;
    const isWatchlist = cardData ? cardData.is_watchlist : false;
    const isArchived = cardData ? cardData.is_archived : false;
    const isImported = !cardData || (cardData.status !== 'processing' && cardData.status !== 'failed');
    // Material imported before topic extraction existed has an empty concept_pool, and its
    // overlay would have nothing to show, so the entry is hidden rather than opening empty.
    const hasConceptPool = !!(cardData && cardData.has_concept_pool);

    const html = `<div class="py-1">
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

    toggleContextMenuPortal('video-context-menu-portal', id, btn, html, {
        extraClasses: 'w-56 border border-[#e7dfd3]',
        onMount: (portal) => {
            const focusBtn = portal.querySelector('[data-focus-video]');
            if (focusBtn) {
                focusBtn.addEventListener('click', () => {
                    closeVideoMenu();
                    openFocusModal(id);
                });
            }
        }
    });
}

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

    const confirmed = await showConfirm({
        title: "Discard Draft Preview?",
        message: promptMessage,
        confirmText: "Discard Draft",
        confirmClass: "bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-xs shadow-sm transition",
        icon: "trash-2"
    });

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
    const confirmed = await showConfirm({
        title: "Delete Material?",
        message: "Are you sure you want to permanently delete this video? All historical quiz data will be deleted.",
        confirmText: "Delete Material",
        confirmClass: "bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-xs shadow-sm transition",
        icon: "trash-2"
    });
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
        openOverlay('overlay-factcheck', closeFactCheckModal);

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
    
    const setEditRating = initEditVideoStars();
    if (setEditRating) setEditRating(parseInt(cardData ? (cardData.importance_rating || rating || 3) : (rating || 3)) || 3);
    
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
    
    openOverlay('overlay-edit-video', closeEditVideoModal);
}

function closeEditVideoModal() {
    document.getElementById('overlay-edit-video')?.classList.add('hidden');
    closeOverlay('overlay-edit-video');
}

function initEditVideoEvents() {
    const btnClose = document.getElementById('btn-close-edit-video');
    const form = document.getElementById('edit-video-form');

    if (btnClose) {
        btnClose.onclick = closeEditVideoModal;
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
                closeEditVideoModal();
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

    openOverlay('overlay-video-stats', closeVideoStatsModal);

    try {
        const stats = await fetchAPI(`/api/videos/${id}/stats`);
        
        if (stats.title) {
            document.getElementById('stats-video-title').textContent = stats.title;
        }
        
        if (stageEl) {
            stageEl.textContent = stats.mastered ? 'Mastered' : `Stage ${stats.srs_stage ?? 0}`;
        }
        
        if (reviewEl) {
            let isDue = false;
            if (!stats.next_review_at) {
                reviewEl.textContent = "Not scheduled";
            } else {
                const dtStr = typeof parseDate === 'function' ? parseDate(stats.next_review_at) : stats.next_review_at;
                const dt = new Date(dtStr);
                isDue = dt <= new Date();
                reviewEl.textContent = isDue ? "Due now" : dt.toLocaleString(undefined, {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                });
            }
            // Toggles only the emphasis. Reassigning .className here restated the
            // template's own text-xs font-semibold as a second copy, which had already
            // drifted: the markup said text-stone-400 and every branch here said
            // text-stone-500, so the color the template declares was never the one shown.
            reviewEl.classList.toggle('font-bold', isDue);
            reviewEl.classList.toggle('text-amber-400', isDue);
            reviewEl.classList.toggle('font-semibold', !isDue);
            reviewEl.classList.toggle('text-stone-500', !isDue);
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
                mastered: att.mastered,
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
                            <span class="text-[9px] bg-amber-100 border border-amber-200 text-amber-800 px-1.5 py-0.5 rounded font-bold uppercase tracking-wider">${session.mastered ? 'Mastered' : `Stage ${session.srs_stage ?? 0}`}</span>
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
    closeOverlay('overlay-video-stats');
}

function closeFactCheckModal() {
    const overlay = document.getElementById('overlay-factcheck');
    if (overlay) overlay.classList.add('hidden');
    closeOverlay('overlay-factcheck');
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
    // Only one studio session exists at a time. Reopening the video that is already in
    // the mini-player just brings it back up; opening a different one ends the current
    // session first, so its notes and position are saved under its own id and its
    // player stops instead of playing on alongside the new one.
    const activeOverlay = document.getElementById('overlay-study-studio');
    const activeMini = document.getElementById('studio-mini-player');
    const miniOpen = activeMini && !activeMini.classList.contains('hidden');
    const studioOpen = activeOverlay && !activeOverlay.classList.contains('hidden');
    if (miniOpen && Number(_currentStudioVideoId) === Number(id)) {
        restoreStudio();
        return;
    }
    if (miniOpen || studioOpen) closeStudyStudio();

    if (typeof stopActiveInlineTracker === 'function') stopActiveInlineTracker();
    if (typeof dismissCompletedImportTaskForVideo === 'function') dismissCompletedImportTaskForVideo(id);
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
    
    openOverlay('overlay-study-studio', closeStudyStudio);
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
                _currentStudioVideoCurrentTime = playerTime;
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
    // The immediate save below covers whatever the debounce was waiting on. Left pending,
    // it would fire after the next openStudyStudio and read that video's id.
    if (_studioNotesSaveTimeout) clearTimeout(_studioNotesSaveTimeout);
    _studioNotesSaveTimeout = null;
    saveStudioVideoPosition();
    saveStudioNotes(true);
    if (_studioPositionSaveInterval) clearInterval(_studioPositionSaveInterval);
    _currentStudioPlayer = null;
    _currentStudioVideoCurrentTime = 0;

    const overlay = document.getElementById('overlay-study-studio');
    if (overlay) overlay.classList.add('hidden');
    closeOverlay('overlay-study-studio');

    const ytWrapper = document.getElementById('studio-yt-wrapper');
    if (ytWrapper) ytWrapper.innerHTML = '';
    const miniVideo = document.getElementById('mini-player-video');
    if (miniVideo) miniVideo.innerHTML = '';
    const miniPlayer = document.getElementById('studio-mini-player');
    if (miniPlayer) miniPlayer.classList.add('hidden');
}

function getStudioCurrentTime() {
    let sec = _currentStudioVideoCurrentTime || 0;
    if (_currentStudioPlayer && typeof _currentStudioPlayer.getCurrentTime === 'function') {
        try {
            const t = _currentStudioPlayer.getCurrentTime();
            if (typeof t === 'number' && !isNaN(t) && t > 0) {
                sec = t;
                _currentStudioVideoCurrentTime = t;
            }
        } catch (e) {}
    }
    if (sec <= 0 && _currentStudioVideoId && window._videoCardCache && window._videoCardCache[_currentStudioVideoId]) {
        sec = parseFloat(window._videoCardCache[_currentStudioVideoId].last_position_seconds) || 0;
    }
    return sec;
}

// Re-parenting the YT iframe (minimize/restore) makes the browser reload it,
// which would otherwise snap playback back to the `start=` baked into the src
// when Study Studio was first opened. Reads the live position synchronously
// before the move, then forces a controlled reload at that position and
// rebinds the YT.Player.
function relocateStudioPlayer(iframe, targetContainer) {
    const resumeSec = Math.floor(getStudioCurrentTime());
    _currentStudioVideoCurrentTime = resumeSec;

    if (_currentStudioVideoId && window._videoCardCache && window._videoCardCache[_currentStudioVideoId]) {
        window._videoCardCache[_currentStudioVideoId].last_position_seconds = resumeSec;
    }

    try {
        const url = new URL(iframe.src);
        url.searchParams.set('start', resumeSec);
        url.searchParams.set('autoplay', '1');
        iframe.src = url.toString();
    } catch (e) {}

    targetContainer.appendChild(iframe);
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

    saveStudioNotes();
    relocateStudioPlayer(iframe, miniVideo);

    const miniTitle = document.getElementById('mini-player-title');
    const cardData = (window._videoCardCache && window._videoCardCache[_currentStudioVideoId]) || null;
    if (miniTitle) miniTitle.textContent = cardData ? cardData.title : 'Now Playing';

    if (overlay) overlay.classList.add('hidden');
    // The big overlay is gone but the session isn't closed - it continues as the floating
    // mini-player - so this unlocks scroll/Escape (closeOverlay) without running
    // closeStudyStudio's full teardown (stopping playback, clearing the save interval, etc.).
    closeOverlay('overlay-study-studio');
    miniPlayer.classList.remove('hidden');
    initMiniPlayerDrag();
}

function restoreStudio() {
    const iframe = document.getElementById('studio-yt-iframe');
    const ytWrapper = document.getElementById('studio-yt-wrapper');
    const miniPlayer = document.getElementById('studio-mini-player');

    if (iframe && ytWrapper) {
        relocateStudioPlayer(iframe, ytWrapper);
    }
    if (miniPlayer) miniPlayer.classList.add('hidden');
    openOverlay('overlay-study-studio', closeStudyStudio);
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
    // Callers assign the result to innerHTML, so if the sanitizer or parser failed to load
    // the note is shown as escaped plain text rather than passed through as markup.
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') return escapeHtml(text);
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
window.ensureYouTubeAPI = ensureYouTubeAPI;
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




