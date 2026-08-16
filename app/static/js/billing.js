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
    sessionStorage.removeItem('profile_password');
    document.cookie = 'username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    document.cookie = 'profile_password=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    window.location.href = '/login';
}


/**
 * Sends the user to Lemon Squeezy checkout.
 *
 * `beta` applies promotional discount configuration when requested.
 */
async function startCheckout(beta = false) {
    _paywallError('');
    try {
        const data = await fetchAPI(`/api/billing/checkout?beta=${beta ? 'true' : 'false'}`);
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
        if (status && !status.has_access) openPaywall();
    } catch (e) {
        // A failed status check must not lock anyone out of an app they have paid for.
        // The server-side dependency is the real gate; this is only the explanation.
        console.warn('Billing status check failed, not showing paywall:', e);
    }
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
    const isTester = !!(settings && settings.is_tester);

    const PRESETS = {
        active:    { label: 'Active',      cls: 'bg-emerald-100 text-emerald-700', text: 'Your subscription is active.' },
        on_trial:  { label: 'Trial',       cls: 'bg-emerald-100 text-emerald-700', text: 'You are on a free trial.' },
        past_due:  { label: 'Payment due', cls: 'bg-amber-100 text-amber-700',     text: "Your last payment failed. Update your card to avoid losing access." },
        cancelled: { label: 'Ending',      cls: 'bg-amber-100 text-amber-700',     text: 'Cancelled: you keep access until the end of the paid period.' },
        paused:    { label: 'Paused',      cls: 'bg-stone-200 text-stone-600',     text: 'Your subscription is paused.' },
        unpaid:    { label: 'Unpaid',      cls: 'bg-red-100 text-red-700',         text: 'Your subscription is unpaid.' },
        expired:   { label: 'Expired',     cls: 'bg-stone-200 text-stone-600',     text: 'Your subscription has expired.' },
        inactive:  { label: 'None',        cls: 'bg-stone-200 text-stone-600',     text: 'You do not have an active subscription.' },
    };

    let preset = PRESETS[status] || PRESETS.inactive;
    if (isTester) {
        preset = { label: 'Tester', cls: 'bg-indigo-100 text-indigo-700', text: 'You have free tester access.' };
    }

    textEl.textContent = preset.text;
    badgeEl.textContent = preset.label;
    badgeEl.className =
        'text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-md ' + preset.cls;

    if (!actionEl) return;

    // Testers have no Lemon Squeezy subscription to manage, and nothing to buy.
    if (isTester) {
        actionEl.innerHTML = '';
        return;
    }

    const hasSubscription = status !== 'inactive';
    if (hasSubscription) {
        actionEl.innerHTML = `
            <button type="button" onclick="openBillingPortal()"
                class="w-full py-2.5 px-4 bg-stone-100 hover:bg-stone-200 border border-[#e7dfd3] rounded-xl text-xs font-bold text-stone-700 transition flex items-center justify-center space-x-2">
                <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                <span>Manage subscription</span>
            </button>`;
    } else {
        actionEl.innerHTML = `
            <button type="button" onclick="startCheckout(false)"
                class="w-full py-2.5 px-4 bg-amber-500 hover:bg-amber-600 rounded-xl text-xs font-extrabold text-stone-950 transition flex items-center justify-center space-x-2">
                <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
                <span>Subscribe ($7.99 / month)</span>
            </button>`;
    }
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
