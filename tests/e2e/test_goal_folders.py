"""
Folders on the goal page (goals.js): folder rows ahead of loose materials, the folder view, the
three-dot menu (new folder, rearrange), moving a material into a folder by drag and by the
"move to" button, and search reaching into folders. Runs on a fixed dashboard; every write is
answered by the test.
"""
import json

import pytest

from tests.e2e.conftest import GOALS_DASHBOARD


def _dashboard():
    d = json.loads(json.dumps(GOALS_DASHBOARD))
    d["folders"] = [{"id": 7001, "goal_id": 9001, "name": "Networking"}]
    for v in d["videos"]:
        if v["id"] == 8002:
            v["folder_id"] = 7001  # "Pod networking deep dive"
    return d


@pytest.fixture
def folder_page(logged_in_page):
    page = logged_in_page
    posts = []

    def record(route):
        posts.append((route.request.method, route.request.url.split("/api", 1)[1], route.request.post_data or ""))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "success", "folder_id": 7002}))

    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_dashboard())))
    page.route("**/api/goals/9001/folders**", record)
    page.route("**/api/goals/9001/materials/*/folder", record)
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    page.click("[data-goal-card='9001'] [data-goal-action='open-goal']")
    page.wait_for_selector("#goal-page [data-goalpage-folder='7001']")
    page.posts = posts
    return page


def test_root_lists_the_folder_first_and_keeps_its_materials_out(folder_page):
    page = folder_page
    assert "1 material" in page.inner_text("[data-goalpage-folder='7001']")
    assert page.locator("#goal-page #video-card-8001").count() == 1
    assert page.locator("#goal-page #video-card-8002").count() == 0
    folder_y = page.locator("[data-goalpage-folder='7001']").bounding_box()["y"]
    assert folder_y < page.locator("#video-card-8001").bounding_box()["y"]
    assert "1 folder" in page.inner_text("#goal-page")


def test_folder_view_shows_only_its_materials_and_goes_back(folder_page):
    page = folder_page
    page.click("[data-goalpage-action='open-folder'][data-folder-id='7001']")
    assert page.inner_text("#goal-page h2").strip() == "Networking"
    assert page.locator("#goal-page #video-card-8002").count() == 1
    assert page.locator("#goal-page #video-card-8001").count() == 0
    assert page.locator("#goal-page #btn-recs-trigger-9001").count() == 0
    page.click("[data-goalpage-action='close-folder']")
    assert page.locator("#goal-page #video-card-8001").count() == 1
    assert page.inner_text("#goal-page h2").strip() == "Kubernetes Basics"


def test_menu_creates_a_folder(folder_page):
    page = folder_page
    page.click("#btn-goalpage-menu")
    page.click("[data-goalpage-menu-action='new-folder']")
    page.fill("#folder-modal-name", "Operators")
    page.click("#folder-modal-form button[type=submit]")
    page.wait_for_timeout(600)
    assert ("POST", "/goals/9001/folders", ) == page.posts[0][:2] and "Operators" in page.posts[0][2]


def test_a_drop_on_a_folder_moves_the_material_at_once(folder_page):
    page = folder_page
    page.click("#btn-goalpage-menu")
    page.click("[data-goalpage-menu-action='rearrange']")
    page.drag_and_drop("[data-goalpage-row='8001'] .drag-handle", "[data-goalpage-folder='7001']")
    # The row leaves the page before the save has been answered.
    assert page.locator("#goal-page #video-card-8001").count() == 0
    page.wait_for_timeout(600)
    moves = [p for p in page.posts if p[1] == "/goals/9001/materials/8001/folder"]
    assert moves and "7001" in moves[0][2]


def test_move_to_button_moves_a_material_into_a_folder_and_out_again(folder_page):
    page = folder_page
    page.click("#btn-goalpage-menu")
    page.click("[data-goalpage-menu-action='rearrange']")
    page.click("[data-goalpage-row='8001'] [data-goalpage-moveto]")
    page.click("[data-moveto-folder='7001']")
    page.wait_for_timeout(600)
    assert any(p[1] == "/goals/9001/materials/8001/folder" and "7001" in p[2] for p in page.posts)

    page.click("[data-goalpage-action='toggle-reorder']")  # Done
    page.click("[data-goalpage-action='open-folder'][data-folder-id='7001']")
    page.click("#btn-goalpage-menu")
    page.click("[data-goalpage-menu-action='rearrange']")
    page.click("[data-goalpage-row='8002'] [data-goalpage-moveto]")
    page.click("[data-moveto-folder='']")
    page.wait_for_timeout(600)
    out = [p for p in page.posts if p[1] == "/goals/9001/materials/8002/folder"]
    assert out and "folder_id" not in out[0][2]


def test_search_finds_a_material_inside_a_folder(folder_page):
    page = folder_page
    page.click("[data-goalpage-action='toggle-search']")
    page.fill("#goalpage-search-input", "networking deep")
    assert page.locator("#goal-page #video-card-8002").is_visible()
    assert not page.locator("#goal-page #video-card-8001").is_visible()
    assert not page.locator("[data-goalpage-folder='7001']").is_visible()
    page.fill("#goalpage-search-input", "")
    assert not page.locator("#goal-page #video-card-8002").is_visible()
    assert page.locator("[data-goalpage-folder='7001']").is_visible()


def test_jump_to_a_material_in_a_folder_opens_that_folder(folder_page):
    page = folder_page
    page.click("[data-goalpage-action='back']")
    page.wait_for_selector("[data-goal-card='9001']")
    page.evaluate("navigateToVideoInGoals(8002)")
    page.wait_for_selector("#goal-page #video-card-8002", timeout=10000)
    assert page.inner_text("#goal-page h2").strip() == "Networking"
