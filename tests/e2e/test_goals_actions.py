"""
The goals tab's buttons are bound through one delegated listener (goals.js initGoalsActions)
instead of inline handlers. Runs on the goals_page fixture's fixed dashboard
(tests/e2e/conftest.py), and every write the buttons trigger is answered by a mocked route, so
nothing reaches the database.
"""
import json


def _record_posts(page, pattern, calls):
    def handle(route):
        calls.append((route.request.method, route.request.url))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "ok"}))
    page.route(pattern, handle)


def test_goal_card_buttons(goals_page):
    page = goals_page
    calls = []
    _record_posts(page, "**/api/goals/*/reorder", calls)
    _record_posts(page, "**/api/goals/*/archive", calls)

    # Materials fold out from the label button and from the chevron icon.
    materials = page.locator("#goal-materials-content-9001")
    was_open = materials.is_visible()
    page.click("[data-goal-card='9001'] button[data-goal-action='toggle-materials']")
    assert materials.is_visible() != was_open
    page.click("#goal-materials-chevron-9001")
    assert materials.is_visible() == was_open

    # Reorder lives in a sheet now: the first goal's "down" arrow posts, its "up" arrow is
    # disabled, and the cards themselves carry no rank arrows.
    assert page.locator("[data-goal-card='9001'] [data-direction]").count() == 0
    page.click("#btn-goals-reorder")
    assert page.locator("#overlay-goal-reorder").is_visible()
    assert page.locator("[data-reorder-row='9001'] [data-reorder-move='up']").is_disabled()
    with page.expect_request("**/api/goals/9001/reorder"):
        page.click("[data-reorder-row='9001'] [data-reorder-move='down']")
    page.click("#btn-goal-reorder-done")
    assert page.locator("#overlay-goal-reorder").is_hidden()
    page.wait_for_timeout(1500)  # the move reloads the goals; let that finish before the next click

    # The options menu opens and its items work.
    # The menu closes on any scroll, and the second goal's button sits under the fixed nav bar at
    # this viewport height, so Playwright would scroll right after the menu opens and dismiss it.
    # Scroll first, and let that settle.
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(400)
    page.click("#btn-goal-menu-9002")
    page.locator("#portal-goal-menu [data-goal-menu-action='edit']").click()
    assert page.locator("#overlay-goal-modal").is_visible()
    assert page.input_value("#goal-modal-title") == "Spanish"
    assert page.locator("#portal-goal-menu").count() == 0


def test_accordions_and_archive(goals_page):
    page = goals_page
    calls = []
    _record_posts(page, "**/api/goals/*/archive", calls)

    queue = page.locator("#content-watchlist")
    before = queue.is_visible()
    page.click("[data-goal-action='toggle-accordion'][data-cat='watchlist']")
    assert queue.is_visible() != before

    loose = page.locator("#content-unassociated")
    before = loose.is_visible()
    page.click("[data-goal-action='toggle-accordion'][data-cat='unassociated']")
    assert loose.is_visible() != before

    page.click("#goals-archived-section > button")
    with page.expect_request("**/api/goals/9003/archive"):
        page.click("[data-archived-goal='9003'] [data-goal-action='archive']")

    page.click("[data-archived-goal='9003'] [data-goal-action='delete']")
    assert page.locator("#overlay-delete-goal-modal").is_visible()
    assert "Old Photography Course" in page.text_content("#delete-goal-modal-msg")


def test_recommendation_cards(goals_page):
    page = goals_page
    rec = {"youtube_id": "abc123XYZ_-", "title": "Kubernetes \"in\" 10 minutes, it's <easy>",
           "thumbnail": "", "url": "https://www.youtube.com/watch?v=abc123XYZ_-"}
    page.route("**/api/goals/9001/recommendations", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"videos": [rec], "key_concepts": ["Pods & <Services>"]})))
    calls = []
    _record_posts(page, "**/api/goals/9001/recommendations/replace_one", calls)

    page.click("#btn-recs-trigger-9001")
    card = page.locator("#rec-card-9001-abc123XYZ_-")
    card.wait_for(timeout=10000)
    # The title travels through data attributes intact, quotes and angle brackets included.
    assert card.locator("[data-goal-action='import-rec']").get_attribute("data-title") == rec["title"]

    # Concepts come from AI output and are shown as text, not markup.
    assert page.text_content("#concepts-9001").strip() == "Pods & <Services>"

    with page.expect_request("**/api/goals/9001/recommendations/replace_one"):
        card.locator("[data-goal-action='dismiss-rec']").click()

    page.click("[data-goal-card='9001'] [data-goal-action='close-recs']")
    assert not page.locator("#recs-9001").is_visible()
