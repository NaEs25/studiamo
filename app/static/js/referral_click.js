// --- Referral link arrivals ---
// /join is a bare redirect that renders no HTML, so a click on a shared
// referral link would never reach analytics on its own. serve_join() tags its
// redirect to /login with utm_source=referral, and this turns that tag into an
// event carrying where the click came from and how the link was shared.
document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('utm_source') !== 'referral' || !window.umami) return;

    let from = 'direct';
    if (document.referrer) {
        try {
            from = new URL(document.referrer).hostname;
        } catch (e) {
            from = 'unknown';
        }
    }

    window.umami.track('referral-link-open', {
        shared_via: params.get('utm_content') || 'link',
        from: from,
    });
});
