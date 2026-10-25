"""Stats tab: the last-seven-days chart and the streak calendar render and the month arrows work."""


def test_stats_chart_and_calendar_render(logged_in_page):
    errors = []
    logged_in_page.on("pageerror", lambda exc: errors.append(str(exc)))
    logged_in_page.goto("/app")
    logged_in_page.wait_for_selector("#nav-stats", timeout=10000)
    logged_in_page.click("#nav-stats")

    logged_in_page.wait_for_selector("#stats-week-chart > div", timeout=10000)
    assert logged_in_page.locator("#stats-week-chart > div").count() == 7
    # A month grid always has its days; the label names the month.
    logged_in_page.wait_for_selector("#stats-cal-grid .streak-cal-cell", timeout=10000)
    assert logged_in_page.locator("#stats-cal-grid .streak-cal-cell").count() >= 28
    assert logged_in_page.locator("#stats-cal-label").inner_text().strip() != ""
    # The current month is the last one: the forward arrow is off.
    assert logged_in_page.locator("#stats-cal-next").is_disabled()
    assert errors == []
