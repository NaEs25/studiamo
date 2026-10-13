"""
Which cards a quiz serves (dependencies.select_stage_questions) and how multiple-choice cards are
edited. Pure functions over a pool; no database.
"""
import pytest

from app import dependencies as dep


def card(stage, n, origin=None, recommended=False, options=None):
    item = {"topic": "T", "question": f"q{stage}-{n}", "answer": "a", "stage": stage,
            "ai_recommended": recommended}
    if origin:
        item["origin"] = origin
        item["card_id"] = f"own{stage}{n}"
    if options:
        item["options"] = options
        item["correct_index"] = 0
    return item


def ids(items):
    return [q["question"] for q in items]


def test_own_cards_are_served_before_recommended_and_the_rest():
    pool = [card(2, 1), card(2, 2, recommended=True), card(2, 3, origin="human", recommended=True)]
    assert ids(dep.select_stage_questions(pool, 2)) == ["q2-3", "q2-2", "q2-1"]


def test_limit_pauses_the_cards_past_it_without_dropping_them_from_the_pool():
    pool = [card(2, n) for n in range(8)]
    assert len(dep.select_stage_questions(pool, 2, limit=6)) == 6
    assert len(pool) == 8


def test_a_stage_with_too_few_cards_is_topped_up_from_other_stages():
    pool = [card(1, 1), card(1, 2)] + [card(s, n) for s in (0, 2, 3, 4) for n in range(4)]
    served = dep.select_stage_questions(pool, 1, limit=5, fill_seed=42)
    assert len(served) == 5
    assert ids(served)[:2] == ["q1-1", "q1-2"]
    assert len(set(ids(served))) == 5


def test_the_top_up_is_the_same_on_every_request_and_changes_with_the_seed():
    pool = [card(1, 1)] + [card(s, n) for s in (0, 2, 3, 4) for n in range(6)]
    first = ids(dep.select_stage_questions(pool, 1, limit=6, fill_seed=7))
    again = ids(dep.select_stage_questions(pool, 1, limit=6, fill_seed=7))
    other = ids(dep.select_stage_questions(pool, 1, limit=6, fill_seed=8))
    assert first == again
    assert first != other


def test_no_top_up_without_a_seed_or_with_a_saved_topic_selection():
    pool = [card(1, 1)] + [card(0, n) for n in range(5)]
    assert len(dep.select_stage_questions(pool, 1, limit=4)) == 1
    pool[0]["topic"] = "Chosen"
    served = dep.select_stage_questions(pool, 1, {"stage_1": ["Chosen"]}, limit=4, fill_seed=3)
    assert ids(served) == ["q1-1"]


def test_an_empty_stage_still_falls_back_to_the_nearest_lower_stage():
    pool = [card(0, n) for n in range(3)]
    assert len(dep.select_stage_questions(pool, 3, limit=5, fill_seed=1)) == 3


OPTIONS = ["one", "two", "three", "four"]


def mc_pool():
    return [card(0, 1, options=list(OPTIONS)), card(0, 2)]


def card_id(pool, question):
    return dep.card_id_of(next(q for q in pool if q["question"] == question))


def test_options_of_a_multiple_choice_card_can_be_edited_and_set_the_answer():
    pool = mc_pool()
    new_pool, edited = dep.edit_card_in_pool(pool, card_id(pool, "q0-1"), options=["a", "b", "c", "d"], correct_index=2)
    assert edited["options"] == ["a", "b", "c", "d"] and edited["correct_index"] == 2
    assert edited["answer"] == "c" and edited.get("edited_at")


@pytest.mark.parametrize("options, index", [
    (["a", "b", "c"], 0),
    (["a", "b", "c", ""], 0),
    (["a", "a", "c", "d"], 0),
    (["a", "b", "c", "d"], 4),
    (["a", "b", "c", "d"], None),
    ("not a list", 0),
])
def test_bad_options_are_refused(options, index):
    pool = mc_pool()
    with pytest.raises(dep.CardEditError):
        dep.edit_card_in_pool(pool, card_id(pool, "q0-1"), options=options, correct_index=index)


def test_a_plain_card_cannot_be_given_options():
    pool = mc_pool()
    with pytest.raises(dep.CardEditError):
        dep.edit_card_in_pool(pool, card_id(pool, "q0-2"), options=list(OPTIONS), correct_index=0)


def test_listing_marks_which_cards_are_served_and_how_many_are_borrowed():
    from app.routers.videos import _build_focus_stages
    pool = [card(1, 1)] + [card(0, n) for n in range(4)] + [card(2, n) for n in range(8)]
    stages = {s["stage"]: s for s in _build_focus_stages(pool, {}, 5, 11)}
    assert len(stages[2]["served"]) == 5 and stages[2]["filled"] == 0
    assert stages[2]["total_questions"] == 8
    assert len(stages[1]["served"]) == 5 and stages[1]["filled"] == 4
    assert stages[1]["served"] == _build_focus_stages(pool, {}, 5, 11)[1]["served"]
