"""Normalization of a goal's key concepts (app.routers.goals.parse_concepts): pure, no database."""
from app.routers.goals import MAX_CONCEPT_CHARS, MAX_GOAL_CONCEPTS, parse_concepts


def test_splits_trims_and_dedupes_case_insensitively():
    assert parse_concepts(" Layers ,typography,, LAYERS ,\nColor  theory ") == ["Layers", "typography", "Color theory"]


def test_accepts_a_list_and_empty_values():
    assert parse_concepts(["a", " b ", ""]) == ["a", "b"]
    assert parse_concepts(None) == []
    assert parse_concepts("") == []


def test_caps_count_and_length():
    many = ",".join(f"c{i}" for i in range(MAX_GOAL_CONCEPTS + 5))
    assert len(parse_concepts(many)) == MAX_GOAL_CONCEPTS
    assert len(parse_concepts("x" * (MAX_CONCEPT_CHARS + 20))[0]) == MAX_CONCEPT_CHARS
