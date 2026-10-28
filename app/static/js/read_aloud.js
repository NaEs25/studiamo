// --- Read-aloud button on guide pages ---
// Uses the browser's own speech synthesis, so the text never leaves the device. The article is
// spoken one sentence per utterance: Chrome cuts a single long utterance off after roughly 15
// seconds, and short utterances also let Stop take effect at once. The Related line and the
// Sources list are skipped, since links and DOIs read aloud are noise.
document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('read-aloud');
    const article = document.getElementById('article');
    if (!button || !article || !('speechSynthesis' in window)) return;

    const synth = window.speechSynthesis;
    const lang = document.documentElement.lang || 'en';
    const startIcon = button.querySelector('[data-read-aloud-icon="start"]');
    const stopIcon = button.querySelector('[data-read-aloud-icon="stop"]');
    // Bumped on every start and stop, so callbacks from a cancelled run do nothing.
    let run = 0;

    function sentences() {
        const out = [];
        for (const el of article.querySelectorAll('h1, .cp-body h2, .cp-body p, .cp-body li')) {
            const text = el.textContent.replace(/\s+/g, ' ').trim();
            if (el.tagName === 'H2' && text === 'Sources') break;
            if (text.startsWith('Related:')) continue;
            // Split after . ! or ? followed by a space, so "1.5" stays whole.
            if (text) out.push(...text.split(/(?<=[.!?])\s+/));
        }
        return out;
    }

    function setReading(on) {
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
        button.title = on ? 'Stop reading' : 'Read aloud';
        startIcon.classList.toggle('hidden', on);
        stopIcon.classList.toggle('hidden', !on);
    }

    function stop() {
        run += 1;
        synth.cancel();
        setReading(false);
    }

    function speak(parts, i, token) {
        if (token !== run) return;
        if (i >= parts.length) {
            setReading(false);
            return;
        }
        const utterance = new SpeechSynthesisUtterance(parts[i]);
        utterance.lang = lang;
        utterance.onend = () => speak(parts, i + 1, token);
        utterance.onerror = (e) => {
            if (token === run && e.error !== 'interrupted' && e.error !== 'canceled') stop();
        };
        synth.speak(utterance);
    }

    function start() {
        run += 1;
        synth.cancel();
        setReading(true);
        speak(sentences(), 0, run);
    }

    button.addEventListener('click', () => {
        if (button.getAttribute('aria-pressed') === 'true') stop();
        else start();
    });
    // Some browsers keep talking after the reader navigates away.
    window.addEventListener('pagehide', () => synth.cancel());
    button.classList.remove('hidden');
});
