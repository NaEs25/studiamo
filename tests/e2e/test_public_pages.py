"""
Browser-level smoke coverage for pages that don't require a login: the landing page and
the static legal pages. Mirrors the "does it render without crashing" bar of
test_smoke_routes.py, but through a real browser so a broken script tag or a JS error
that leaves the page blank (something an HTTP-status-only check can't see) would show up
here as a missing heading.
"""


def test_landing_page_loads(page, base_url):
    page.goto("/")
    assert "studiamo" in page.title().lower()


def test_login_page_loads(page, base_url):
    page.goto("/login")
    assert page.locator("body").count() == 1


def test_impressum_loads(page, base_url):
    page.goto("/impressum")
    assert page.locator("body").inner_text().strip() != ""


def test_privacy_loads(page, base_url):
    page.goto("/privacy")
    assert page.locator("body").inner_text().strip() != ""


def test_terms_loads(page, base_url):
    page.goto("/terms")
    assert page.locator("body").inner_text().strip() != ""
