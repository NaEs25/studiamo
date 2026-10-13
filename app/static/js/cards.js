/**
 * Card editor: a sheet that shows, per SRS stage, which cards a quiz at the material's star
 * rating serves and which are paused, and lets the learner add, edit and remove cards.
 *
 * It reads and writes the same pool as the Learning Focus overlay (videos.js), through the same
 * endpoints, and it works on phones. Cards past the star rating's count are shown greyed and are
 * never deleted by a rating change. The learner's own cards are plain front and back; the AI's
 * multiple-choice cards have their four options editable.
 */

let cardsState = null;

const CARDS_FIELD_CLASS = 'w-full bg-[#fcfaf6] border border-[#e7dfd3] rounded-lg px-3 py-2 text-sm text-stone-900 focus:outline-none focus:border-amber-500';
const CARDS_STAGE_LABELS = ['Immediate', '1 day', '3 days', '7 days', '14-30 days'];

function cardsAllCards() {
    const all = new Map();
    cardsState.stages.forEach(s => s.topics.forEach(t => t.questions.forEach(q => all.set(q.id, { ...q, stage: s.stage, topic: t.topic }))));
    return all;
}

function cardsStageData(stageIndex) {
    return cardsState.stages.find(s => s.stage === stageIndex) || { stage: stageIndex, topics: [], served: [], filled: 0, total_questions: 0 };
}

// The stage's own cards, in the order a quiz serves them: first the ones in rotation, then the paused rest.
function cardsForStage(stageIndex) {
    const stage = cardsStageData(stageIndex);
    const all = cardsAllCards();
    const own = [];
    stage.topics.forEach(t => t.questions.forEach(q => own.push(all.get(q.id))));
    const servedOrder = new Map(stage.served.map((id, i) => [id, i]));
    const inRotation = own.filter(c => servedOrder.has(c.id)).sort((a, b) => servedOrder.get(a.id) - servedOrder.get(b.id));
    const paused = own.filter(c => !servedOrder.has(c.id));
    const borrowed = stage.served.map(id => all.get(id)).filter(c => c && c.stage !== stageIndex);
    return { inRotation, paused, borrowed };
}

function cardsKindLabel(c) {
    const kind = c.options ? 'Multiple choice' : (c.origin === 'human' ? 'Flashcard' : 'Typed answer');
    const who = c.origin === 'human' ? 'you' : (c.edited ? 'edited' : 'AI');
    return `${kind}, ${who}`;
}

function cardsStars(n) {
    let html = '';
    for (let i = 1; i <= 5; i++) {
        html += `<i data-lucide="star" class="w-3 h-3 ${i <= n ? 'fill-amber-500 text-amber-500' : 'text-stone-300'}"></i>`;
    }
    return `<span class="inline-flex">${html}</span>`;
}

function cardsRowHTML(c, { paused = false, readOnly = false } = {}) {
    const editing = cardsState.editor && cardsState.editor.kind === 'edit' && cardsState.editor.cardId === c.id;
    if (editing) return cardsEditFormHTML(c);
    const busy = cardsState.busy;
    const controls = readOnly ? `<span class="text-[10px] text-stone-400 shrink-0">stage ${c.stage}</span>` : `
        <button type="button" data-cards-edit="${escapeHtml(c.id)}" ${busy ? 'disabled' : ''} class="p-1.5 text-stone-500 hover:text-stone-900 hover:bg-stone-100 rounded-lg transition disabled:opacity-40" aria-label="Edit this card"><i data-lucide="pencil" class="w-4 h-4"></i></button>
        <button type="button" data-cards-remove="${escapeHtml(c.id)}" ${busy ? 'disabled' : ''} class="p-1.5 text-stone-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition disabled:opacity-40" aria-label="Remove this card"><i data-lucide="x" class="w-4 h-4"></i></button>`;
    return `
        <div class="flex items-center gap-2 border rounded-xl px-3 py-2.5 ${paused ? 'bg-stone-50 border-dashed border-stone-300 opacity-60' : 'bg-white border-stone-200 shadow-sm'}">
            <div class="min-w-0 flex-1">
                <p class="text-sm font-bold text-stone-900 break-words">${escapeHtml(c.question)}</p>
                <p class="text-[11px] text-stone-500">${escapeHtml(cardsKindLabel(c))}</p>
            </div>
            ${controls}
        </div>`;
}

function cardsEditFormHTML(c) {
    const d = cardsState.editor.draft;
    const busy = cardsState.busy ? 'disabled' : '';
    let body;
    if (c.options) {
        body = `<textarea data-cards-field="question" rows="2" maxlength="500" class="${CARDS_FIELD_CLASS}" placeholder="Question">${escapeHtml(d.question)}</textarea>`
            + d.options.map((o, i) => `
                <label class="flex items-center gap-2">
                    <input type="radio" name="cards-correct" value="${i}" data-cards-correct ${d.correct_index === i ? 'checked' : ''} class="text-amber-600 focus:ring-amber-500">
                    <input type="text" data-cards-option="${i}" maxlength="300" value="${escapeHtml(o)}" class="${CARDS_FIELD_CLASS}" placeholder="Option ${i + 1}">
                </label>`).join('')
            + '<p class="text-[11px] text-stone-500">Mark the correct option with the round button.</p>';
    } else {
        body = `<textarea data-cards-field="question" rows="2" maxlength="500" class="${CARDS_FIELD_CLASS}" placeholder="Front">${escapeHtml(d.question)}</textarea>
                <textarea data-cards-field="answer" rows="3" maxlength="1000" class="${CARDS_FIELD_CLASS}" placeholder="Back">${escapeHtml(d.answer)}</textarea>`;
    }
    return `
        <div class="border border-amber-300 bg-amber-50/40 rounded-xl p-3 space-y-2">
            ${body}
            <div class="flex items-center gap-2">
                <button type="button" data-cards-save ${busy} class="btn-primary px-4 py-2 rounded-xl text-xs font-extrabold disabled:opacity-60">Save</button>
                <button type="button" data-cards-cancel ${busy} class="px-3 py-2 rounded-xl text-xs font-bold text-stone-600 hover:bg-stone-100">Cancel</button>
            </div>
        </div>`;
}

function cardsAddFormHTML(stageIndex) {
    const ed = cardsState.editor;
    if (ed && ed.kind === 'add') {
        const d = ed.draft;
        const busy = cardsState.busy ? 'disabled' : '';
        return `
            <div class="border border-amber-300 bg-amber-50/40 rounded-xl p-3 space-y-2">
                <p class="text-xs font-extrabold text-stone-800">New card, stage ${stageIndex}</p>
                <textarea data-cards-field="question" rows="2" maxlength="500" class="${CARDS_FIELD_CLASS}" placeholder="Front: the question">${escapeHtml(d.question)}</textarea>
                <textarea data-cards-field="answer" rows="3" maxlength="1000" class="${CARDS_FIELD_CLASS}" placeholder="Back: the answer">${escapeHtml(d.answer)}</textarea>
                <input type="text" data-cards-field="topic" maxlength="60" value="${escapeHtml(d.topic)}" class="${CARDS_FIELD_CLASS}" placeholder="Topic (optional)">
                <div class="flex items-center gap-2">
                    <button type="button" data-cards-save ${busy} class="btn-primary px-4 py-2 rounded-xl text-xs font-extrabold disabled:opacity-60">Add card</button>
                    <button type="button" data-cards-cancel ${busy} class="px-3 py-2 rounded-xl text-xs font-bold text-stone-600 hover:bg-stone-100">Cancel</button>
                </div>
            </div>`;
    }
    return `<button type="button" data-cards-add class="w-full py-2.5 border border-dashed border-amber-500/40 hover:bg-amber-500/5 text-amber-700 font-bold rounded-xl text-xs flex items-center justify-center gap-1.5 transition"><i data-lucide="plus" class="w-3.5 h-3.5"></i>Add card to stage ${stageIndex}</button>`;
}

function renderCardsSheet() {
    if (!cardsState) return;
    const target = cardsState.targetCount || 0;
    const stage = cardsState.activeStage;

    const pills = [0, 1, 2, 3, 4].map(s => {
        const count = cardsStageData(s).total_questions || 0;
        const active = s === stage;
        const short = target > 0 && count < target;
        const cls = active ? 'bg-amber-100 border-amber-300 text-amber-900 font-extrabold'
            : (short ? 'bg-red-50 border-red-200 text-red-700 font-bold' : 'bg-white border-stone-200 text-stone-700 font-bold');
        return `<button type="button" data-cards-stage="${s}" aria-pressed="${active}" title="${escapeHtml(CARDS_STAGE_LABELS[s])}" class="flex-1 py-2 rounded-xl border text-xs ${cls}">${s}<span class="font-normal opacity-75"> · ${count}</span></button>`;
    }).join('');

    const { inRotation, paused, borrowed } = cardsForStage(stage);
    const total = inRotation.length + paused.length;
    const rating = cardsState.rating || 3;
    let status;
    if (total === 0) {
        status = 'This stage has no cards of its own yet. Quizzes at this stage borrow cards from the other stages until you add some.';
    } else if (borrowed.length > 0) {
        status = `This stage has ${total} ${total === 1 ? 'card' : 'cards'} but a quiz at ${rating} stars asks for ${target}, so ${borrowed.length} ${borrowed.length === 1 ? 'is' : 'are'} borrowed at random from other stages. Add cards here to avoid that.`;
    } else if (paused.length > 0) {
        status = `At ${rating} stars this stage reviews ${inRotation.length} of its ${total} cards. ${paused.length} ${paused.length === 1 ? 'is' : 'are'} paused. Your own cards always go first.`;
    } else {
        status = `At ${rating} stars this stage reviews all ${total} of its cards. Your own cards always go first.`;
    }

    const list = document.getElementById('cards-list');
    list.innerHTML = `
        <p class="text-[11px] font-bold tracking-wider uppercase text-stone-600">Stage (cards in this stage)</p>
        <div class="flex gap-1.5">${pills}</div>
        <div class="text-xs font-semibold rounded-xl px-3 py-2 border bg-amber-50 border-amber-200 text-amber-900">${escapeHtml(status)}</div>
        ${inRotation.map(c => cardsRowHTML(c)).join('')}
        ${paused.length ? `<p class="text-[11px] font-bold tracking-wider uppercase text-stone-500 pt-1">Paused at ${rating} stars, back at a higher rating</p>${paused.map(c => cardsRowHTML(c, { paused: true })).join('')}` : ''}
        ${borrowed.length ? `<p class="text-[11px] font-bold tracking-wider uppercase text-stone-500 pt-1">Borrowed from other stages</p>${borrowed.map(c => cardsRowHTML(c, { paused: false, readOnly: true })).join('')}` : ''}
        ${cardsAddFormHTML(stage)}`;

    document.getElementById('cards-subtitle').innerHTML = `${escapeHtml(cardsState.title || '')} ${cardsStars(rating)}`;
    if (typeof renderIcons === 'function') renderIcons();
}

function closeCardsSheet() {
    document.getElementById('overlay-cards')?.classList.add('hidden');
    closeOverlay('overlay-cards');
    cardsState = null;
}

async function openCardsSheet(videoId) {
    try {
        const data = await fetchAPI(`/api/videos/${videoId}/concept-pool`);
        const cached = (window._videoCardCache && window._videoCardCache[videoId]) || {};
        cardsState = {
            videoId,
            title: data.title || cached.title || '',
            rating: cached.importance_rating || 3,
            targetCount: data.target_count,
            stages: data.stages || [],
            activeStage: data.current_stage || 0,
            editor: null,
            busy: false,
            pendingRemove: null,
        };
        document.getElementById('overlay-cards').classList.remove('hidden');
        openOverlay('overlay-cards', closeCardsSheet);
        renderCardsSheet();
    } catch (e) {
        showToast(e.detail || e.message || 'Could not open the cards.', 'failed', 4000);
    }
}
window.openCardsSheet = openCardsSheet;

async function cardsRequest(request) {
    const state = cardsState;
    if (!state || state.busy) return false;
    state.busy = true;
    renderCardsSheet();
    let ok = false;
    try {
        const data = await request();
        if (cardsState === state) {
            state.stages = data.stages || state.stages;
            state.targetCount = data.target_count ?? state.targetCount;
            ok = true;
        }
    } catch (e) {
        showToast(e.detail || e.message || 'Could not update the cards.', 'failed', 4000);
    }
    if (cardsState === state) {
        state.busy = false;
        renderCardsSheet();
    }
    return ok;
}

function cardsReadDraft() {
    const ed = cardsState.editor;
    const q = (name) => document.querySelector(`#cards-list [data-cards-field="${name}"]`);
    if (q('question')) ed.draft.question = q('question').value;
    if (q('answer')) ed.draft.answer = q('answer').value;
    if (q('topic')) ed.draft.topic = q('topic').value;
    if (ed.draft.options) {
        ed.draft.options = ed.draft.options.map((_, i) => document.querySelector(`#cards-list [data-cards-option="${i}"]`)?.value ?? '');
        const picked = document.querySelector('#cards-list [data-cards-correct]:checked');
        if (picked) ed.draft.correct_index = Number(picked.value);
    }
}

async function cardsSave() {
    const ed = cardsState && cardsState.editor;
    if (!ed || cardsState.busy) return;
    cardsReadDraft();
    const d = ed.draft;
    const base = `/api/videos/${cardsState.videoId}/cards`;
    if (ed.kind === 'add') {
        if (!d.question.trim() || !d.answer.trim()) { showToast('A card needs a front and a back.', 'failed', 3000); return; }
        const body = new FormData();
        body.append('stage', String(cardsState.activeStage));
        body.append('topic', d.topic || '');
        body.append('question', d.question);
        body.append('answer', d.answer);
        if (await cardsRequest(() => fetchAPI(base, { method: 'POST', body }))) { cardsState.editor = null; renderCardsSheet(); }
        return;
    }
    const body = new FormData();
    body.append('question', d.question);
    if (d.options) {
        body.append('options', JSON.stringify(d.options));
        body.append('correct_index', String(d.correct_index));
    } else {
        body.append('answer', d.answer);
    }
    if (await cardsRequest(() => fetchAPI(`${base}/${encodeURIComponent(ed.cardId)}`, { method: 'PATCH', body }))) {
        cardsState.editor = null;
        renderCardsSheet();
    }
}

function cardsArmRemove(btn) {
    cardsDisarmRemove();
    cardsState.pendingRemove = btn.dataset.cardsRemove;
    btn.dataset.idleHtml = btn.innerHTML;
    btn.innerHTML = '<span class="text-[10px] font-bold px-1">Remove?</span>';
    btn.classList.add('text-red-600', 'bg-red-50');
    cardsState.removeTimer = setTimeout(cardsDisarmRemove, 4000);
}

function cardsDisarmRemove() {
    if (!cardsState) return;
    clearTimeout(cardsState.removeTimer);
    cardsState.pendingRemove = null;
    document.querySelectorAll('#cards-list [data-cards-remove]').forEach(b => {
        if (b.dataset.idleHtml) { b.innerHTML = b.dataset.idleHtml; delete b.dataset.idleHtml; }
        b.classList.remove('text-red-600', 'bg-red-50');
    });
}

function initCardsSheet() {
    const sheet = document.getElementById('overlay-cards');
    if (!sheet || sheet.dataset.bound) return;
    sheet.dataset.bound = '1';
    document.getElementById('btn-cards-close')?.addEventListener('click', closeCardsSheet);
    document.getElementById('btn-cards-focus')?.addEventListener('click', () => {
        const id = cardsState && cardsState.videoId;
        closeCardsSheet();
        if (id && typeof openFocusModal === 'function') openFocusModal(id);
    });
    sheet.addEventListener('click', (e) => {
        if (!cardsState) return;
        const remove = e.target.closest('[data-cards-remove]');
        if (cardsState.pendingRemove && (!remove || remove.dataset.cardsRemove !== cardsState.pendingRemove)) cardsDisarmRemove();
        const stage = e.target.closest('[data-cards-stage]');
        if (stage) { cardsState.activeStage = Number(stage.dataset.cardsStage); cardsState.editor = null; renderCardsSheet(); return; }
        if (remove && !remove.disabled) {
            if (cardsState.pendingRemove === remove.dataset.cardsRemove) {
                const id = remove.dataset.cardsRemove;
                cardsDisarmRemove();
                cardsRequest(() => fetchAPI(`/api/videos/${cardsState.videoId}/cards/${encodeURIComponent(id)}`, { method: 'DELETE' }));
            } else {
                cardsArmRemove(remove);
            }
            return;
        }
        const edit = e.target.closest('[data-cards-edit]');
        if (edit && !edit.disabled) {
            const c = cardsAllCards().get(edit.dataset.cardsEdit);
            if (!c) return;
            cardsState.editor = {
                kind: 'edit', cardId: c.id,
                draft: { question: c.question, answer: c.answer, options: c.options ? [...c.options] : null, correct_index: c.correct_index ?? 0 },
            };
            renderCardsSheet();
            return;
        }
        if (e.target.closest('[data-cards-add]')) {
            cardsState.editor = { kind: 'add', draft: { question: '', answer: '', topic: '' } };
            renderCardsSheet();
            document.querySelector('#cards-list [data-cards-field="question"]')?.focus();
            return;
        }
        if (e.target.closest('[data-cards-save]')) { cardsSave(); return; }
        if (e.target.closest('[data-cards-cancel]')) { if (!cardsState.busy) { cardsState.editor = null; renderCardsSheet(); } }
    });
}
document.addEventListener('DOMContentLoaded', initCardsSheet);
