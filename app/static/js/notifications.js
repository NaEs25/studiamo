/**
 * Global Non-Blocking Toast, Confirmation & Prompt Notification Module (Warm Paper Sepia Theme).
 * Provides lightweight, responsive UI toasts and promise-based modal dialogs across Studiamo.
 */

let _appToastTimer = null;
let _appToastDuration = 0;

/**
 * Display a non-blocking toast notification pill at the bottom of the screen.
 * @param {string} text Notification text message to display.
 * @param {string} type Notification type: 'saving' | 'saved' | 'loading' | 'info' | 'failed' | 'error' | 'success'.
 * @param {number|null} duration Auto-dismiss delay in milliseconds (0 or null for persistent loading toasts).
 */
function showToast(text, type = 'saved', duration = null) {
    const indicator = document.getElementById('app-toast-indicator') || document.getElementById('settings-autosave-indicator');
    const textEl = document.getElementById('app-toast-text') || document.getElementById('settings-autosave-text');
    const pill = document.getElementById('app-toast-pill') || document.getElementById('settings-autosave-pill');
    const iconEl = document.getElementById('app-toast-icon');

    if (!indicator) return;

    if (textEl) textEl.textContent = text;

    let iconHtml = '';
    let pillClasses = 'px-4 py-2 rounded-2xl text-xs font-bold text-left shadow-2xl border backdrop-blur-md flex items-start space-x-2 ';
    let defaultDuration = 2500;

    if (type === 'saving' || type === 'loading') {
        pillClasses += 'bg-amber-950/95 text-amber-200 border-amber-600/60 ring-2 ring-amber-500/30';
        iconHtml = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-amber-400"></i>';
        defaultDuration = type === 'loading' ? 0 : 3000;
    } else if (type === 'failed' || type === 'error') {
        pillClasses += 'bg-red-950/95 text-red-200 border-red-600/60 ring-2 ring-red-500/30';
        iconHtml = '<i data-lucide="alert-triangle" class="w-3.5 h-3.5 text-red-400"></i>';
        defaultDuration = 4000;
    } else if (type === 'info') {
        pillClasses += 'bg-stone-900/95 text-amber-200 border-stone-700 ring-2 ring-amber-500/30';
        iconHtml = '<i data-lucide="info" class="w-3.5 h-3.5 text-amber-400"></i>';
        defaultDuration = 2500;
    } else { // 'saved', 'success'
        pillClasses += 'bg-emerald-950/95 text-emerald-200 border-emerald-600/60 ring-2 ring-emerald-500/30';
        iconHtml = '<i data-lucide="check-circle-2" class="w-3.5 h-3.5 text-emerald-400"></i>';
        defaultDuration = 2000;
    }

    if (pill) {
        pill.className = pillClasses;
        // A swipe-dismissed toast leaves its transform and fade behind, so a new one starts clean.
        pill.style.transition = '';
        pill.style.transform = '';
        pill.style.opacity = '';
        // The container ignores pointer events so it never blocks the page; the pill takes them
        // back while it is showing so it can be swiped away.
        pill.style.pointerEvents = 'auto';
    }
    if (iconEl) {
        iconEl.innerHTML = iconHtml;
        if (typeof renderIcons === 'function') renderIcons();
    }

    indicator.classList.remove('opacity-0', 'translate-y-2');
    indicator.classList.add('opacity-100', 'translate-y-0');

    if (_appToastTimer) clearTimeout(_appToastTimer);
    const finalDuration = duration !== null ? duration : defaultDuration;
    _appToastDuration = finalDuration;
    if (finalDuration > 0) {
        _appToastTimer = setTimeout(() => {
            hideToast();
        }, finalDuration);
    }
}

/**
 * Dismiss the active global toast notification pill.
 */
function hideToast() {
    const indicator = document.getElementById('app-toast-indicator') || document.getElementById('settings-autosave-indicator');
    if (!indicator) return;
    if (_appToastTimer) clearTimeout(_appToastTimer);
    const pill = document.getElementById('app-toast-pill');
    if (pill) pill.style.pointerEvents = 'none';
    indicator.classList.remove('opacity-100', 'translate-y-0');
    indicator.classList.add('opacity-0', 'translate-y-2');
}

// Swipe the toast down to dismiss it. Pointer events cover touch, pen and mouse in one path, so
// there is no separate touch handler. While a finger is down the auto-dismiss timer is paused,
// and a release that did not travel far enough snaps back and resumes it.
const TOAST_SWIPE_DISMISS_PX = 40;

function initToastSwipe() {
    const pill = document.getElementById('app-toast-pill');
    if (!pill || pill._swipeBound) return;
    pill._swipeBound = true;
    // Without this the browser claims the vertical drag to scroll the page and cancels it.
    // Text selection has to go too: starting one mid-drag cancels the pointer the same way,
    // and on iOS a press on selectable text raises the copy callout instead of a swipe.
    pill.style.touchAction = 'none';
    pill.style.userSelect = 'none';
    pill.style.webkitUserSelect = 'none';

    let startY = null;
    let pointerId = null;

    pill.addEventListener('pointerdown', (e) => {
        startY = e.clientY;
        pointerId = e.pointerId;
        pill.setPointerCapture(pointerId);
        pill.style.transition = 'none';
        if (_appToastTimer) clearTimeout(_appToastTimer);
    });

    pill.addEventListener('pointermove', (e) => {
        if (startY === null || e.pointerId !== pointerId) return;
        // Only downward: dragging up would fight the toast's own position.
        const dy = Math.max(0, e.clientY - startY);
        pill.style.transform = `translateY(${dy}px)`;
        pill.style.opacity = String(Math.max(0.2, 1 - dy / 120));
    });

    const finish = (e) => {
        if (startY === null || e.pointerId !== pointerId) return;
        const dy = Math.max(0, e.clientY - startY);
        startY = null;
        pill.style.transition = 'transform 180ms ease, opacity 180ms ease';

        if (e.type === 'pointerup' && dy >= TOAST_SWIPE_DISMISS_PX) {
            pill.style.transform = 'translateY(140%)';
            pill.style.opacity = '0';
            setTimeout(hideToast, 180);
            return;
        }

        pill.style.transform = '';
        pill.style.opacity = '';
        if (_appToastDuration > 0) {
            _appToastTimer = setTimeout(hideToast, Math.min(_appToastDuration, 2500));
        }
    };
    pill.addEventListener('pointerup', finish);
    pill.addEventListener('pointercancel', finish);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initToastSwipe);
} else {
    initToastSwipe();
}

/**
 * Display a custom Promise-based In-App Confirmation Modal.
 * @param {Object} options Configuration options for title, message, button texts, and icons.
 * @returns {Promise<boolean>} Resolves to true if confirmed, false if cancelled or dismissed.
 */
function showConfirm(options = {}) {
    return new Promise((resolve) => {
        const overlay = document.getElementById('app-confirm-overlay');
        const box = document.getElementById('app-confirm-box');
        const titleEl = document.getElementById('app-confirm-title');
        const msgEl = document.getElementById('app-confirm-message');
        const btnCancel = document.getElementById('app-confirm-btn-cancel');
        const btnOk = document.getElementById('app-confirm-btn-ok');
        const iconEl = document.getElementById('app-confirm-icon');
        const iconWrapper = document.getElementById('app-confirm-icon-wrapper');

        if (!overlay || !box) {
            resolve(window.confirm(options.message || 'Are you sure?'));
            return;
        }

        const {
            title = 'Confirm Action',
            message = 'Are you sure you want to proceed?',
            confirmText = 'Confirm',
            cancelText = 'Cancel',
            confirmClass = 'bg-[#fbbf24] hover:bg-[#f59e0b] text-[#78350f] font-bold rounded-xl text-xs shadow-sm transition',
            icon = 'alert-triangle'
        } = options;

        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.textContent = message;
        if (btnOk) {
            btnOk.textContent = confirmText;
            btnOk.className = `px-4 py-2 ${confirmClass}`;
        }
        if (btnCancel) btnCancel.textContent = cancelText;
        if (iconEl) {
            iconEl.setAttribute('data-lucide', icon);
            if (typeof renderIcons === 'function') renderIcons();
        }
        if (iconWrapper) {
            if (confirmClass.includes('red')) {
                iconWrapper.className = 'p-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 shrink-0';
            } else {
                iconWrapper.className = 'p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 shrink-0';
            }
        }

        overlay.classList.remove('hidden');
        requestAnimationFrame(() => {
            overlay.classList.remove('opacity-0');
            box.classList.remove('scale-95', 'opacity-0');
            box.classList.add('scale-100', 'opacity-100');
        });

        const cleanup = (result) => {
            box.classList.remove('scale-100', 'opacity-100');
            box.classList.add('scale-95', 'opacity-0');
            overlay.classList.add('opacity-0');
            setTimeout(() => {
                overlay.classList.add('hidden');
                btnOk.removeEventListener('click', onOk);
                btnCancel.removeEventListener('click', onCancel);
                window.removeEventListener('keydown', onKey);
                resolve(result);
            }, 180);
        };

        const onOk = () => cleanup(true);
        const onCancel = () => cleanup(false);
        const onKey = (e) => {
            if (e.key === 'Escape') cleanup(false);
            if (e.key === 'Enter') cleanup(true);
        };

        btnOk.addEventListener('click', onOk);
        btnCancel.addEventListener('click', onCancel);
        window.addEventListener('keydown', onKey);
    });
}

/**
 * Display a custom Promise-based In-App Prompt Input Modal.
 * @param {Object} options Configuration options for title, message, default value, and input type.
 * @returns {Promise<string|null>} Resolves to entered string if submitted, or null if cancelled.
 */
function showPrompt(options = {}) {
    return new Promise((resolve) => {
        const overlay = document.getElementById('app-prompt-overlay');
        const form = document.getElementById('app-prompt-form');
        const titleEl = document.getElementById('app-prompt-title');
        const msgEl = document.getElementById('app-prompt-message');
        const inputEl = document.getElementById('app-prompt-input');
        const btnCancel = document.getElementById('app-prompt-btn-cancel');

        if (!overlay || !form || !inputEl) {
            resolve(window.prompt(options.message || 'Please enter value:', options.defaultValue || ''));
            return;
        }

        const {
            title = 'Input Required',
            message = 'Please enter a value:',
            defaultValue = '',
            inputType = 'text'
        } = options;

        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.textContent = message;
        inputEl.type = inputType;
        inputEl.value = defaultValue;

        overlay.classList.remove('hidden');
        requestAnimationFrame(() => {
            overlay.classList.remove('opacity-0');
            form.classList.remove('scale-95', 'opacity-0');
            form.classList.add('scale-100', 'opacity-100');
            inputEl.focus();
            inputEl.select();
        });

        const cleanup = (val) => {
            form.classList.remove('scale-100', 'opacity-100');
            form.classList.add('scale-95', 'opacity-0');
            overlay.classList.add('opacity-0');
            setTimeout(() => {
                overlay.classList.add('hidden');
                form.removeEventListener('submit', onSubmit);
                btnCancel.removeEventListener('click', onCancel);
                window.removeEventListener('keydown', onKey);
                resolve(val);
            }, 180);
        };

        const onSubmit = (e) => {
            e.preventDefault();
            cleanup(inputEl.value);
        };
        const onCancel = () => cleanup(null);
        const onKey = (e) => {
            if (e.key === 'Escape') cleanup(null);
        };

        form.addEventListener('submit', onSubmit);
        btnCancel.addEventListener('click', onCancel);
        window.addEventListener('keydown', onKey);
    });
}

// Bind to window object for global availability
window.showToast = showToast;
window.hideToast = hideToast;
window.showConfirm = showConfirm;
window.showPrompt = showPrompt;
