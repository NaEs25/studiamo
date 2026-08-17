// --- Studiamo Active Recall Quiz Module ---

// --- TTS (Text-to-Speech) helpers ---
let activeTtsAudio = null;
let activeTtsButton = null;

// Records whether the AI conceptual check found the last guess correct, so
// Enter/Space on the back card can confirm the AI's suggested grade.
let lastVerdictIsCorrect = null;

function setTtsButtonPlaying(btn, playing) {
    if (!btn) return;
    const idleIcon = btn.querySelector('.tts-icon-idle');
    const playingIcon = btn.querySelector('.tts-icon-playing');
    const label = btn.querySelector('.tts-label');
    if (idleIcon) idleIcon.classList.toggle('hidden', playing);
    if (playingIcon) playingIcon.classList.toggle('hidden', !playing);
    if (label) label.textContent = playing ? 'Pause' : 'Read';
    btn.setAttribute('aria-label', playing ? 'Pause audio' : (btn.dataset.readLabel || 'Read aloud'));
}

function finishTtsButton(btn) {
    if (btn && activeTtsButton === btn) {
        setTtsButtonPlaying(btn, false);
        activeTtsButton = null;
    }
}

function stopCurrentSpeech() {
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    if (activeTtsAudio) {
        try {
            activeTtsAudio.pause();
            activeTtsAudio.currentTime = 0;
        } catch (e) {}
        activeTtsAudio = null;
    }
    if (activeTtsButton) {
        setTtsButtonPlaying(activeTtsButton, false);
        activeTtsButton = null;
    }
}

function fallbackBrowserSpeak(text, speed, btn = null) {
    if (!('speechSynthesis' in window)) {
        finishTtsButton(btn);
        return;
    }
    const utterance = new SpeechSynthesisUtterance(text.trim());
    utterance.rate = isNaN(speed) ? 1.0 : speed;
    utterance.pitch = 1.0;
    utterance.lang = 'en-US';
    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(v => v.lang === 'en-US' && /male|guy|david|mark|alex/i.test(v.name))
        || voices.find(v => v.lang === 'en-US')
        || voices.find(v => v.lang.startsWith('en'));
    if (preferredVoice) utterance.voice = preferredVoice;
    utterance.onend = () => finishTtsButton(btn);
    utterance.onerror = () => finishTtsButton(btn);
    window.speechSynthesis.speak(utterance);
}

async function speakText(text, btn = null) {
    if (!text || !text.trim()) return;
    stopCurrentSpeech();

    if (btn) {
        activeTtsButton = btn;
        setTtsButtonPlaying(btn, true);
    }

    const engine = localStorage.getItem('studiamo_voice_engine') || 'browser';
    const speed = parseFloat(localStorage.getItem('studiamo_voice_speed') || '1.25');
    const cleanText = text.trim();

    if (engine === 'gemini') {
        try {
            const formData = new FormData();
            formData.append('text', cleanText);
            formData.append('speed', speed);
            const res = await fetchAPI('/api/tts', {
                method: 'POST',
                body: formData
            });
            const audioSrc = res && (res.audio_data || res.audio_url);
            if (audioSrc) {
                activeTtsAudio = new Audio(audioSrc);
                activeTtsAudio.onended = () => finishTtsButton(btn);
                activeTtsAudio.onerror = () => finishTtsButton(btn);
                await activeTtsAudio.play();
                return;
            }
        } catch (e) {
            console.warn("Edge TTS failed, falling back to browser voice:", e);
        }
    }

    fallbackBrowserSpeak(cleanText, speed, btn);
}

async function startQuiz(quizId, videoId = null, level = 3) {
    console.log("startQuiz invoked:", { quizId, videoId, level });
    if (!quizId || quizId === 'null' || quizId === 'undefined' || quizId === 0 || quizId === '0') {
        if (videoId && videoId !== 'null' && videoId !== 'undefined') {
            return triggerStudy(videoId, level);
        }
        if (typeof showToast === 'function') {
            showToast("Quiz ID is unavailable.", "failed");
        } else {
            alert("Quiz ID is unavailable.");
        }
        return;
    }

    // If a star-rating change on this video is still syncing in the background
    // (see changeVideoRating in videos.js), wait for it first. Fetching the quiz
    // while that sync was still in flight used to return the pre-change question
    // count, only a second open (after the sync had finished) showed the update.
    if (videoId && videoId !== 'null' && videoId !== 'undefined' && window._pendingRatingSync && window._pendingRatingSync[videoId]) {
        try {
            await window._pendingRatingSync[videoId];
        } catch (e) {
            // Sync failure is already surfaced by changeVideoRating's own toast.
        }
    }

    let quizLoadTimer = setTimeout(() => {
        if (typeof showToast === 'function') {
            showToast('Loading active recall session...', 'loading', 0);
        }
    }, 300);

    try {
        activeQuizSession = await fetchAPI(`/api/quiz/${quizId}`);
        clearTimeout(quizLoadTimer);
        if (typeof hideToast === 'function') hideToast();

        if (!activeQuizSession || !activeQuizSession.questions || activeQuizSession.questions.length === 0) {
            if (videoId && videoId !== 'null' && videoId !== 'undefined') {
                return triggerStudy(videoId, level);
            }
        }
        activeQuizSession.id = quizId;
        
        const username = typeof activeUsername !== 'undefined' ? activeUsername : 'default';
        const progressKey = `quiz-progress-${username}-${quizId}`;
        const savedIndex = localStorage.getItem(progressKey);
        currentQuestionIndex = 0;
        
        let resumeIdx = 0;
        if (activeQuizSession.in_progress_index !== undefined && activeQuizSession.in_progress_index !== null && activeQuizSession.in_progress_index > 0) {
            resumeIdx = parseInt(activeQuizSession.in_progress_index, 10);
        } else if (savedIndex) {
            resumeIdx = parseInt(savedIndex, 10);
        }
        
        if (resumeIdx > 0 && resumeIdx < activeQuizSession.questions.length) {
            currentQuestionIndex = resumeIdx;
        }
        
        const overlay = document.getElementById('overlay-quiz');
        if (overlay) {
            overlay.classList.remove('hidden');
            overlay.style.display = 'flex';
        }

        const titleEl = document.getElementById('quiz-source-title');
        const labelEl = document.getElementById('quiz-source-label');

        if (titleEl) {
            if (activeQuizSession.quiz_type === 'video') {
                titleEl.textContent = activeQuizSession.questions.length > 0 ? (activeQuizSession.video_title || 'Video Quiz') : 'Active recall session';
            } else {
                titleEl.textContent = 'Active recall session';
            }
        }
        if (labelEl) {
            const isYoutubeVideo = activeQuizSession.video_filename && !activeQuizSession.video_filename.startsWith('doc_');
            let fallbackLabel = 'Goal practice session';
            if (activeQuizSession.quiz_type === 'video') {
                fallbackLabel = isYoutubeVideo ? 'YouTube Video Material' : 'Document Material';
            }
            labelEl.textContent = activeQuizSession.goal_title || fallbackLabel;
        }

        const rewatch = document.getElementById('quiz-rewatch-link');
        if (rewatch) {
            if (activeQuizSession.video_filename && !activeQuizSession.video_filename.startsWith('doc_')) {
                rewatch.href = `https://youtube.com/watch?v=${activeQuizSession.video_filename}`;
                rewatch.classList.remove('hidden');
            } else {
                rewatch.classList.add('hidden');
            }
        }
        
        // Auto-check SRS progress for due quizzes, auto-uncheck for premature reviews
        const progressCheckbox = document.getElementById('quiz-progress-srs-checkbox');
        if (progressCheckbox) {
            let isDue = true;
            if (activeQuizSession && activeQuizSession.next_review_at) {
                const reviewDate = typeof parseDate === 'function' ? parseDate(activeQuizSession.next_review_at) : new Date(activeQuizSession.next_review_at);
                const now = new Date();
                if (reviewDate && reviewDate > now) {
                    isDue = false;
                }
            }
            progressCheckbox.checked = isDue;
        }

        // Auto-read Aloud never carries over between quiz sessions: leaving it
        // checked after closing a quiz would silently blast audio next time.
        const autoTtsToggle = document.getElementById('quiz-auto-tts-toggle');
        if (autoTtsToggle) autoTtsToggle.checked = false;

        renderQuizQuestion();
    } catch (e) {
        clearTimeout(quizLoadTimer);
        if (typeof hideToast === 'function') hideToast();
        console.error("Quiz retrieval error:", e);
        const msg = e?.message || String(e);
        if (videoId && videoId !== 'null' && videoId !== 'undefined') {
            // Only fall back to triggerStudy if NOT a transcript issue (422)
            if (!msg.includes('transcript') && !msg.includes('rate-limit')) {
                return triggerStudy(videoId, level);
            }
        }
        // Show a friendly non-blocking toast
        if (typeof showToast === 'function') {
            showToast(msg.includes('transcript') ? 'No transcript: re-import to enable Study.' : ('Could not load quiz: ' + msg), 'failed', 4000);
        }
        const toastEl = document.getElementById('global-toast') || document.getElementById('toast');
        if (toastEl) {
            toastEl.textContent = msg.includes('transcript')
                ? 'No transcript: re-import the video to enable Study.'
                : ('Could not load quiz: ' + msg);
            toastEl.classList.remove('hidden', 'opacity-0');
            setTimeout(() => toastEl.classList.add('opacity-0'), 5000);
        } else {
            alert(msg.includes('transcript')
                ? 'This video has no transcript. Please re-import the video to enable quizzes.'
                : ('Could not load quiz: ' + msg));
        }
    }
}

function renderQuizQuestion() {
    stopCurrentSpeech();
    if (!activeQuizSession || !activeQuizSession.questions || activeQuizSession.questions.length === 0) {
        alert("This quiz doesn't contain any active recall questions.");
        closeQuizOverlay();
        return;
    }
    
    window._lastFeedback = "";
    window._lastExplanation = "";
    lastVerdictIsCorrect = null;

    if (activeQuizSession && activeQuizSession.id) {
        const progressKey = `quiz-progress-${activeUsername}-${activeQuizSession.id}`;
        localStorage.setItem(progressKey, currentQuestionIndex);
    }
    
    const questions = activeQuizSession.questions;
    const currentQ = questions[currentQuestionIndex];
    let qText = "Question text not available.";
    let aText = "Answer not available.";
    let expText = "";

    if (typeof currentQ === 'string') {
        qText = currentQ;
    } else if (typeof currentQ === 'object' && currentQ !== null) {
        qText = currentQ.question || currentQ.Question || currentQ.q || currentQ.prompt || currentQ.text || currentQ.title || "Question text not available.";
        aText = currentQ.answer || currentQ.Answer || currentQ.a || currentQ.correct_answer || currentQ.solution || "Answer not available.";
        expText = currentQ.explanation || currentQ.Explanation || currentQ.exp || currentQ.hint || "";
    }

    const guessInput = document.getElementById('quiz-guess-input');
    if (guessInput) guessInput.value = '';
    
    const frontCard = document.getElementById('quiz-card-front');
    const backCard = document.getElementById('quiz-card-back');
    if (frontCard) frontCard.classList.remove('hidden');
    if (backCard) backCard.classList.add('hidden');
    
    const qEl = document.getElementById('quiz-question-text');
    const aEl = document.getElementById('quiz-correct-answer');
    const expEl = document.getElementById('quiz-explanation-text');
    
    if (qEl) qEl.textContent = qText;
    if (aEl) aEl.textContent = aText;
    if (expEl) expEl.textContent = expText;
    
    const progressPct = ((currentQuestionIndex + 1) / questions.length) * 100;
    const progressBar = document.getElementById('quiz-progress-bar');
    const qNumEl = document.getElementById('quiz-question-number');
    const pctEl = document.getElementById('quiz-completion-pct');
    
    if (progressBar) progressBar.style.width = `${progressPct}%`;
    if (qNumEl) qNumEl.textContent = `Question ${currentQuestionIndex + 1} of ${questions.length}`;
    if (pctEl) pctEl.textContent = `${Math.round(progressPct)}% Done`;

    // Auto-read the question aloud if toggle is enabled
    const autoTts = document.getElementById('quiz-auto-tts-toggle');
    if (autoTts && autoTts.checked) {
        // Small delay so text is rendered before speaking
        setTimeout(() => speakText(qText, document.getElementById('btn-tts-question')), 300);
    }
}

function closeQuizOverlay() {
    stopCurrentSpeech();
    const overlay = document.getElementById('overlay-quiz');
    if (overlay) {
        overlay.classList.add('hidden');
        overlay.style.display = 'none';
    }
    activeQuizSession = null;
    if (typeof loadDashboard === 'function') loadDashboard();
    if (typeof loadGoals === 'function') loadGoals();
}

async function gradeQuestion(grade) {
    try {
        const questions = activeQuizSession.questions;
        const currentQ = questions[currentQuestionIndex];
        const guessInput = document.getElementById('quiz-guess-input');
        const guess = guessInput ? guessInput.value : "";
        
        const progressCheckbox = document.getElementById('quiz-progress-srs-checkbox');
        const progressSrs = progressCheckbox ? progressCheckbox.checked : true;
        
        const isFinalQuestion = (currentQuestionIndex === questions.length - 1);
        
        const formData = new FormData();
        formData.append('grade', grade);
        formData.append('question_index', currentQuestionIndex);
        formData.append('question', typeof currentQ === 'string' ? currentQ : (currentQ.question || JSON.stringify(currentQ)));
        formData.append('given_answer', guess);
        formData.append('correct_answer', currentQ.answer || "");
        formData.append('progress_srs', progressSrs);
        formData.append('is_final_question', isFinalQuestion);
        
        const feedbackToSend = window._lastFeedback || (guess ? "" : "Flipped card without guessing.");
        const explanationToSend = window._lastExplanation || currentQ.explanation || "";
        formData.append('feedback', feedbackToSend);
        formData.append('explanation', explanationToSend);
        
        const res = await fetchAPI(`/api/quiz/${activeQuizSession.id}/grade`, {
            method: 'POST',
            body: formData
        });
        
        if (res.leveled_up) {
            if (typeof showToast === 'function') {
                showToast(`Level Up! You reached Level ${res.level}!`, 'saved', 4000);
            } else {
                alert(`Level Up!\nCongratulations! You have reached Level ${res.level}!`);
            }
        }
        
        currentQuestionIndex++;
        const progressKey = `quiz-progress-${activeUsername}-${activeQuizSession.id}`;
        if (currentQuestionIndex >= questions.length) {
            localStorage.removeItem(progressKey);
            if (typeof showToast === 'function') {
                showToast("Quiz Session Complete! Great job reviewing!", 'saved', 4000);
            } else {
                alert("Quiz Session Complete!\nGreat job reviewing your study materials!");
            }
            closeQuizOverlay();
        } else {
            localStorage.setItem(progressKey, currentQuestionIndex);
            renderQuizQuestion();
        }
    } catch (e) {
        console.error("Error in gradeQuestion:", e);
        if (typeof showToast === 'function') {
            showToast("Error grading question: " + e.message, "failed");
        } else {
            alert("Error grading question: " + e.message);
        }
        if (typeof hideLoader === 'function') hideLoader();
    }
}

async function rescheduleQuiz(quizId) {
    try {
        const formData = new FormData();
        formData.append('days', 1);
        await fetchAPI(`/api/quiz/${quizId}/reschedule`, { method: 'POST', body: formData });
        if (typeof showToast === 'function') {
            showToast('Rescheduled for tomorrow', 'info', 2500);
        }
        if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
        console.error("Reschedule failed:", e);
        if (typeof showToast === 'function') {
            showToast('Reschedule failed', 'failed', 3000);
        }
    }
}

function initQuizEvents() {
    const btnShow = document.getElementById('btn-show-answer');
    const verdictBox = document.getElementById('quiz-ai-verdict-box');
    const feedbackEl = document.getElementById('quiz-ai-feedback');
    const verdictLabel = document.getElementById('quiz-ai-verdict-label');
    const btnForgot = document.getElementById('btn-grade-forgot');
    const btnRemembered = document.getElementById('btn-grade-remembered');
    const btnClose = document.getElementById('btn-close-quiz');
    const btnQuit = document.getElementById('btn-quit-quiz');

    // Wire up Read buttons. Clicking a button that is already reading pauses it;
    // otherwise it starts reading and the button flips to a "Pause" state.
    const btnTtsQuestion = document.getElementById('btn-tts-question');
    const btnTtsAnswer = document.getElementById('btn-tts-answer');
    const btnTtsFeedback = document.getElementById('btn-tts-feedback');
    const btnTtsExplanation = document.getElementById('btn-tts-explanation');

    function wireReadButton(btn, getText) {
        if (!btn) return;
        btn.dataset.readLabel = btn.getAttribute('aria-label') || 'Read aloud';
        btn.addEventListener('click', () => {
            if (activeTtsButton === btn) {
                stopCurrentSpeech();
                return;
            }
            const text = getText();
            if (text) speakText(text, btn);
        });
    }

    wireReadButton(btnTtsQuestion, () => {
        const el = document.getElementById('quiz-question-text');
        return el ? el.textContent : '';
    });
    wireReadButton(btnTtsAnswer, () => {
        const el = document.getElementById('quiz-correct-answer');
        return el ? el.textContent : '';
    });
    wireReadButton(btnTtsFeedback, () => {
        const el = document.getElementById('quiz-ai-feedback');
        return el ? (el.innerText || el.textContent) : '';
    });
    wireReadButton(btnTtsExplanation, () => {
        const el = document.getElementById('quiz-explanation-text');
        return el ? el.textContent : '';
    });

    if (btnShow) {
        btnShow.addEventListener('click', async () => {
            const guessInput = document.getElementById('quiz-guess-input');
            const guess = guessInput ? guessInput.value.trim() : '';
            
            const originalText = btnShow.textContent;
            btnShow.disabled = true;
            btnShow.textContent = "Verifying guess conceptually...";
            
            if (verdictBox) verdictBox.classList.add('hidden');
            if (feedbackEl) feedbackEl.innerHTML = '';
            
            if (btnForgot) btnForgot.className = "py-3 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 font-bold rounded-2xl transition flex items-center justify-center space-x-1.5";
            if (btnRemembered) btnRemembered.className = "py-3 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 font-bold rounded-2xl transition flex items-center justify-center space-x-1.5";
            
            try {
                const formData = new FormData();
                formData.append('quiz_id', activeQuizSession.id);
                formData.append('question_index', currentQuestionIndex);
                formData.append('user_guess', guess);
                
                const verification = await fetchAPI('/api/quiz/verify-guess', {
                    method: 'POST',
                    body: formData
                });
                
                window._lastFeedback = verification.feedback;
                const currentQ = activeQuizSession.questions[currentQuestionIndex];
                window._lastExplanation = currentQ ? (currentQ.explanation || "") : "";
                
                if (guess.length > 0 && verdictBox && feedbackEl && verdictLabel) {
                    verdictBox.classList.remove('hidden');
                    feedbackEl.textContent = verification.feedback;
                    lastVerdictIsCorrect = !!verification.is_correct;

                    if (verification.is_correct) {
                        verdictLabel.textContent = "AI Evaluation: Conceptually Correct";
                        verdictLabel.className = "text-[9px] font-bold uppercase tracking-wider text-emerald-450";
                        verdictBox.className = "p-3 rounded-xl border border-emerald-500/30 bg-emerald-950/10 flex flex-col space-y-1";
                        if (btnRemembered) btnRemembered.className = "py-3 bg-emerald-550 text-stone-900 font-bold rounded-2xl transition flex items-center justify-center space-x-1.5 ring-2 ring-emerald-400 shadow-lg shadow-emerald-500/20";
                        if (btnForgot) btnForgot.className = "py-3 bg-stone-100 border border-stone-200 text-stone-500 font-bold rounded-2xl transition flex items-center justify-center space-x-1.5 opacity-60";
                    } else {
                        verdictLabel.textContent = "AI Evaluation: Incorrect / Needs Review";
                        verdictLabel.className = "text-[9px] font-bold uppercase tracking-wider text-red-450";
                        verdictBox.className = "p-3 rounded-xl border border-red-500/30 bg-red-950/10 flex flex-col space-y-1";
                        if (btnForgot) btnForgot.className = "py-3 bg-red-550 text-stone-900 font-bold rounded-2xl transition flex items-center justify-center space-x-1.5 ring-2 ring-red-400 shadow-lg shadow-red-500/20";
                        if (btnRemembered) btnRemembered.className = "py-3 bg-stone-100 border border-stone-200 text-stone-500 font-bold rounded-2xl transition flex items-center justify-center space-x-1.5 opacity-60";
                    }
                }
            } catch (e) {
                console.error("Conceptual verification error:", e);
            } finally {
                btnShow.disabled = false;
                btnShow.textContent = originalText;
            }
            
            const frontCard = document.getElementById('quiz-card-front');
            const backCard = document.getElementById('quiz-card-back');
            if (frontCard) frontCard.classList.add('hidden');
            if (backCard) backCard.classList.remove('hidden');
            renderIcons();

            // Auto-read the answer aloud if the toggle is enabled (mirrors the
            // auto-read of the question on the front card).
            const autoTts = document.getElementById('quiz-auto-tts-toggle');
            const answerEl = document.getElementById('quiz-correct-answer');
            if (autoTts && autoTts.checked && answerEl) {
                setTimeout(() => speakText(answerEl.textContent, document.getElementById('btn-tts-answer')), 300);
            }
        });
    }

    if (btnClose) btnClose.addEventListener('click', closeQuizOverlay);
    if (btnQuit) btnQuit.addEventListener('click', closeQuizOverlay);

    if (btnForgot) btnForgot.addEventListener('click', () => gradeQuestion('forgot'));
    if (btnRemembered) btnRemembered.addEventListener('click', () => gradeQuestion('remembered'));

    document.addEventListener('keydown', handleQuizKeydown);
}

// Keyboard shortcuts for the quiz overlay:
// - Front card: Enter (always) or Space (when not typing) shows the answer,
//   which submits the guess for AI grading if one was typed, or just flips
//   the card if not.
// - Back card: "1"/"2" grade Forgot/Remembered directly (matching the numbers
//   printed on the buttons), and Enter/Space confirm whichever grade the AI
//   verdict recommended.
function handleQuizKeydown(e) {
    const overlay = document.getElementById('overlay-quiz');
    if (!overlay || overlay.classList.contains('hidden')) return;
    if (!activeQuizSession) return;

    const frontCard = document.getElementById('quiz-card-front');
    const backCard = document.getElementById('quiz-card-back');
    const isFrontVisible = frontCard && !frontCard.classList.contains('hidden');
    const isBackVisible = backCard && !backCard.classList.contains('hidden');

    const active = document.activeElement;
    const activeTag = active ? active.tagName : '';
    // Let native keyboard behavior win for focused buttons/selects/checkboxes
    // (e.g. Space toggling the Auto-read checkbox) rather than hijacking it.
    const isSafeToHijack = !(activeTag === 'BUTTON' || activeTag === 'SELECT'
        || (activeTag === 'INPUT' && active.type === 'checkbox'));

    if (isFrontVisible) {
        const btnShow = document.getElementById('btn-show-answer');
        if (e.key === 'Enter' && isSafeToHijack) {
            e.preventDefault();
            if (btnShow && !btnShow.disabled) btnShow.click();
        } else if (e.key === ' ' && isSafeToHijack && activeTag !== 'TEXTAREA') {
            e.preventDefault();
            if (btnShow && !btnShow.disabled) btnShow.click();
        }
        return;
    }

    if (isBackVisible) {
        if (e.key === '1') {
            e.preventDefault();
            gradeQuestion('forgot');
        } else if (e.key === '2') {
            e.preventDefault();
            gradeQuestion('remembered');
        } else if ((e.key === 'Enter' || e.key === ' ') && isSafeToHijack) {
            e.preventDefault();
            if (lastVerdictIsCorrect === true) {
                gradeQuestion('remembered');
            } else if (lastVerdictIsCorrect === false) {
                gradeQuestion('forgot');
            }
        }
    }
}

async function triggerStudy(videoId, level, quizId = null) {
    if (quizId) {
        return startQuiz(quizId);
    }
    try {
        // Prefer the live cached rating over a `level` argument that may have been
        // baked in at the last card render, see the matching note in
        // handleStudyButtonClick (videos.js).
        const liveLevel = (window._videoCardCache && window._videoCardCache[videoId] && window._videoCardCache[videoId].importance_rating) || level;
        const formData = new FormData();
        formData.append('level', liveLevel);
        const res = await fetchAPI(`/api/videos/${videoId}/generate_quiz`, {
            method: 'POST',
            body: formData
        });
        if (res && res.quiz_id) {
            return startQuiz(res.quiz_id);
        }
    } catch (e) {
        console.error("Error starting study session:", e);
        alert("Error launching quiz: " + (e.detail || e.message || e));
    }
}

// Window bindings for inline HTML attribute calls
window.triggerStudy = triggerStudy;
window.startQuiz = startQuiz;
window.renderQuizQuestion = renderQuizQuestion;
window.closeQuizOverlay = closeQuizOverlay;
window.gradeQuestion = gradeQuestion;
window.rescheduleQuiz = rescheduleQuiz;
window.initQuizEvents = initQuizEvents;
window.speakText = speakText;
window.stopCurrentSpeech = stopCurrentSpeech;

