"""
The free plan's screens (billing.js, app.js, core.js). The browser runs the real app against
canned answers for the billing status, the dashboard and the AI routes, so the test account
is never touched and nothing is written.
"""
import json

from tests.e2e.conftest import GOALS_DASHBOARD

FREE_STATUS = {
    "has_access": False, "plan": "free", "free_video": "available", "status": "inactive",
    "is_tester": False,
    "tester": {"state": "none", "granted_at": None, "expires_at": None, "period_days": None,
               "days_left": None, "unlimited": False, "legacy": False, "needs_welcome": False,
               "needs_reminder": None},
    "renews_at": None, "ends_at": None, "has_portal": False, "beta_discount_code": "",
}
PLAN_REQUIRED = {"detail": {"code": "ai_requires_plan", "message": "AI features need a plan. Pick a plan to use this feature."}}


def _json(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _free_app(logged_in_page):
    page = logged_in_page
    page.route("**/api/billing/status", lambda route: _json(route, FREE_STATUS))
    page.route("**/api/dashboard", lambda route: _json(route, GOALS_DASHBOARD))
    page.route("**/api/daily-recommendations", lambda route: _json(
        route, {"recommendations": [], "requires_plan": True, "date": "today"}))
    page.route("**/api/goals/9001/recommendations", lambda route: _json(route, PLAN_REQUIRED, 402))
    page.goto("/app")
    return page


def test_free_account_is_not_walled_and_sees_the_home_card(logged_in_page):
    page = _free_app(logged_in_page)
    page.wait_for_selector("[data-open-plans]", timeout=15000)
    assert page.locator("#overlay-paywall").is_hidden()
    assert "Video picks show up here" in page.text_content("#daily-recommendations-grid")
    assert page.locator("#btn-refresh-daily-recs").is_hidden()


def test_plan_picker_from_the_home_card_can_be_closed(logged_in_page):
    page = _free_app(logged_in_page)
    page.click("[data-open-plans]")
    assert page.locator("#overlay-paywall").is_visible()
    assert page.locator("#paywall-close").is_visible()
    assert page.locator("[data-paywall-decline]").first.text_content().strip() == "Not now"
    assert page.locator("#paywall-copy-free").is_visible()
    page.keyboard.press("Escape")
    assert page.locator("#overlay-paywall").is_hidden()


def test_ai_button_on_the_free_plan_shows_the_upgrade_toast(logged_in_page):
    page = _free_app(logged_in_page)
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    page.click("#btn-recs-trigger-9001")
    action = page.locator("#app-toast-action")
    action.wait_for(state="visible", timeout=5000)
    assert action.text_content().strip() == "See plans"
    assert "AI features need a plan" in page.text_content("#app-toast-text")
    # The caller's own "failed" toast must not replace the upgrade prompt.
    page.wait_for_timeout(1800)
    assert action.is_visible()
    action.click()
    assert page.locator("#overlay-paywall").is_visible()
