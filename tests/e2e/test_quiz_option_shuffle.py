"""
Multiple-choice quiz options are shuffled when rendered, so the correct answer is not always
the same letter, and the remapped correct_index still points at the right option text.
"""


def _render(page, question):
    page.goto("/app")
    page.wait_for_selector("#nav-dashboard", timeout=15000)
    return page.evaluate("""q => {
        const wrap = document.getElementById('quiz-options');
        renderQuizOptions(q);
        renderQuizOptions(q);
        const shown = [...wrap.querySelectorAll('.grow')].map(el => el.textContent);
        return { shown, options: q.options, correct: q.correct_index };
    }""", question)


def test_shuffle_keeps_correct_option_and_is_stable(logged_in_page):
    question = {"options": ["right", "w1", "w2", "w3"], "correct_index": 0}
    out = _render(logged_in_page, question)
    assert sorted(out["shown"]) == ["right", "w1", "w2", "w3"]
    assert out["shown"] == out["options"]
    assert out["options"][out["correct"]] == "right"


def test_correct_letter_is_not_constant(logged_in_page):
    page = logged_in_page
    page.goto("/app")
    page.wait_for_selector("#nav-dashboard", timeout=15000)
    positions = page.evaluate("""() => {
        const wrap = document.getElementById('quiz-options');
        const seen = [];
        for (let n = 0; n < 40; n++) {
            const q = { options: ['right', 'a', 'b', 'c'], correct_index: 0 };
            renderQuizOptions(q);
            seen.push(q.correct_index);
        }
        return seen;
    }""")
    assert len(set(positions)) > 1
