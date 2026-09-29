"""
In-app dialogs instead of native alert(): showConfirm's single-button notice mode, and no
alert() left in the app's scripts.
"""
from pathlib import Path

STATIC_JS = Path(__file__).resolve().parents[2] / "app" / "static" / "js"


def test_no_native_alert_in_app_scripts():
    offenders = [
        f"{path.name}:{number}"
        for path in STATIC_JS.glob("*.js")
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "alert(" in line and not line.strip().startswith("//")
    ]
    assert offenders == []


def test_notice_hides_cancel_and_the_next_confirm_restores_it(logged_in_page):
    page = logged_in_page
    page.goto("/app")
    page.wait_for_selector("#nav-dashboard", timeout=15000)

    page.evaluate("() => { window._noticeResult = showConfirm({ title: 'Level Up!', hideCancel: true }); }")
    page.wait_for_selector("#app-confirm-btn-ok", state="visible")
    assert page.locator("#app-confirm-btn-cancel").is_hidden()
    page.click("#app-confirm-btn-ok")
    assert page.evaluate("window._noticeResult") is True

    page.wait_for_selector("#app-confirm-overlay", state="hidden")
    page.evaluate("() => { window._confirmResult = showConfirm({ title: 'Sure?' }); }")
    page.wait_for_selector("#app-confirm-btn-cancel", state="visible")
    page.click("#app-confirm-btn-cancel")
    assert page.evaluate("window._confirmResult") is False
