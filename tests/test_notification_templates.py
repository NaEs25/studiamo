"""
Every reminder text renders with realistic data, fits a push notification, and follows the
copy rules. Runs over the whole list, so a new or edited variant is checked automatically.
"""
import pytest

from app import notification_templates as nt

LONG_TITLE = "How the Federal Reserve sets interest rates and why it matters for you"


def _render_worst_case(t):
    return nt.render(t, count=12, titles=[LONG_TITLE, "Second", "Third"], streak=123, eaten=14)


@pytest.mark.parametrize("t", nt.TEMPLATES, ids=lambda t: t.id)
def test_renders_within_push_limits(t):
    title, body = _render_worst_case(t)
    assert "{" not in title + body and "}" not in title + body
    assert len(title) <= nt.MAX_TITLE_CHARS, title
    assert len(body) <= nt.MAX_BODY_CHARS, body


@pytest.mark.parametrize("t", nt.TEMPLATES, ids=lambda t: t.id)
def test_copy_rules(t):
    text = t.title + " " + t.body
    assert "\u2014" not in text, "no em dashes"
    assert t.kind in nt.CASES and t.case in nt.CASES[t.kind]
    assert t.style in {"neutral", "playful", "progress", "chompy"}


def test_ids_are_unique():
    ids = [t.id for t in nt.TEMPLATES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("kind, case", [(k, c) for k, cases in nt.CASES.items() for c in cases])
def test_every_situation_has_an_active_variant(kind, case):
    assert nt.active_templates(kind, case)


def test_singular_and_plural():
    t = nt.Template("x", "daily", "default", "neutral", "t", "{quizzes} / {eaten}")
    assert nt.render(t, count=1, eaten=1)[1] == "1 quiz / 1 quiz"
    assert nt.render(t, count=3, eaten=4)[1] == "3 quizzes / 4 quizzes"


def test_title_placeholder_quotes_truncates_and_counts_the_rest():
    t = nt.Template("x", "save", "chompy", "neutral", "t", "{title}")
    assert nt.render(t, titles=["Short"])[1] == "'Short'"
    assert nt.render(t, titles=["Short", "B", "C"])[1] == "'Short' and 2 more"
    long_quoted = nt.render(t, titles=[LONG_TITLE])[1]
    assert long_quoted.endswith("…'") and len(long_quoted) <= nt.MAX_QUOTED_TITLE_CHARS + 2
