"""
Adding a recommended video to a goal from the recommendations drawer (goals.js
importGoalRecommendation). Runs on the goals_page fixture (tests/e2e/conftest.py); the
recommendations and the save endpoint are answered by the test, so nothing is read from or
written to the test account and no YouTube lookup happens.
"""
import json

RECS = {
    "key_concepts": ["Pods", "Services"],
    "videos": [
        {"youtube_id": "aaaaaaaaaaa", "title": "First recommended", "thumbnail": "", "duration": "10:00"},
        {"youtube_id": "bbbbbbbbbbb", "title": "Second recommended", "thumbnail": "", "duration": "8:00"},
    ],
}


def _answer(page, save_body):
    saves = []

    def save(route):
        saves.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json", body=json.dumps(save_body))

    page.route("**/api/goals/9001/recommendations", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(RECS)))
    page.route("**/api/videos/save", save)
    return saves


def _open_drawer(page):
    """The recommendations controls live on the goal page, not on the card."""
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.click("#goal-page #btn-recs-trigger-9001")
    page.wait_for_selector("#rec-card-9001-aaaaaaaaaaa", timeout=10000)


def test_added_recommendation_leaves_the_drawer(goals_page):
    page = goals_page
    saves = _answer(page, {"status": "success", "video_id": 1})
    _open_drawer(page)

    page.click("#rec-card-9001-aaaaaaaaaaa [data-goal-action='import-rec']")
    page.wait_for_selector("#rec-card-9001-aaaaaaaaaaa", state="detached", timeout=10000)
    assert len(saves) == 1 and "aaaaaaaaaaa" in saves[0]
    assert page.locator("#rec-card-9001-bbbbbbbbbbb").count() == 1

    # A redraw of the goals (the import reloads them) does not bring the card back.
    page.evaluate("loadGoals()")
    page.wait_for_timeout(500)
    assert page.locator("#rec-card-9001-aaaaaaaaaaa").count() == 0


def test_already_owned_recommendation_says_so_and_leaves_the_drawer(goals_page):
    page = goals_page
    _answer(page, {"status": "success", "video_id": 1, "already_existed": True})
    _open_drawer(page)

    page.click("#rec-card-9001-aaaaaaaaaaa [data-goal-action='import-rec']")
    page.wait_for_selector("#rec-card-9001-aaaaaaaaaaa", state="detached", timeout=10000)
    assert "already in your library" in page.inner_text("body")


def test_added_recommendation_leaves_the_drawer_on_the_goal_page(goals_page):
    page = goals_page
    _answer(page, {"status": "success", "video_id": 1})
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.wait_for_selector("#goal-page [data-goal-action='load-recs']", timeout=10000)
    page.click("#goal-page [data-goal-action='load-recs']")
    page.wait_for_selector("#goal-page #rec-card-9001-aaaaaaaaaaa", timeout=10000)

    page.click("#goal-page #rec-card-9001-aaaaaaaaaaa [data-goal-action='import-rec']")
    page.wait_for_selector("#goal-page #rec-card-9001-aaaaaaaaaaa", state="detached", timeout=10000)
    page.wait_for_timeout(500)
    assert page.locator("#goal-page #rec-card-9001-aaaaaaaaaaa").count() == 0
    assert page.locator("#goal-page #rec-card-9001-bbbbbbbbbbb").count() == 1
