// --- Waitlist confirmation page (/waitlist-confirmation?ref=<code>) ---
// Loads the referral status for the code in the URL and wires up the two copy
// buttons. Both copies are reported to Umami so the referral funnel can be read
// end to end: copy -> click on the shared link -> completed signup.

function trackReferral(event, data) {
    if (window.umami) window.umami.track(event, data);
}

function flashCopied(labelEl, original) {
    labelEl.textContent = 'Copied!';
    setTimeout(() => { labelEl.textContent = original; }, 1500);
}

function copyAndTrack(text, labelEl, what) {
    // Older browsers and insecure contexts reject here. Report the failure
    // rather than counting it as a copy, otherwise the funnel overstates
    // how many people walked away with a usable link.
    navigator.clipboard.writeText(text).then(() => {
        flashCopied(labelEl, 'Copy');
        trackReferral('referral-copy', { what: what });
    }).catch(() => {
        labelEl.textContent = 'Press Ctrl+C';
        setTimeout(() => { labelEl.textContent = 'Copy'; }, 2500);
        trackReferral('referral-copy-failed', { what: what });
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    if (window.lucide) lucide.createIcons();

    const params = new URLSearchParams(window.location.search);
    const ref = (params.get('ref') || '').trim();

    const loadingEl = document.getElementById('loading-state');
    const errorEl = document.getElementById('error-state');
    const readyEl = document.getElementById('ready-state');

    function showError(message) {
        loadingEl.classList.add('hidden');
        readyEl.classList.add('hidden');
        errorEl.textContent = message;
        errorEl.classList.remove('hidden');
    }

    if (!ref) {
        showError("We couldn't find your waitlist info. Please use the link from your confirmation email.");
        return;
    }

    try {
        const res = await fetch(`/api/waitlist-status?ref=${encodeURIComponent(ref)}`);
        if (!res.ok) {
            showError("We couldn't find your waitlist info. Please use the link from your confirmation email.");
            return;
        }
        const data = await res.json();

        const referralLink = `${window.location.origin}/join?ref=${ref}`;
        const shareMessage = `I'm on the waitlist for Studiamo, an AI-powered spaced repetition app for turning YouTube videos into active recall practice. Join me: ${referralLink}`;

        document.getElementById('referral-count').textContent = data.referral_count;
        document.getElementById('referral-link').value = referralLink;
        document.getElementById('share-message').textContent = shareMessage;

        loadingEl.classList.add('hidden');
        readyEl.classList.remove('hidden');

        document.getElementById('copy-link-btn').addEventListener('click', () => {
            copyAndTrack(referralLink, document.getElementById('copy-link-label'), 'link');
        });
        document.getElementById('copy-message-btn').addEventListener('click', () => {
            copyAndTrack(shareMessage, document.getElementById('copy-message-label'), 'message');
        });
    } catch (e) {
        showError("Something went wrong loading your waitlist info. Please try again shortly.");
    }
});
