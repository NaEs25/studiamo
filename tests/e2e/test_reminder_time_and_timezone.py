"""
The reminder time is a local hour, and the time zone dropdown lists the browser's zones with the
stored one selected. The settings GET has its two fields overridden and the autosave POST is intercepted,
so nothing is written to the account's settings.
"""
import json

import pytest


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "timezone_id": "Europe/Berlin", "locale": "en-GB"}


def _open_settings(page, settings_payload, saved):
    def handle(route):
        if route.request.method == "POST":
            saved.append(route.request.post_data or "")
            route.fulfill(status=200, content_type="application/json", body="{}")
        else:
            response = route.fetch()
            body = response.json()
            body.update(settings_payload)
            route.fulfill(response=response, body=json.dumps(body))

    page.route("**/api/settings", handle)
    page.goto("/app")
    with page.expect_response(lambda r: r.url.endswith("/api/settings") and r.request.method == "GET", timeout=15000):
        page.click("#nav-settings")
    page.wait_for_load_state("networkidle")


def test_reminder_hour_is_local_and_stored_zone_is_selected(logged_in_page):
    page = logged_in_page
    saved = []
    _open_settings(page, {"reminder_hour": 18, "timezone": "America/New_York"}, saved)

    hour = page.locator("#settings-reminder-hour")
    hour.wait_for(state="attached", timeout=15000)
    assert hour.input_value() == "18"
    assert hour.locator("option[value='8']").inner_text().strip() == "08:00"
    assert "UTC" not in page.inner_text("label[for='settings-reminder-hour']")

    zone = page.locator("#settings-timezone")
    assert zone.input_value() == "America/New_York"
    # The device is in Berlin, the account in New York: the hint says so.
    assert "Europe/Berlin".replace("_", " ") in page.inner_text("#settings-timezone-hint")

    hour.select_option("7")
    # The autosave is debounced (settings.js _scheduleSettingsAutosave).
    for _ in range(20):
        if saved:
            break
        page.wait_for_timeout(250)
    assert saved, "changing the reminder hour should trigger the settings autosave"
    assert "reminder_hour" in saved[-1] and "America/New_York" in saved[-1]


def test_device_zone_is_preselected_when_none_is_stored(logged_in_page):
    page = logged_in_page
    _open_settings(page, {"reminder_hour": 18, "timezone": None}, [])

    zone = page.locator("#settings-timezone")
    zone.wait_for(state="attached", timeout=15000)
    assert zone.input_value() == "Europe/Berlin"
    assert page.locator("#settings-timezone-hint").is_hidden()
