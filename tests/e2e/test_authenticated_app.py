"""
Logged-in smoke coverage for the main SPA shell: does each tab actually render, and does
navigating between them throw uncaught JS errors. This is the frontend equivalent of
test_smoke_routes.py's "did it crash" bar, not a correctness suite for any one feature.
"""
import pytest


def _console_errors(page):
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


def test_dashboard_loads_when_logged_in(logged_in_page):
    errors = _console_errors(logged_in_page)
    logged_in_page.goto("/app")
    logged_in_page.wait_for_selector("#nav-dashboard", timeout=10000)
    assert errors == []


@pytest.mark.parametrize("nav_id", ["nav-goals", "nav-import", "nav-stats", "nav-settings", "nav-dashboard"])
def test_tab_switch_has_no_console_errors(logged_in_page, nav_id):
    errors = _console_errors(logged_in_page)
    logged_in_page.goto("/app")
    logged_in_page.wait_for_selector(f"#{nav_id}", timeout=10000)
    logged_in_page.click(f"#{nav_id}")
    logged_in_page.wait_for_timeout(300)
    assert errors == []
