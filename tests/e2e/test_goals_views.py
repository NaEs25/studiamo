"""
The goals tab and the goal page (goals.js): the count chips on a card, the goal page's plus that opens Import with the goal selected, and the goal
page with its own history entry. Runs on the goals_page fixture's fixed dashboard; writes are mocked.
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


def test_goals_sit_two_to_a_row_on_a_desktop_window(goals_page):
    page = goals_page
    first = page.locator("[data-goal-card='9001']").bounding_box()
    second = page.locator("[data-goal-card='9002']").bounding_box()
    assert abs(first["y"] - second["y"]) < 4 and second["x"] > first["x"] + first["width"] - 1
    page.set_viewport_size({"width": 390, "height": 800})
    first = page.locator("[data-goal-card='9001']").bounding_box()
    second = page.locator("[data-goal-card='9002']").bounding_box()
    assert second["y"] > first["y"] + first["height"] - 1


def test_a_paused_material_with_a_quiz_still_counts_but_is_not_due(logged_in_page):
    page = logged_in_page
    dashboard = json.loads(json.dumps(GOALS_DASHBOARD))
    dashboard["videos"][0]["is_paused"] = 1  # paused by Chompy
    dashboard["quizzes"] = [{"id": 1, "video_id": 8001, "quiz_type": "video", "importance_level": 3,
                             "mastered": False, "is_due": True}]
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(dashboard)))
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    chips = [c.strip() for c in page.locator("[data-goal-card='9001'] .goal-stat").all_text_contents()]
    assert chips == ["2 materials", "1 quiz"]


def test_goals_tab_has_no_view_toggle(goals_page):
    page = goals_page
    assert page.locator("[aria-label='Goals view']").count() == 0
    assert page.locator("[data-goal-card='9001'] .goal-stat").count() >= 2


def test_plus_opens_import_with_that_goal_selected(goals_page):
    page = goals_page
    page.click("[data-goal-card='9002'] [data-goal-action='open-goal']")
    page.click("#goal-page [data-goal-action='add-material']")
    assert page.locator("#tab-import").is_visible()
    assert page.input_value("#input-goal-selected-id") == "9002"
    assert "bg-amber-500/15" in page.locator(".goal-select-card[data-goal-id='9002']").get_attribute("class")


def test_card_shows_counts_instead_of_materials(many_materials_page):
    page = many_materials_page
    card = page.locator("[data-goal-card='9001']")
    chips = [c.strip() for c in card.locator(".goal-stat").all_text_contents()]
    assert chips == ["6 materials", "0 quizzes"]  # no due chip while nothing is due
    assert card.locator("[id^='video-card-']").count() == 0
    assert page.locator("[data-goal-card='9002'] .goal-stat").first.text_content().strip() == "2 materials"


def test_card_counts_quizzes_and_what_is_due(logged_in_page):
    page = logged_in_page
    dashboard = json.loads(json.dumps(GOALS_DASHBOARD))
    quiz = lambda qid, vid, **kw: {"id": qid, "video_id": vid, "quiz_type": "video", "importance_level": 3,
                                   "mastered": False, "is_due": False, **kw}
    dashboard["quizzes"] = [
        quiz(1, 8001, is_due=True),
        quiz(2, 8002, mastered=True, is_due=True),   # mastered: counted, never due
        quiz(3, 8003, is_due=True),
        quiz(4, 8001, importance_level=5, is_due=True),  # a second quiz on one material: still one
        quiz(5, 8004, importance_level=5),               # only at another level: still counts
    ]
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(dashboard)))
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    chips = [c.strip() for c in page.locator("[data-goal-card='9001'] .goal-stat").all_text_contents()]
    assert chips == ["2 materials", "2 quizzes", "1 due today"]
    assert page.locator("[data-goal-card='9001'] .goal-stat-due").count() == 1
    assert [c.strip() for c in page.locator("[data-goal-card='9002'] .goal-stat").all_text_contents()] == ["2 materials", "2 quizzes", "1 due today"]


def test_goal_page_opens_lists_everything_and_goes_back(many_materials_page):
    page = many_materials_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert page.locator("#goal-page").is_visible()
    assert page.locator("#goals-container").is_hidden()
    assert page.locator("#goal-page [id^='video-card-']").count() == 6
    page.click("[data-goalpage-action='view-list']")
    assert page.locator("#goal-page [data-goalpage-row]").count() == 6
    page.click("#btn-goalpage-menu")
    page.click("[data-goalpage-menu-action='rearrange']")
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
    page.click("#btn-goalpage-menu")
    page.click("[data-goalpage-menu-action='rearrange']")
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


def test_goal_card_has_no_recommendations_controls(goals_page):
    page = goals_page
    assert page.locator("[data-goal-card='9001'] #btn-recs-trigger-9001").count() == 0
    assert page.locator("#btn-recs-trigger-9001").count() == 0


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
    # Edit is the one goal button, on the title line, inside the box with the recommendations;
    # Archive and Delete are in its dialog.
    button = box.locator("[data-goal-action='edit']")
    assert abs(title_mid(button) - title_mid(title)) < 12
    assert page.locator("#goal-page [data-goal-action='archive'], #goal-page [data-goal-action='delete']").count() == 0
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


def test_recommendations_controls_exist_only_on_the_open_goal_page(goals_page):
    page = goals_page
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    assert page.locator("#btn-recs-trigger-9001").count() == 1
    page.click("[data-goalpage-action='back']")
    page.wait_for_selector("#goal-page", state="hidden")
    page.wait_for_selector("[data-goal-card='9001']", state="attached")
    assert page.locator("#btn-recs-trigger-9001").count() == 0


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


def test_goals_header_puts_new_goal_on_the_row_of_the_reorder_button(goals_page):
    page = goals_page
    toggle = page.locator("#btn-goals-reorder").bounding_box()
    new_goal = page.locator("#btn-add-goal-modal").bounding_box()
    assert abs((toggle["y"] + toggle["height"] / 2) - (new_goal["y"] + new_goal["height"] / 2)) < 12
    heading = page.locator("#tab-goals h2").first.bounding_box()
    assert new_goal["y"] > heading["y"] + heading["height"] - 2


def test_new_goal_button_sits_at_the_far_end_of_the_header_row(goals_page):
    page = goals_page
    new_goal = page.locator("#btn-add-goal-modal").bounding_box()
    section = page.locator("#tab-goals").bounding_box()
    assert abs((new_goal["x"] + new_goal["width"]) - (section["x"] + section["width"])) < 4


def test_the_header_controls_have_the_same_height(goals_page):
    page = goals_page
    boxes = [page.locator(sel).bounding_box() for sel in (
        "#btn-goals-search-toggle >> xpath=..", "#btn-goals-reorder", "#btn-add-goal-modal")]
    heights = [round(b["height"]) for b in boxes]
    assert len(set(heights)) == 1, heights
