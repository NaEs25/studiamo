/**
 * Subscription paywall + billing UI (cloud mode only).
 *
 * The modal here is UX, not enforcement. Anyone can delete a DOM node, so access is
 * enforced server-side by has_app_access() / the require_app_access dependency; this file
 * exists so a blocked user is told why and given a way to fix it, rather than meeting a
 * wall of 402s.
 */

// Whether the user has already declined the standard-price offer in this session. The
// discounted offer is gated on this and on nothing else: no URL parameter, no deep link.
let _paywallDeclinedStandard = false;

// How long to wait for the Lemon Squeezy webhook after returning from checkout.
const ACTIVATION_POLL_INTERVAL_MS = 2000;
const ACTIVATION_POLL_TIMEOUT_MS = 30000;


function _paywallShowStep(stepId) {
    // Every step id must be listed. _paywallShowStep only toggles what it knows about, so a
    // step missing from this array is never hidden and would sit under the one being shown.
    ['paywall-step-standard', 'paywall-step-beta', 'paywall-step-tester-expired',
     'paywall-step-activating', 'paywall-step-pending']
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.toggle('hidden', id !== stepId);
        });
    if (typeof renderIcons === 'function') renderIcons();
}


function _paywallError(message) {
    const el = document.getElementById('paywall-error');
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('hidden', !message);
}


function openPaywall(stepId = 'paywall-step-standard') {
    const overlay = document.getElementById('overlay-paywall');
    if (!overlay) return;
    _paywallShowStep(stepId);
    overlay.classList.remove('hidden');
    // Stop the page behind the modal from scrolling, so it cannot be read past the overlay.
    document.body.style.overflow = 'hidden';
    if (typeof renderIcons === 'function') renderIcons();
}


function closePaywall() {
    const overlay = document.getElementById('overlay-paywall');
    if (!overlay) return;
    overlay.classList.add('hidden');
    document.body.style.overflow = '';
}


// Last known tester state, so the 402 handler can pick the right step without a fetch of
// its own. Set by initPaywall from the status call it already makes.
let _testerState = null;


/** Which first screen a blocked user should meet. */
function _blockedStepFor(tester) {
    const state = tester && tester.state;
    return (state === 'expired' || state === 'revoked')
        ? 'paywall-step-tester-expired'
        : 'paywall-step-standard';
}


/**
 * Records that a tester notice was shown, so it is not shown again and so the admin side
 * can see who has actually been told.
 *
 * Fire-and-forget on purpose: this is bookkeeping, and a failed POST must not stop the
 * screen it is recording from being displayed.
 */
function _ackTesterNotice(kind) {
    const body = new FormData();
    body.append('kind', kind);
    fetch('/api/billing/tester/ack', { method: 'POST', body, credentials: 'same-origin' })
        .catch(e => console.warn('Tester notice ack failed:', e));
}


/**
 * Called by fetchAPI when any request returns 402, i.e. access lapsed mid-session.
 *
 * Opens the paywall only if it is not already showing. openPaywall() defaults to step 1,
 * so calling it unconditionally would yank a user who is reading the discounted offer
 * back to the default screen the moment any background request returned 402, losing the
 * offer they were about to accept.
 *
 * Picks the same step initPaywall would. Without that, a tester whose period ran out while
 * the tab sat open would be shown the first-time "Thank you for choosing Cloud" screen,
 * which is exactly the case the expired step exists for and the likeliest way to meet it.
 */
function notifyPaymentRequired() {
    const overlay = document.getElementById('overlay-paywall');
    if (!overlay || !overlay.classList.contains('hidden')) return;
    const step = _blockedStepFor(_testerState);
    if (step === 'paywall-step-tester-expired') {
        _ackTesterNotice('expiry');
        const send = document.getElementById('tester-feedback-send');
        if (send) send.addEventListener('click', sendTesterFeedback);
    }
    openPaywall(step);
}


/** Step 1 declined: reveal the promotional offer. This is the only path to it. */
function declineStandardPrice() {
    _paywallDeclinedStandard = true;
    _paywallError('');
    _paywallShowStep('paywall-step-beta');
}


async function logoutFromPaywall() {
    // Delegates to the app's own logout so session cleanup stays in one place.
    //
    // The fallback below is not decoration. This originally called a function named
    // `logout()`, which does not exist, the real one is `logoutUser()`, so the guard was
    // always false and it silently navigated to /login WITHOUT clearing anything. The
    // yb_session cookie survived, every later visit resolved back to the unpaid account,
    // and signing in as a different user appeared to fail because the stale session was
    // still authoritative. Navigating away is not logging out, so if the delegate is ever
    // missing again, tear the session down here rather than pretending.
    if (typeof logoutUser === 'function') return logoutUser();

    try {
        await fetch('/api/users/logout', { method: 'POST' });
    } catch (e) {
        console.warn('Paywall logout request failed; clearing client state anyway:', e);
    }
    localStorage.removeItem('active_username');
    localStorage.removeItem('active_studiamo_tab');
    sessionStorage.removeItem('profile_password');
    document.cookie = 'username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    document.cookie = 'profile_password=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    window.location.href = '/login';
}


/**
 * Sends the user to Lemon Squeezy checkout.
 *
 * On the general paywall the promotional code is displayed in our own UI and typed in at
 * checkout rather than pre-applied, because Lemon Squeezy renders an applied discount below
 * its pay button, where someone who does not scroll never sees it.
 *
 * The expired-tester screen passes applyDiscount, having already stated the price and terms
 * on our side: that reader has earned the offer, and asking them to transcribe a code is
 * friction at the moment their answer is still open.
 */
async function startCheckout(applyDiscount = false) {
    _paywallError('');
    try {
        const data = await fetchAPI(
            `/api/billing/checkout${applyDiscount ? '?apply_discount=true' : ''}`);
        if (!data || !data.checkout_url) throw new Error('No checkout URL returned');
        window.location.href = data.checkout_url;
    } catch (e) {
        console.error('Checkout failed:', e);
        _paywallError("Couldn't open checkout. Please try again, or email hello@studiamo.cloud.");
    }
}


/**
 * Polls billing status after returning from checkout.
 *
 * Lemon Squeezy redirects the browser back immediately, but access is granted by the
 * webhook, which can land a second or two later. Without this the user would bounce
 * straight back onto the paywall having just paid.
 */
async function _pollForActivation() {
    openPaywall('paywall-step-activating');
    const deadline = Date.now() + ACTIVATION_POLL_TIMEOUT_MS;

    while (Date.now() < deadline) {
        try {
            const status = await fetchAPI('/api/billing/status');
            if (status && status.has_access) {
                closePaywall();
                if (typeof loadSettings === 'function' && document.getElementById('tab-settings')) {
                    loadSettings();
                }
                return true;
            }
        } catch (e) {
            console.warn('Activation poll error:', e);
        }
        await new Promise(r => setTimeout(r, ACTIVATION_POLL_INTERVAL_MS));
    }

    _paywallShowStep('paywall-step-pending');
    return false;
}


/**
 * Entry point, called once on load.
 *
 * Self-hosted deployments have no billing at all, so this is a no-op there.
 */
async function initPaywall() {
    // app_mode arrives from an async fetch in core.js. Await it rather than assuming it has
    // landed, checking window.appConfig too early reads undefined, and the paywall would
    // then silently never appear for anyone.
    if (window.systemConfigReady) {
        try { await window.systemConfigReady; } catch (e) { /* falls through to the guard below */ }
    }
    if (!window.appConfig || !window.appConfig.is_cloud) return;

    const params = new URLSearchParams(window.location.search);
    const returningFromCheckout = params.get('checkout') === 'success';

    if (returningFromCheckout) {
        // Drop the parameter so a refresh doesn't re-trigger the poll, and so the URL
        // doesn't stay in this state in the user's history.
        params.delete('checkout');
        const clean = window.location.pathname + (params.toString() ? `?${params}` : '');
        window.history.replaceState({}, '', clean);
        await _pollForActivation();
        return;
    }

    try {
        const status = await fetchAPI('/api/billing/status');
        _testerState = (status && status.tester) || null;
        // Populated before the modal opens, so the code is already on screen rather than
        // appearing a moment after the user starts reading.
        renderDiscountNote(status && status.beta_discount_code);
        renderTesterPill(_testerState);
        if (status && !status.has_access) {
            const step = _blockedStepFor(_testerState);
            if (step === 'paywall-step-tester-expired') {
                _ackTesterNotice('expiry');
                const send = document.getElementById('tester-feedback-send');
                if (send) send.addEventListener('click', sendTesterFeedback);
            }
            openPaywall(step);
            return;
        }
        // Deferred so the onboarding and "what's new" modals, which fire from their own
        // load path, have already claimed the screen if they were going to.
        setTimeout(() => maybeShowTesterNotice(_testerState), 1200);
    } catch (e) {
        // A failed status check must not lock anyone out of an app they have paid for.
        // The server-side dependency is the real gate; this is only the explanation.
        console.warn('Billing status check failed, not showing paywall:', e);
    }
}


/**
 * Fills in the promotional code wherever it is offered.
 *
 * The code is never hardcoded in the frontend. It comes from the server, which reads it
 * from the environment, so rotating it means changing one value and nothing here. An empty
 * value means no promotion is running, and every note about one is hidden rather than
 * rendered with a blank code in the middle of the sentence.
 */
function renderDiscountNote(code) {
    // Every occurrence, not one: the offer partial is included by more than one paywall
    // step, so this cannot key off an id.
    document.querySelectorAll('[data-discount-note]').forEach(note => {
        if (!code) {
            note.classList.add('hidden');
            return;
        }
        const target = note.querySelector('[data-discount-code]');
        if (target) target.textContent = code;
        note.classList.remove('hidden');
    });
}


/** The same note as an HTML string, for the action area of the Settings card. */
function _discountNoteMarkup(code) {
    if (!code) return '';
    return `
        <div class="discount-note">
            <i data-lucide="ticket-percent" class="w-4 h-4 flex-shrink-0"></i>
            <span>
                Enter code <strong class="discount-code">${code}</strong> at checkout for 50% off
                your first 6 months, because you are helping test Studiamo. Cancel any time.
            </span>
        </div>`;
}


// Every variant the status badge can wear. The template owns the badge's shape; these are
// the only classes the script adds or removes, so the two cannot drift apart.
const STATUS_BADGE_VARIANTS = [
    'status-badge-positive', 'status-badge-warning', 'status-badge-danger',
    'status-badge-neutral', 'status-badge-tester',
];


/** Formats an ISO date for display, e.g. "September 5, 2026". Empty string on anything
 *  unparseable, so a bad value degrades to a sentence without a date rather than
 *  "Invalid Date". */
function _formatTesterDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}


/** "1 day" / "5 days", so no sentence has to read "in 1 days". */
function _dayCount(n) {
    return n === 1 ? '1 day' : `${n} days`;
}


/**
 * Whole days from today until `iso`, by calendar date in UTC, or null.
 *
 * Mirrors _tester_days_left in database.py rather than dividing a millisecond difference
 * by 86400000: a subscription ending at 01:00 tomorrow is one day away, not zero, and the
 * two ways of counting disagree for most of every day. Negative results clamp to 0.
 */
function _daysUntil(iso) {
    if (!iso) return null;
    const end = new Date(iso);
    if (isNaN(end.getTime())) return null;
    const endDay = Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate());
    const now = new Date();
    const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    return Math.max(0, Math.round((endDay - today) / 86400000));
}


/**
 * Subscription states whose message is better with a date in it.
 *
 * 'cancelled' especially: in Lemon Squeezy it means "will not renew", so the customer keeps
 * access until ls_ends_at, and "you keep access until the end of the paid period" was
 * asking them to work out when that is from a receipt somewhere.
 */
function _datedSubscriptionText(status, settings, fallback) {
    const endsAt = settings && settings.subscription_ends_at;
    const renewsAt = settings && settings.subscription_renews_at;

    if (status === 'cancelled') {
        const on = _formatTesterDate(endsAt);
        if (!on) return fallback;
        const left = _daysUntil(endsAt);
        if (left === 0) return `Cancelled. Your access ends today, ${on}.`;
        if (left === null) return `Cancelled. You keep access until ${on}.`;
        return `Cancelled. Your access ends in ${_dayCount(left)}, on ${on}.`;
    }

    if (status === 'active') {
        const on = _formatTesterDate(renewsAt);
        return on ? `Your subscription is active. It renews on ${on}.` : fallback;
    }

    if (status === 'past_due') {
        const on = _formatTesterDate(endsAt);
        return on
            ? `Your last payment failed. Update your card before ${on} to avoid losing access.`
            : fallback;
    }

    return fallback;
}


/**
 * Chooses the badge and body text for an account with tester access.
 *
 * Branches on `unlimited` and `legacy` BEFORE looking at days_left: both carry
 * days_left === null, which is silently false-y in JS and would otherwise fall through to
 * the "ends today" wording for someone whose access has no end date at all.
 */
function _testerPreset(tester) {
    const ended = { label: 'Tester ended', variant: 'status-badge-neutral' };

    if (tester.state === 'expired' || tester.state === 'revoked') {
        const on = _formatTesterDate(tester.expires_at);
        return {
            ...ended,
            text: on
                ? `Your tester access ended on ${on}. Thank you for helping test Studiamo.`
                : 'Your tester access has ended. Thank you for helping test Studiamo.',
        };
    }

    if (tester.unlimited) {
        return {
            label: 'Tester', variant: 'status-badge-tester',
            text: 'You have tester access with no end date.',
        };
    }

    // Predates time-boxed grants. Kept deliberately vague: there is no end date to show,
    // and inventing one here would be a promise the database is not making.
    if (tester.legacy) {
        return {
            label: 'Tester', variant: 'status-badge-tester',
            text: 'You have free tester access.',
        };
    }

    const left = tester.days_left;
    const on = _formatTesterDate(tester.expires_at);

    if (left === 0) {
        return {
            label: 'Ending today', variant: 'status-badge-warning',
            text: 'Your tester access ends today. Subscribe to keep your library and your streak.',
        };
    }
    if (left !== null && left <= 7) {
        return {
            label: 'Tester', variant: 'status-badge-warning',
            text: `Tester access ends in ${_dayCount(left)}, on ${on}.`,
        };
    }
    return {
        label: 'Tester', variant: 'status-badge-tester',
        text: `Tester access until ${on}. ${_dayCount(left)} left.`,
    };
}


/**
 * Renders the Settings subscription card from live status.
 * Called by loadSettings() once the settings payload is in.
 */
function renderSubscriptionCard(settings) {
    const textEl = document.getElementById('subscription-status-text');
    const badgeEl = document.getElementById('subscription-status-badge');
    const actionEl = document.getElementById('subscription-action');
    if (!textEl || !badgeEl) return;

    const status = (settings && settings.subscription_status) || 'inactive';
    // `tester` carries the end date; `is_tester` is the flat legacy flag kept for older
    // clients. Fall back to it so this still renders something sane if the payload is stale.
    const tester = (settings && settings.tester) || null;
    const isTester = tester
        ? tester.state !== 'none'
        : !!(settings && settings.is_tester);
    const testerEnded = !!tester && (tester.state === 'expired' || tester.state === 'revoked');

    const PRESETS = {
        active:    { label: 'Active',      variant: 'status-badge-positive', text: 'Your subscription is active.' },
        on_trial:  { label: 'Trial',       variant: 'status-badge-positive', text: 'You are on a free trial.' },
        past_due:  { label: 'Payment due', variant: 'status-badge-warning',  text: "Your last payment failed. Update your card to avoid losing access." },
        cancelled: { label: 'Ending',      variant: 'status-badge-warning',  text: 'Cancelled: you keep access until the end of the paid period.' },
        paused:    { label: 'Paused',      variant: 'status-badge-neutral',  text: 'Your subscription is paused.' },
        unpaid:    { label: 'Unpaid',      variant: 'status-badge-danger',   text: 'Your subscription is unpaid.' },
        expired:   { label: 'Expired',     variant: 'status-badge-neutral',  text: 'Your subscription has expired.' },
        inactive:  { label: 'None',        variant: 'status-badge-neutral',  text: 'You do not have an active subscription.' },
    };

    // A real subscription outranks a tester grant: someone who subscribed mid-test phase is
    // paying, and should be told about the thing they are paying for.
    const hasSubscription = status !== 'inactive';
    let preset;
    if (isTester && !hasSubscription) {
        preset = tester
            ? _testerPreset(tester)
            : { label: 'Tester', variant: 'status-badge-tester', text: 'You have free tester access.' };
    } else {
        preset = PRESETS[status] || PRESETS.inactive;
        preset = { ...preset, text: _datedSubscriptionText(status, settings, preset.text) };
    }

    textEl.textContent = preset.text;
    badgeEl.textContent = preset.label;
    // Toggle the variant only. The shape classes stay in the template, where they are
    // declared once.
    badgeEl.classList.remove(...STATUS_BADGE_VARIANTS);
    badgeEl.classList.add(preset.variant);

    if (tester) renderTesterPill(tester);

    if (!actionEl) return;
    _renderSubscriptionAction(actionEl, {
        hasSubscription, isTester, testerEnded, tester,
        discountCode: (settings && settings.beta_discount_code) || '',
    });
}


/**
 * Fills the action area under the status box.
 *
 * Handlers are attached with addEventListener after the markup is in place rather than
 * written as inline onclick attributes in these template strings.
 */
function _renderSubscriptionAction(actionEl, { hasSubscription, isTester, testerEnded, tester, discountCode }) {
    // Above the button, not below it: the code has to be read before the click, not
    // discovered afterwards on someone else's checkout page.
    const DISCOUNT_NOTE = _discountNoteMarkup(discountCode);
    const SUBSCRIBE_BTN = `
        <button type="button" data-action="checkout"
            class="btn-primary w-full py-2.5 px-4 rounded-xl text-xs font-extrabold transition flex items-center justify-center space-x-2">
            <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
            <span>Continue with a subscription</span>
        </button>`;
    const EXPORT_BTN = `
        <a href="/api/user/export"
            class="w-full py-2.5 px-4 bg-stone-100 hover:bg-stone-200 border border-[#e7dfd3] rounded-xl text-xs font-bold text-stone-700 transition flex items-center justify-center space-x-2">
            <i data-lucide="download" class="w-3.5 h-3.5"></i>
            <span>Download my data</span>
        </a>`;

    if (hasSubscription) {
        actionEl.innerHTML = `
            <button type="button" data-action="billing-portal"
                class="w-full py-2.5 px-4 bg-stone-100 hover:bg-stone-200 border border-[#e7dfd3] rounded-xl text-xs font-bold text-stone-700 transition flex items-center justify-center space-x-2">
                <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                <span>Manage subscription</span>
            </button>`;
    } else if (testerEnded) {
        // The export link matters most here: this is someone deciding whether to stay, and
        // leaving with their data has to be as reachable as paying.
        actionEl.innerHTML = `<div class="space-y-2">${DISCOUNT_NOTE}${SUBSCRIBE_BTN}${EXPORT_BTN}</div>`;
    } else if (isTester && tester && !tester.unlimited && !tester.legacy && tester.days_left !== null && tester.days_left <= 7) {
        // Only once the end is in sight. A tester on day one is here to test, not to be sold to.
        actionEl.innerHTML = `<div class="space-y-2">${DISCOUNT_NOTE}${SUBSCRIBE_BTN}</div>`;
    } else if (isTester) {
        // Testers with time left have no subscription to manage and nothing to buy yet.
        actionEl.innerHTML = '';
        return;
    } else {
        actionEl.innerHTML = `
            <button type="button" data-action="checkout"
                class="btn-primary w-full py-2.5 px-4 rounded-xl text-xs font-extrabold transition flex items-center justify-center space-x-2">
                <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                <span>Subscribe ($7.99 / month)</span>
            </button>`;
    }

    const HANDLERS = {
        'billing-portal': () => openBillingPortal(),
        'checkout': () => startCheckout(),
    };
    actionEl.querySelectorAll('[data-action]').forEach(el => {
        const handler = HANDLERS[el.dataset.action];
        if (handler) el.addEventListener('click', handler);
    });

    if (typeof renderIcons === 'function') renderIcons();
}


// --- Tester pill and notices ---------------------------------------------------------

/**
 * The countdown chip in the header.
 *
 * Hidden for everyone who is not a tester, and also for testers whose grant has no end
 * date, whether that is a deliberate unlimited grant or a legacy one: both carry
 * days_left === null, and a countdown with nothing to count down to is noise.
 */
function renderTesterPill(tester) {
    const pill = document.getElementById('tester-pill');
    const label = document.getElementById('tester-pill-label');
    if (!pill || !label) return;

    const left = tester && tester.days_left;
    const showable = tester && tester.state === 'active' && left !== null && left !== undefined;
    if (!showable) {
        pill.classList.add('hidden');
        pill.classList.remove('flex');
        return;
    }

    label.textContent = left === 0 ? 'Tester, ends today' : `Tester, ${_dayCount(left)} left`;
    pill.classList.remove('hidden');
    pill.classList.add('flex');
    // Same three-state colouring as the Settings badge, so the header and the card agree
    // about how much time is left.
    pill.classList.remove(...STATUS_BADGE_VARIANTS);
    pill.classList.add(left <= 7 ? 'status-badge-warning' : 'status-badge-tester');
    if (typeof renderIcons === 'function') renderIcons();
}


// Which notice is on screen, so dismissing it can acknowledge the right one.
let _openTesterNotice = null;


const TESTER_NOTICES = {
    welcome: {
        icon: 'flask-conical',
        iconWrap: 'bg-indigo-100 text-indigo-600',
        title: 'Welcome to the Studiamo test phase',
        primary: 'Start studying',
        dismiss: 'Close',
        body: (t) => [
            t.unlimited || t.days_left === null
                ? 'You have full access to everything in Studiamo, with no end date and nothing to cancel.'
                : `You have full access to everything in Studiamo for the next ${_dayCount(t.days_left)}, `
                  + `through <strong>${_formatTesterDate(t.expires_at)}</strong>. No card, no subscription, `
                  + 'nothing to cancel.',
            'What we would love from you: use it the way you actually study, and tell us where it gets '
              + 'in your way. The bug report button in the header goes straight to us.',
            'Your notes, imports and quiz history are yours and stay yours. You can download all of it '
              + 'at any time from Settings, whether or not you continue afterwards.',
        ],
    },
    reminder_7d: {
        icon: 'clock',
        iconWrap: 'bg-amber-100 text-amber-600',
        title: 'One week left in your test phase',
        primary: 'See the tester price',
        dismiss: 'Remind me later',
        body: (t) => [
            `Your tester access runs through <strong>${_formatTesterDate(t.expires_at)}</strong>. After that, `
              + 'Studiamo needs a subscription to keep going, at a price we are keeping low for the people '
              + 'who tested it.',
            'Nothing disappears when the test phase ends: your library stays where it is, and you can '
              + 'download everything from Settings at any time.',
        ],
    },
    reminder_1d: {
        icon: 'clock',
        iconWrap: 'bg-amber-100 text-amber-600',
        title: 'Your test phase ends tomorrow',
        primary: 'Continue with a subscription',
        dismiss: 'Not now',
        body: (t) => [
            `Tomorrow, <strong>${_formatTesterDate(t.expires_at)}</strong>, Studiamo will ask for a `
              + 'subscription. Everything you have built stays in your account either way, and your data '
              + 'export is always available in Settings.',
        ],
    },
};


function closeTesterNotice() {
    const overlay = document.getElementById('overlay-tester-notice');
    if (overlay) overlay.classList.add('hidden');
    document.body.classList.remove('overflow-hidden');
    // Written on dismiss rather than on open: a notice the user never actually saw, because
    // the tab was closed first, should still be waiting for them next time.
    if (_openTesterNotice) {
        _ackTesterNotice(_openTesterNotice === 'welcome' ? 'welcome' : _openTesterNotice);
        _openTesterNotice = null;
    }
}


function openTesterNotice(kind, tester) {
    const spec = TESTER_NOTICES[kind];
    const overlay = document.getElementById('overlay-tester-notice');
    if (!spec || !overlay) return;

    document.getElementById('tester-notice-title').textContent = spec.title;
    document.getElementById('tester-notice-icon').setAttribute('data-lucide', spec.icon);
    document.getElementById('tester-notice-icon-wrap').className =
        'w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0 ' + spec.iconWrap;
    document.getElementById('tester-notice-body').innerHTML =
        spec.body(tester).map(p => `<p>${p}</p>`).join('');
    document.getElementById('tester-notice-primary-label').textContent = spec.primary;
    document.getElementById('tester-notice-dismiss-label').textContent = spec.dismiss;

    const primary = document.getElementById('tester-notice-primary');
    // The welcome's primary action is just "get on with it"; the reminders' is the offer.
    primary.onclick = kind === 'welcome'
        ? () => closeTesterNotice()
        : () => { closeTesterNotice(); openPaywall('paywall-step-beta'); };

    _openTesterNotice = kind;
    overlay.classList.remove('hidden');
    document.body.classList.add('overflow-hidden');
    if (typeof renderIcons === 'function') renderIcons();
}


/**
 * Shows at most one tester notice per load, and only once nothing else is competing.
 *
 * The onboarding and "what's new" modals are also fired on load for new accounts, and a
 * tester's first session is exactly when all three could want the screen. Stacking them
 * would bury whichever lost. This one yields.
 */
function maybeShowTesterNotice(tester) {
    if (!tester || tester.state !== 'active') return;

    const busy = ['overlay-tab-guide', 'overlay-updates-modal', 'overlay-paywall']
        .some(id => {
            const el = document.getElementById(id);
            return el && !el.classList.contains('hidden');
        });
    if (busy) return;

    if (tester.needs_welcome) return openTesterNotice('welcome', tester);
    if (tester.needs_reminder === '1d') return openTesterNotice('reminder_1d', tester);
    if (tester.needs_reminder === '7d') return openTesterNotice('reminder_7d', tester);
}


/**
 * Sends the one-question tester feedback from the expired screen.
 *
 * Never blocks or replaces the two real actions next to it. The button reports what
 * happened in place, and a failure says so rather than pretending: someone who took the
 * trouble to write something deserves to know whether it arrived.
 */
async function sendTesterFeedback() {
    const input = document.getElementById('tester-feedback-input');
    const status = document.getElementById('tester-feedback-status');
    const button = document.getElementById('tester-feedback-send');
    if (!input || !button) return;

    const message = (input.value || '').trim();
    if (!message) {
        if (status) status.textContent = 'Write something first.';
        return;
    }

    button.disabled = true;
    if (status) status.textContent = 'Sending…';
    try {
        const body = new FormData();
        body.append('message', message);
        const res = await fetch('/api/billing/tester/feedback',
            { method: 'POST', body, credentials: 'same-origin' });
        if (!res.ok) throw new Error(String(res.status));
        input.disabled = true;
        button.classList.add('hidden');
        if (status) status.textContent = 'Thank you, that went straight to us.';
    } catch (e) {
        console.warn('Tester feedback failed:', e);
        if (status) status.textContent = "That didn't send. Please email hello@studiamo.cloud.";
        button.disabled = false;
    }
}


/** Opens the Lemon Squeezy customer portal, where the user updates their card or cancels. */
async function openBillingPortal() {
    try {
        const data = await fetchAPI('/api/billing/portal');
        if (!data || !data.portal_url) throw new Error('No portal URL returned');
        window.open(data.portal_url, '_blank', 'noopener');
    } catch (e) {
        console.error('Billing portal failed:', e);
        if (typeof showErrorBanner === 'function') {
            showErrorBanner("Couldn't open the billing portal. Please email hello@studiamo.cloud.");
        }
    }
}


window.openPaywall = openPaywall;
window.notifyPaymentRequired = notifyPaymentRequired;
window.closePaywall = closePaywall;
window.declineStandardPrice = declineStandardPrice;
window.logoutFromPaywall = logoutFromPaywall;
window.startCheckout = startCheckout;
window.initPaywall = initPaywall;
window.renderSubscriptionCard = renderSubscriptionCard;
window.renderTesterPill = renderTesterPill;
window.closeTesterNotice = closeTesterNotice;
window.maybeShowTesterNotice = maybeShowTesterNotice;
window.sendTesterFeedback = sendTesterFeedback;
window.openBillingPortal = openBillingPortal;
