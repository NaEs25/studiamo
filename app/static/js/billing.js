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
    ['paywall-step-standard', 'paywall-step-beta', 'paywall-step-activating', 'paywall-step-pending']
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


/**
 * Called by fetchAPI when any request returns 402, i.e. access lapsed mid-session.
 *
 * Opens the paywall only if it is not already showing. openPaywall() defaults to step 1,
 * so calling it unconditionally would yank a user who is reading the discounted offer
 * back to the default screen the moment any background request returned 402, losing the
 * offer they were about to accept.
 */
function notifyPaymentRequired() {
    const overlay = document.getElementById('overlay-paywall');
    if (!overlay || !overlay.classList.contains('hidden')) return;
    openPaywall();
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
 * There is one checkout URL. The promotional code is displayed in our own UI and typed in
 * at checkout rather than pre-applied, because Lemon Squeezy renders an applied discount
 * below its pay button, where someone who does not scroll never sees it.
 */
async function startCheckout() {
    _paywallError('');
    try {
        const data = await fetchAPI('/api/billing/checkout');
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
        // Populated before the modal opens, so the code is already on screen rather than
        // appearing a moment after the user starts reading.
        renderDiscountNote(status && status.beta_discount_code);
        if (status && !status.has_access) openPaywall();
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
    const note = document.getElementById('paywall-discount-note');
    const target = document.getElementById('paywall-discount-code');
    if (!note || !target) return;
    if (!code) {
        note.classList.add('hidden');
        return;
    }
    target.textContent = code;
    note.classList.remove('hidden');
}


/** The same note as an HTML string, for the action area of the Settings card. */
function _discountNoteMarkup(code) {
    if (!code) return '';
    return `
        <div class="discount-note">
            <i data-lucide="ticket" class="w-4 h-4 flex-shrink-0"></i>
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
    }

    textEl.textContent = preset.text;
    badgeEl.textContent = preset.label;
    // Toggle the variant only. The shape classes stay in the template, where they are
    // declared once.
    badgeEl.classList.remove(...STATUS_BADGE_VARIANTS);
    badgeEl.classList.add(preset.variant);

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
window.openBillingPortal = openBillingPortal;
