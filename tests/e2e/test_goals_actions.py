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

    # A card carries no buttons of its own: no materials list, options menu, plus or arrow.
    assert page.locator("[data-goal-card='9001'] button:not([data-goal-action='open-goal'])").count() == 0
    assert page.locator("#goal-materials-content-9001").count() == 0

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

    # Clicking anywhere on a card opens its goal page, where Edit lives.
    page.click("[data-goal-card='9002'] h3")
    page.click("#goal-page [data-goal-action='edit']")
    assert page.locator("#overlay-goal-modal").is_visible()
    assert page.input_value("#goal-modal-title") == "Spanish"


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

    # The recommendations controls live on the goal page, not on the card.
    assert page.locator("[data-goal-card='9001'] #btn-recs-trigger-9001").count() == 0
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.click("#goal-page #btn-recs-trigger-9001")
    card = page.locator("#rec-card-9001-abc123XYZ_-")
    card.wait_for(timeout=10000)
    # The title travels through data attributes intact, quotes and angle brackets included.
    assert card.locator("[data-goal-action='import-rec']").get_attribute("data-title") == rec["title"]

    # Concepts come from AI output and are shown as text, not markup.
    assert page.text_content("#concepts-9001").strip() == "Pods & <Services>"

    with page.expect_request("**/api/goals/9001/recommendations/replace_one"):
        card.locator("[data-goal-action='dismiss-rec']").click()

    # The same button hides the drawer again.
    page.click("#goal-page #btn-recs-trigger-9001")
    assert not page.locator("#recs-9001").is_visible()


def test_edit_dialog_holds_archive_and_delete_for_an_existing_goal_only(goals_page):
    page = goals_page
    page.click("#btn-add-goal-modal")
    assert page.locator("#btn-goal-modal-archive").is_hidden()
    page.click("#btn-close-goal-modal")

    calls = []
    _record_posts(page, "**/api/goals/*/archive", calls)
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.click("#goal-page [data-goal-action='edit']")
    assert page.locator("#btn-goal-modal-archive").is_visible() and page.locator("#btn-goal-modal-delete").is_visible()
    page.click("#btn-goal-modal-delete")
    assert page.locator("#overlay-goal-modal").is_hidden()
    assert page.locator("#overlay-delete-goal-modal").is_visible()
