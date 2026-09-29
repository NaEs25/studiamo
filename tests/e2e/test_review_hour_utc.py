"""
The review hour setting is labeled as UTC and shows the equivalent time in the browser's
time zone. The settings autosave is intercepted, so nothing is written.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "timezone_id": "Europe/Berlin", "locale": "en-GB"}


def test_review_hour_is_labeled_utc_with_local_hint(logged_in_page):
    page = logged_in_page
    page.route("**/api/settings", lambda route: route.fulfill(status=200, content_type="application/json", body="{}")
               if route.request.method == "POST" else route.continue_())

    page.goto("/app")
    page.click("#nav-settings")
    select = page.locator("#settings-preferred-hour")
    select.wait_for(state="attached", timeout=15000)

    assert "(UTC)" in page.inner_text("label[for='settings-preferred-hour']")
    assert select.locator("option[value='8']").inner_text().strip() == "08:00 UTC"

    select.select_option("8")
    now = datetime.now(timezone.utc)
    expected = now.replace(hour=8, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("Europe/Berlin"))
    hint = page.locator("#settings-preferred-hour-local")
    assert hint.inner_text() == f"That is {expected:%H:%M} in your time zone."

    select.select_option("-1")
    assert hint.is_hidden()
