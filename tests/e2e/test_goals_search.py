"""
Goals tab search (goals.js applyGoalsSearch). Runs on the goals_page fixture (tests/e2e/conftest.py),
whose dashboard is a fixed set of goals and materials, so the test reads nothing from the test
account's real data and writes nothing.
"""


def _visible(page, selector):
    return page.locator(selector).first.is_visible()


def _search(page, text):
    page.fill("#goals-search-input", text)
    page.wait_for_timeout(250)  # the input is debounced


def test_search_filters_goals_and_materials(goals_page):
    page = goals_page
    assert not _visible(page, "#goals-search-bar")
    page.click("#btn-goals-search-toggle")
    assert page.evaluate("document.activeElement.id") == "goals-search-input"

    # A material title match keeps its goal, opens the materials, and hides the rest.
    _search(page, "helm")
    assert _visible(page, "[data-goal-card='9001']")
    assert _visible(page, "#video-card-8001")
    assert not _visible(page, "#video-card-8002")
    assert not _visible(page, "[data-goal-card='9002']")
    assert not _visible(page, "#goals-watchlist-container")
    assert not _visible(page, "#goals-archived-section")
    assert page.text_content("#goals-search-status") == "Showing 1 material"

    # A goal title match shows the goal with all of its materials.
    _search(page, "kubernetes")
    assert _visible(page, "[data-goal-card='9001']")
    assert not _visible(page, "[data-goal-card='9002']")

    # When the goal and one of its materials both match, the materials open and all stay listed.
    _search(page, "pod")
    assert _visible(page, "#video-card-8002")
    assert _visible(page, "#video-card-8001")
    assert page.text_content("#goals-search-status") == "Showing 1 goal and 1 material"

    # Accents and case are ignored, and every word has to match.
    _search(page, "CAFE vocab")
    assert _visible(page, "#video-card-8004")
    assert not _visible(page, "#video-card-8003")

    # Watchlist, unassociated, and archived items are searched too.
    _search(page, "docker")
    assert _visible(page, "#video-card-8005")
    _search(page, "git")
    assert _visible(page, "#video-card-8006")
    _search(page, "photography")
    assert _visible(page, "[data-archived-goal='9003']")
    assert not _visible(page, "#goals-container")

    _search(page, "zzzz")
    assert _visible(page, "#goals-search-empty")


def test_closing_search_restores_the_page(goals_page):
    page = goals_page
    materials_open_before = _visible(page, "#goal-materials-content-9001")

    page.click("#btn-goals-search-toggle")
    _search(page, "pod networking")
    assert _visible(page, "#video-card-8002")

    page.press("#goals-search-input", "Escape")
    assert not _visible(page, "#goals-search-bar")
    assert page.input_value("#goals-search-input") == ""
    assert page.locator("#tab-goals .search-miss").count() == 0
    assert _visible(page, "#goal-materials-content-9001") == materials_open_before
    assert _visible(page, "[data-goal-card='9002']")


def test_slash_shortcut(goals_page):
    page = goals_page
    page.keyboard.press("/")
    assert _visible(page, "#goals-search-bar")
    assert page.evaluate("document.activeElement.id") == "goals-search-input"
    page.press("#goals-search-input", "Escape")
    assert not _visible(page, "#goals-search-bar")

    # Not while an overlay is open: the search would open behind it and take its focus.
    page.evaluate("openEditGoalModal(9002)")
    assert _visible(page, "#overlay-goal-modal")
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("/")
    assert not _visible(page, "#goals-search-bar")


def test_section_opened_by_hand_during_search_stays_open(goals_page):
    page = goals_page
    page.evaluate("localStorage.setItem('goal-materials-open-9001', 'false')")
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    assert not _visible(page, "#goal-materials-content-9001")

    page.click("#btn-goals-search-toggle")
    _search(page, "helm")
    assert _visible(page, "#goal-materials-content-9001")

    # Closing and reopening by hand makes the section the user's again.
    page.click("#goal-materials-chevron-9001")
    page.click("#goal-materials-chevron-9001")
    page.press("#goals-search-input", "Escape")
    assert _visible(page, "#goal-materials-content-9001")
    assert page.evaluate("localStorage.getItem('goal-materials-open-9001')") == "true"


def test_jump_to_material_clears_the_search(goals_page):
    page = goals_page
    page.click("#btn-goals-search-toggle")
    _search(page, "kubernetes")
    assert not _visible(page, "#video-card-8006")

    page.evaluate("navigateToVideoInGoals(8006)")
    page.wait_for_timeout(500)
    assert page.input_value("#goals-search-input") == ""
    assert _visible(page, "#video-card-8006")
