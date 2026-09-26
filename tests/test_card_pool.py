"""
Pure-function tests for the concept-pool card helpers behind the Learning Focus overlay's
add and remove. No database: the row-locking wrapper is exercised on staging, this covers the
rules that decide what a pool looks like afterwards.
"""
import pytest

from app.dependencies import (
    CardEditError,
    MAX_POOL_CARDS,
    add_card_to_pool,
    card_id_of,
    edit_card_in_pool,
    remove_card_from_pool,
    rename_topic_in_pool,
    select_stage_questions,
)


def _ai(question, topic="Algorithms", stage=0, recommended=False):
    return {"topic": topic, "question": question, "answer": "a", "explanation": "",
            "timestamp_seconds": 0, "ai_recommended": recommended, "stage": stage}


def test_added_card_is_human_and_lands_ahead_of_its_topic():
    pool = [_ai("q1", "Other"), _ai("q2"), _ai("q3")]
    new_pool, card = add_card_to_pool(pool, 0, "Algorithms", "Mine?", "Yes")

    assert card["origin"] == "human"
    assert card["ai_recommended"] is True
    assert card["stage"] == 0 and "options" not in card
    assert [q["question"] for q in new_pool] == ["q1", "Mine?", "q2", "q3"]


def test_added_card_survives_the_per_session_prefix_cut():
    pool = [_ai(f"q{i}", recommended=True) for i in range(6)]
    new_pool, card = add_card_to_pool(pool, 0, "Algorithms", "Mine?", "Yes")

    served = select_stage_questions(new_pool, 0, None, limit=5)
    assert card in served


def test_new_topic_is_appended_and_existing_topic_matches_case_insensitively():
    pool = [_ai("q1")]
    _, card = add_card_to_pool(pool, 0, "algorithms", "Another?", "Yes")
    assert card["topic"] == "Algorithms"

    new_pool, card = add_card_to_pool(pool, 2, "Fresh topic", "Another?", "Yes")
    assert card["topic"] == "Fresh topic" and new_pool[-1] is card


@pytest.mark.parametrize("stage,topic,question,answer", [
    (5, "t", "q", "a"), (-1, "t", "q", "a"), ("x", "t", "q", "a"),
    (0, "", "q", "a"), (0, "t", "  ", "a"), (0, "t", "q", ""),
    (0, "t" * 61, "q", "a"), (0, "t", "q" * 501, "a"), (0, "t", "q", "a" * 1001),
])
def test_invalid_cards_are_rejected(stage, topic, question, answer):
    with pytest.raises(CardEditError) as err:
        add_card_to_pool([_ai("q1")], stage, topic, question, answer)
    assert err.value.status == 400


def test_duplicate_question_in_same_stage_and_topic_is_rejected():
    with pytest.raises(CardEditError) as err:
        add_card_to_pool([_ai("Same?")], 0, "Algorithms", " same? ", "a")
    assert err.value.status == 409

    # The same text in another stage is a different card.
    add_card_to_pool([_ai("Same?")], 1, "Algorithms", "Same?", "a")


def test_pool_size_is_capped():
    pool = [_ai(f"q{i}") for i in range(MAX_POOL_CARDS)]
    with pytest.raises(CardEditError) as err:
        add_card_to_pool(pool, 0, "Algorithms", "One more?", "a")
    assert err.value.status == 409


def test_ai_card_ids_are_stable_and_stored_ids_win():
    item = _ai("q1")
    assert card_id_of(item) == card_id_of(dict(item))
    assert card_id_of(item) != card_id_of(_ai("q2"))
    assert card_id_of({**item, "card_id": "abc123"}) == "abc123"


def test_remove_by_derived_and_stored_id():
    pool = [_ai("q1"), _ai("q2")]
    new_pool, removed = remove_card_from_pool(pool, card_id_of(pool[0]))
    assert [q["question"] for q in new_pool] == ["q2"] and removed["question"] == "q1"

    pool, card = add_card_to_pool(pool, 0, "Algorithms", "Mine?", "Yes")
    new_pool, removed = remove_card_from_pool(pool, card["card_id"])
    assert removed is card and card not in new_pool


def test_removing_unknown_card_is_404_and_last_card_is_protected():
    with pytest.raises(CardEditError) as err:
        remove_card_from_pool([_ai("q1"), _ai("q2")], "nope")
    assert err.value.status == 404

    with pytest.raises(CardEditError) as err:
        remove_card_from_pool([_ai("q1")], card_id_of(_ai("q1")))
    assert err.value.status == 409


def test_text_edit_keeps_identity_position_and_provenance():
    pool = [_ai("q1"), _ai("q2"), _ai("q3")]
    original_id = card_id_of(pool[1])

    new_pool, card = edit_card_in_pool(pool, original_id, question="q2 reworded", answer="new")

    assert [q["question"] for q in new_pool] == ["q1", "q2 reworded", "q3"]
    assert card["card_id"] == original_id and card_id_of(card) == original_id
    # AI cards carry no `origin` key (only human ones are stamped), and editing must not add one.
    assert "origin" not in card and card["edited_at"]
    # The same id still resolves after the derived inputs changed.
    remove_card_from_pool(new_pool, original_id)


def test_no_op_edit_does_not_stamp_edited_at():
    pool = [_ai("q1"), _ai("q2")]
    new_pool, card = edit_card_in_pool(pool, card_id_of(pool[0]), question="q1", answer="a")
    assert new_pool == pool and "edited_at" not in card


def test_topic_change_moves_card_ahead_of_new_topic_and_matches_case():
    pool = [_ai("a1", "Alpha"), _ai("b1", "Beta"), _ai("b2", "Beta")]
    new_pool, card = edit_card_in_pool(pool, card_id_of(pool[0]), topic="beta")

    assert card["topic"] == "Beta"
    assert [q["question"] for q in new_pool] == ["a1", "b1", "b2"]
    assert new_pool[0] is card


def test_edit_rejects_empty_fields_duplicates_and_unknown_cards():
    pool = [_ai("q1"), _ai("q2")]
    with pytest.raises(CardEditError):
        edit_card_in_pool(pool, card_id_of(pool[0]), question="  ")
    with pytest.raises(CardEditError):
        edit_card_in_pool(pool, card_id_of(pool[0]), topic="")
    with pytest.raises(CardEditError) as err:
        edit_card_in_pool(pool, card_id_of(pool[0]), question="Q2")
    assert err.value.status == 409
    with pytest.raises(CardEditError) as err:
        edit_card_in_pool(pool, "nope", question="x")
    assert err.value.status == 404


def test_rename_covers_every_stage_and_freezes_ids():
    pool = [_ai("q1", "Old", 0), _ai("q2", "Old", 2), _ai("q3", "Keep", 0)]
    ids = [card_id_of(q) for q in pool]

    new_pool, count = rename_topic_in_pool(pool, "Old", "Fresh")

    assert count == 2
    assert [q["topic"] for q in new_pool] == ["Fresh", "Fresh", "Keep"]
    # Derived ids depended on the topic, so they were frozen before the rename.
    assert [card_id_of(q) for q in new_pool] == ids
    assert "edited_at" not in new_pool[2]


def test_rename_allows_case_change_but_refuses_collision():
    pool = [_ai("q1", "Alpha"), _ai("q2", "Beta")]
    new_pool, count = rename_topic_in_pool(pool, "Alpha", "ALPHA")
    assert count == 1 and new_pool[0]["topic"] == "ALPHA"

    with pytest.raises(CardEditError) as err:
        rename_topic_in_pool(pool, "Alpha", "beta")
    assert err.value.status == 409
    with pytest.raises(CardEditError) as err:
        rename_topic_in_pool(pool, "Missing", "Whatever")
    assert err.value.status == 404
