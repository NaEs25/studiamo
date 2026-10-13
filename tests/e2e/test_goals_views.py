"""
The goals tab's views and the goal page (goals.js): expanded and titles-only views, the
plus that opens Import with the goal selected, the three-material limit, and the goal page with
its own history entry. Runs on the goals_page fixture's fixed dashboard; writes are mocked.
"""
import json

import pytest

from tests.e2e.conftest import GOALS_DASHBOARD


@pytest.fixture
def many_materials_page(logged_in_page):
    page = logged_in_page
    dashboard = json.loads(json.dumps(GOALS_DASHBOARD))
    for n in range(4):
        dashboard["videos"].append({
            "id": 8100 + n, "title": f"Extra material {n}", "learning_goal_id": 9001, "is_watchlist": 0,
            "status": "completed", "importance_rating": 3, "importance_level": 3, "url": "", "summary": "", "custom_notes": "",
        })
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(dashboard)))
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    return page


def test_titles_only_view_keeps_the_three_controls_and_is_remembered(goals_page):
    page = goals_page
    page.click("#btn-goals-view-compact")
    page.wait_for_selector("[data-goal-card='9001']")
    assert page.locator("#goal-materials-content-9001").count() == 0
    controls = page.locator("[data-goal-card='9001'] .bg-stone-100")
    for action in ("add-material", "open-goal", "menu"):
        assert controls.locator(f"[data-goal-action='{action}']").count() == 1
    page.reload()
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    assert page.locator("#goal-materials-content-9001").count() == 0
    page.click("#btn-goals-view-expanded")
    page.wait_for_selector("#goal-materials-content-9001", state="attached")


def test_plus_opens_import_with_that_goal_selected(goals_page):
    page = goals_page
    page.click("[data-goal-card='9002'] [data-goal-action='add-material']")
    assert page.locator("#tab-import").is_visible()
    assert page.input_value("#input-goal-selected-id") == "9002"
    assert "bg-amber-500/15" in page.locator(".goal-select-card[data-goal-id='9002']").get_attribute("class")


def test_card_lists_three_materials_then_points_at_the_goal_page(many_materials_page):
    page = many_materials_page
    page.evaluate("localStorage.setItem('goal-materials-open-9001', 'true')")
    page.reload()
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    visible = page.locator("#goal-materials-content-9001 [id^='video-card-']:visible").count()
    assert visible == 3
    see_all = page.locator("[data-goal-card='9001'] button:has-text('See all 6 on the goal page')")
    assert see_all.is_visible()


def test_goal_page_opens_lists_everything_and_goes_back(many_materials_page):
    page = many_materials_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert page.locator("#goal-page").is_visible()
    assert page.locator("#goals-container").is_hidden()
    assert page.locator("#goal-page [id^='video-card-']").count() == 6
    page.click("[data-goalpage-action='view-list']")
    assert page.locator("#goal-page [data-goalpage-row]").count() == 6
    page.click("[data-goalpage-action='toggle-reorder']")
    assert page.locator("#goal-page [data-goalpage-move='up']").count() == 6
    page.click("[data-goalpage-action='back']")
    page.wait_for_selector("#goal-page", state="hidden")
    assert page.locator("#goals-container").is_visible()


def test_browser_back_closes_the_goal_page(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert page.locator("#goal-page").is_visible()
    page.go_back()
    page.wait_for_selector("#goal-page", state="hidden")


def test_reordering_materials_posts_the_full_list(many_materials_page):
    page = many_materials_page
    sent = []
    page.route("**/api/goals/9001/materials/order", lambda route: (
        sent.append(route.request.post_data), route.fulfill(status=200, content_type="application/json", body='{"status":"success"}')))
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.click("[data-goalpage-action='view-list']")
    page.click("[data-goalpage-action='toggle-reorder']")
    first = page.locator("[data-goalpage-row]").first.get_attribute("data-goalpage-row")
    page.locator("[data-goalpage-row] [data-goalpage-move='down']").first.click()
    page.wait_for_timeout(400)
    assert sent and 'name="ids"' in sent[0]
    ids = sent[0].split('name="ids"')[1].strip().split("\r\n")[0].split(",")
    assert len(ids) == 6 and ids[1] == first


def test_reorder_sheet_shows_the_new_order_after_an_arrow(logged_in_page):
    """Against the real API (the test account): the sheet must redraw from the reloaded list, not
    from the one it had before the move. Creates three goals and deletes them again."""
    page = logged_in_page
    page.goto("/app")
    make = lambda title: page.evaluate(
        """async (t) => { const f = new FormData(); f.append('title', t); const r = await fetch('/api/goals', {method: 'POST', body: f}); return (await r.json()).goal_id; }""",
        title)
    goals = [make(f"Sheet order test {n} {id(page)}") for n in range(3)]
    try:
        page.reload()
        page.click("#nav-goals")
        page.wait_for_selector(f"[data-goal-card='{goals[0]}']", state="attached")
        page.click("#btn-goals-reorder")
        rows = lambda: [str(x) for x in page.evaluate(
            "[...document.querySelectorAll('#goal-reorder-list [data-reorder-row]')].map(e => Number(e.dataset.reorderRow))")]
        before = [r for r in rows() if r in map(str, goals)]
        assert before == [str(g) for g in goals]
        page.click(f"[data-reorder-row='{goals[0]}'] [data-reorder-move='down']")
        page.wait_for_function(
            "([a, b]) => { const r = [...document.querySelectorAll('#goal-reorder-list [data-reorder-row]')].map(e => e.dataset.reorderRow); return r.indexOf(String(a)) > r.indexOf(String(b)); }",
            arg=[goals[0], goals[1]], timeout=5000)
    finally:
        for g in goals:
            page.evaluate("async (g) => { await fetch('/api/goals/' + g + '?delete_materials=true', {method: 'DELETE'}); }", g)


def test_goal_description_is_only_on_the_goal_page(goals_page):
    page = goals_page
    assert "Pods and deployments" not in page.locator("[data-goal-card='9001']").text_content()
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert "Pods and deployments" in page.text_content("#goal-page")


def test_goal_card_keeps_the_recommendations_below_the_materials(goals_page):
    page = goals_page
    card = page.locator("[data-goal-card='9001']")
    recs_y = card.locator("#btn-recs-trigger-9001").bounding_box()["y"]
    materials_y = card.locator("[data-goal-action='toggle-materials']").first.bounding_box()["y"]
    assert recs_y > materials_y


def test_goal_page_layout_buttons_and_boxes(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.wait_for_selector("#goal-page [data-goal-action='edit']")
    # Exactly one copy of the recommendations controls while the page is open (their ids are per goal).
    assert page.locator("#btn-recs-trigger-9001").count() == 1
    assert page.locator("#goal-page [data-goal-action='menu']").count() == 0

    box = page.locator("#goal-page > div").first
    title_mid = lambda loc: loc.bounding_box()["y"] + loc.bounding_box()["height"] / 2
    title = page.locator("#goal-page h2")
    # Edit, Archive and Delete share the title line, inside the box with the recommendations.
    for action in ("edit", "archive", "delete"):
        button = box.locator(f"[data-goal-action='{action}']")
        assert abs(title_mid(button) - title_mid(title)) < 12, action
    assert box.locator("#btn-recs-trigger-9001").count() == 1
    # Add material is not in that box: it sits below it, on the row of the Detail and List toggle.
    assert box.locator("[data-goal-action='add-material']").count() == 0
    add = page.locator("#goal-page [data-goal-action='add-material']")
    toggle = page.locator("[data-goalpage-action='view-detail']")
    assert abs(title_mid(add) - title_mid(toggle)) < 12
    assert add.bounding_box()["y"] > box.bounding_box()["y"] + box.bounding_box()["height"]

    page.click("#goal-page [data-goal-action='edit']")
    assert page.locator("#overlay-goal-modal").is_visible()
    assert page.input_value("#goal-modal-title") == "Kubernetes Basics"


def test_closing_the_goal_page_gives_the_card_its_recommendations_back(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.click("[data-goalpage-action='back']")
    page.wait_for_selector("#goal-page", state="hidden")
    page.wait_for_selector("[data-goal-card='9001'] #btn-recs-trigger-9001", state="attached")
    assert page.locator("#btn-recs-trigger-9001").count() == 1


def test_reload_on_a_goal_page_stays_on_it_and_back_returns_to_the_list(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert page.url.endswith("#goal-9001")
    page.reload()
    page.wait_for_selector("#goal-page [data-goal-action='edit']", timeout=10000)
    assert page.locator("#tab-goals").is_visible() and page.locator("#goals-container").is_hidden()
    page.click("[data-goalpage-action='back']")
    page.wait_for_selector("#goal-page", state="hidden")
    assert "#goal-" not in page.url
    assert page.locator("#goals-container").is_visible()


def test_reload_reopens_the_goal_page_even_if_the_address_loses_its_hash(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert page.evaluate("localStorage.getItem('active_goal_page')") == "9001"
    page.evaluate("history.replaceState(null, '', location.pathname)")
    page.reload()
    page.wait_for_selector("#goal-page [data-goal-action='edit']", timeout=10000)
    page.click("[data-goalpage-action='back']")
    page.wait_for_selector("#goal-page", state="hidden")
    assert page.evaluate("localStorage.getItem('active_goal_page')") is None
    page.reload()
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    assert page.locator("#goal-page").is_hidden()


def test_goal_page_edit_sits_on_the_title_line_inside_one_box(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    title = page.locator("#goal-page h2").bounding_box()
    edit = page.locator("#goal-page [data-goal-action='edit']").bounding_box()
    assert abs((title["y"] + title["height"] / 2) - (edit["y"] + edit["height"] / 2)) < 12
    box = page.locator("#goal-page > div").first
    assert box.locator("#btn-recs-trigger-9001").count() == 1 and box.locator("h2").count() == 1


def test_goals_header_puts_new_goal_on_the_row_of_the_view_toggle(goals_page):
    page = goals_page
    toggle = page.locator("#btn-goals-view-expanded").bounding_box()
    new_goal = page.locator("#btn-add-goal-modal").bounding_box()
    assert abs((toggle["y"] + toggle["height"] / 2) - (new_goal["y"] + new_goal["height"] / 2)) < 12
    heading = page.locator("#tab-goals h2").first.bounding_box()
    assert new_goal["y"] > heading["y"] + heading["height"] - 2


def test_new_goal_button_sits_at_the_far_end_of_the_header_row(goals_page):
    page = goals_page
    new_goal = page.locator("#btn-add-goal-modal").bounding_box()
    section = page.locator("#tab-goals").bounding_box()
    assert abs((new_goal["x"] + new_goal["width"]) - (section["x"] + section["width"])) < 4


def test_the_four_header_controls_have_the_same_height(goals_page):
    page = goals_page
    boxes = [page.locator(sel).bounding_box() for sel in (
        "#btn-goals-search-toggle >> xpath=..", "[aria-label='Goals view']", "#btn-goals-reorder", "#btn-add-goal-modal")]
    heights = [round(b["height"]) for b in boxes]
    assert len(set(heights)) == 1, heights
