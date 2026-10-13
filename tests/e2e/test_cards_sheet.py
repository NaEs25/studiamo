"""
The card editor sheet (cards.js): per-stage counts, paused cards, adding and editing cards, and
multiple-choice options. Runs against canned answers for the dashboard and the card endpoints, so
nothing is written.
"""
import json

import pytest

from tests.e2e.conftest import GOALS_DASHBOARD


def _card(cid, question, origin="ai", options=None, correct=None, edited=False):
    return {"id": cid, "question": question, "answer": "an answer", "origin": origin, "edited": edited,
            "options": options, "correct_index": correct}


def _stage(stage, cards, served, filled=0):
    return {"stage": stage, "label": f"Stage {stage}", "served": served, "filled": filled, "total_questions": len(cards),
            "selected_questions": len(cards), "has_saved_selection": False,
            "topics": [{"topic": "Topic", "count": len(cards), "recommended": True, "selected": True, "questions": cards}]}


POOL = {
    "video_id": 8001, "quiz_id": 1, "title": "Helm charts explained", "current_stage": 1, "target_count": 2,
    "stages": [
        _stage(0, [_card("m1", "Which scope?", options=["a", "b", "c", "d"], correct=1)], ["m1"]),
        _stage(1, [_card("c1", "Card one", origin="human"), _card("c2", "Card two"), _card("c3", "Card three")], ["c1", "c2"]),
    ],
}


@pytest.fixture
def cards_page(logged_in_page):
    page = logged_in_page
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(GOALS_DASHBOARD)))
    page.route("**/api/videos/8001/concept-pool", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(POOL)))
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    page.evaluate("openCardsSheet(8001)")
    page.wait_for_selector("#overlay-cards:not(.hidden)")
    return page


def test_sheet_shows_counts_and_greys_out_cards_past_the_star_rating(cards_page):
    page = cards_page
    assert "Stage" in page.text_content("#cards-list")
    pills = page.locator("[data-cards-stage]")
    assert pills.nth(1).text_content().replace(" ", "") == "1·3"
    assert "reviews 2 of its 3 cards" in page.text_content("#cards-list")
    assert page.locator("#cards-list .border-dashed.opacity-60").count() == 1
    assert "Card three" in page.locator("#cards-list .border-dashed.opacity-60").text_content()


def test_adding_a_card_posts_front_back_and_topic(cards_page):
    page = cards_page
    sent = []
    page.route("**/api/videos/8001/cards", lambda route: (
        sent.append(route.request.post_data),
        route.fulfill(status=200, content_type="application/json", body=json.dumps(POOL))))
    page.click("[data-cards-add]")
    page.fill("[data-cards-field='question']", "What does a LUT do?")
    page.fill("[data-cards-field='answer']", "Maps colors.")
    page.click("[data-cards-save]")
    page.wait_for_timeout(500)
    assert sent and 'name="question"' in sent[0] and "What does a LUT do?" in sent[0] and 'name="stage"' in sent[0]


def test_multiple_choice_options_are_edited_and_sent_as_json(cards_page):
    page = cards_page
    sent = []
    page.route("**/api/videos/8001/cards/m1", lambda route: (
        sent.append(route.request.post_data),
        route.fulfill(status=200, content_type="application/json", body=json.dumps(POOL))))
    page.click("[data-cards-stage='0']")
    page.click("[data-cards-edit='m1']")
    page.fill("[data-cards-option='2']", "changed option")
    page.locator("[data-cards-correct]").nth(3).check()
    page.click("[data-cards-save]")
    page.wait_for_timeout(500)
    assert sent and 'name="options"' in sent[0] and "changed option" in sent[0]
    assert 'name="correct_index"' in sent[0] and "\r\n3\r\n" in sent[0]


def test_removing_needs_a_second_tap_and_works_on_a_phone_sized_screen(cards_page):
    page = cards_page
    page.set_viewport_size({"width": 390, "height": 800})
    deleted = []
    page.route("**/api/videos/8001/cards/c2", lambda route: (
        deleted.append(route.request.method),
        route.fulfill(status=200, content_type="application/json", body=json.dumps(POOL))))
    page.click("[data-cards-remove='c2']")
    assert not deleted
    page.click("[data-cards-remove='c2']")
    page.wait_for_timeout(500)
    assert deleted == ["DELETE"]
