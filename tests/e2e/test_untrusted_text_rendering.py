"""
Text from outside the app (YouTube titles, the user's own goal text) must reach the page as
text and reach the click handlers unchanged, whatever characters it holds.

The recommendation test serves its data through page.route, so no request reaches the
backend and nothing is written. The goal test writes one goal as the test account and
deletes it again, like test_goals_flow.py.
"""
import json
import uuid

HOSTILE_TITLES = [
    "Backslash quote \\');window.__injected=1;//",
    "Attribute break \"><img src=x onerror=\"window.__injected=2\">",
    "Plain <b>markup</b> & an ampersand",
]


def _console_errors(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


def test_recommendation_titles_stay_text_and_reach_handlers_unchanged(logged_in_page):
    page = logged_in_page
    errors = _console_errors(page)
    recs = [
        {"youtube_id": f"vid{i:08d}", "title": title, "goal_id": "", "goal_title": "<i>goal</i>",
         "views": "1K", "duration": "3:00"}
        for i, title in enumerate(HOSTILE_TITLES)
    ]
    page.route("**/api/daily-recommendations", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"date": "today", "recommendations": recs}),
    ))

    posted = []

    def capture_preview(route):
        posted.append(route.request.post_data or "")
        route.fulfill(status=500, content_type="application/json", body='{"detail": "intercepted"}')

    page.route("**/api/videos/preview", capture_preview)

    # The dashboard only loads recommendations for an account with goals, and the test account
    # has none, so the real loader is called directly once the dashboard has settled.
    with page.expect_response("**/api/dashboard", timeout=30000):
        page.goto("/app")
    page.wait_for_load_state("networkidle")
    page.evaluate("""() => {
        document.getElementById('daily-recommendations-panel').classList.remove('hidden');
        return loadDailyRecommendations();
    }""")
    page.wait_for_selector("[data-rec-yt]", timeout=15000)

    for i, title in enumerate(HOSTILE_TITLES):
        card = page.locator(f"[data-rec-yt='vid{i:08d}']")
        assert card.locator("h4").inner_text().strip() == title
        assert card.get_attribute("data-rec-title") == title
        with page.expect_request("**/api/videos/preview"):
            card.locator("[data-rec-action='queue']").click()

    assert page.evaluate("window.__injected") is None
    assert page.locator("[data-rec-yt] img[src='x']").count() == 0
    for title, body in zip(HOSTILE_TITLES, posted):
        assert title in body
    assert errors == []


def test_goal_with_quotes_and_line_breaks_opens_in_edit(logged_in_page):
    page = logged_in_page
    errors = _console_errors(page)
    tag = uuid.uuid4().hex[:8]
    title = f"E2E \"Quote\" O'Brien \\ <b>x</b> {tag}"
    description = "First line with 'single' and \"double\" quotes\nSecond line \\ backslash"

    page.goto("/app")
    page.click("#nav-goals")
    page.click("#btn-add-goal-modal")
    page.wait_for_selector("#goal-modal-title", state="visible", timeout=10000)
    page.fill("#goal-modal-title", title)
    page.fill("#goal-modal-desc", description)
    with page.expect_response(lambda r: r.url.endswith("/api/goals") and r.request.method == "POST", timeout=30000):
        page.click("#goal-modal-form button[type=submit]")

    heading = page.get_by_role("heading", name=title)
    heading.wait_for(timeout=15000)
    card = heading.locator("xpath=ancestor::*[.//button[starts-with(@id, 'btn-goal-menu-')]][1]")

    try:
        card.locator("[id^='btn-goal-menu-']").click()
        page.locator("#portal-goal-menu").get_by_text("Edit Title", exact=False).click()
        page.wait_for_selector("#goal-modal-title", state="visible", timeout=10000)
        assert page.input_value("#goal-modal-title") == title
        assert page.input_value("#goal-modal-desc") == description
        page.keyboard.press("Escape")
        page.wait_for_selector("#goal-modal-title", state="hidden", timeout=10000)
    finally:
        card.locator("[id^='btn-goal-menu-']").click()
        page.locator("#portal-goal-menu").get_by_text("Permanently Delete", exact=False).click()
        assert title in page.inner_text("#delete-goal-modal-msg")
        with page.expect_response(lambda r: "/api/goals/" in r.url and r.request.method == "DELETE", timeout=20000):
            page.get_by_text("Delete Goal & All Linked Materials", exact=False).click()
        heading.wait_for(state="detached", timeout=15000)

    assert errors == []
