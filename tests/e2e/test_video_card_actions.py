"""
Material cards (videos.js renderVideoCard), their options menu, and the session list in the
material analytics modal are bound through delegated listeners (initVideoCardActions) instead
of inline handlers. The dashboard is answered with fixed materials in each card state, and every
write a button makes is answered by a mocked route, so nothing reaches the database.
"""
import json

import pytest

GOAL_ID = 9101
NORMAL, PREVIEW, FAILED = 8101, 8102, 8103


def _video(vid, **fields):
    video = {"id": vid, "title": f"Material {vid}", "learning_goal_id": GOAL_ID, "importance_rating": 3,
             "importance_level": 3, "status": "ready", "is_watchlist": 0, "is_temporary": 0, "is_paused": 0,
             "is_archived": 0, "youtube_id": None, "thumbnail_url": None, "summary": [], "custom_notes": "",
             "url": "", "has_concept_pool": False}
    video.update(fields)
    return video


DASHBOARD = {
    "goals": [{"id": GOAL_ID, "title": "Video editing", "description": "", "order_index": 1,
               "has_saved_recommendations": 0}],
    "archived_goals": [],
    "videos": [
        _video(NORMAL, summary=["Nodes apply one adjustment each."]),
        _video(PREVIEW, is_temporary=1, is_watchlist=1, learning_goal_id=None, youtube_id="abcDEF12345"),
        _video(FAILED, status="failed", status_error="Transcript unavailable"),
    ],
    "archived": [],
    "quizzes": [],
    "chompy": {"eaten_unseen": []},
}

STATS = {
    "title": f"Material {NORMAL}", "srs_stage": 1, "mastered": False, "next_review_at": None,
    "attempts": [{"id": 70001, "quiz_id": 60001, "srs_stage": 1, "mastered": False,
                  "created_at": "2026-10-01T08:00:00", "question": "What does a node do?",
                  "user_answer": "One adjustment", "grade": "remembered", "explanation": ""}],
}


@pytest.fixture
def cards_page(logged_in_page):
    page = logged_in_page
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(DASHBOARD)))
    page.route("**/api/daily-recommendations**", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"recommendations": []}'))
    page.route("**/api/videos/import-tasks", lambda route: route.fulfill(
        status=200, content_type="application/json", body="[]"))
    page.route(f"**/api/videos/{NORMAL}/stats", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(STATS)))
    page.add_init_script(f"""
        localStorage.setItem('goal-materials-open-{GOAL_ID}', 'true');
        localStorage.setItem('accordion-open-watchlist', 'true');
    """)
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector(f"#video-card-{NORMAL}", state="visible", timeout=15000)
    page.evaluate("""() => {
        window.__calls = [];
        window.openStudyStudio = id => window.__calls.push(['studio', id]);
        window.handleStudyButtonClick = (e, id, level) => window.__calls.push(['study', id, level]);
    }""")
    return page


def _answer(page, pattern, sink):
    def handle(route):
        sink.append((route.request.method, route.request.url.split("/api/")[1]))
        route.fulfill(status=200, content_type="application/json", body='{"status": "ok", "quiz_id": 1}')
    page.route(pattern, handle)


def _calls(page):
    return page.evaluate("window.__calls")


def _open_menu(page, vid=NORMAL):
    button = page.locator(f"#video-card-{vid} [data-video-action='menu']")
    button.scroll_into_view_if_needed()
    # A scroll event arrives a frame after the scroll itself. Clicking in between opens the menu
    # just in time for that event, which the menu takes as the page scrolling away and closes
    # on (core.js toggleContextMenuPortal). A person never clicks that fast after a scroll.
    page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")
    button.click()
    page.locator("#video-context-menu-portal").wait_for(state="visible", timeout=5000)


def test_card_buttons(cards_page):
    page = cards_page
    card = page.locator(f"#video-card-{NORMAL}")
    sent = []
    _answer(page, f"**/api/videos/{NORMAL}/edit", sent)
    _answer(page, f"**/api/videos/{NORMAL}/generate_quiz", sent)

    # The title, the thumbnail and Watch & Notes all open Study Studio.
    card.locator("a[data-video-action='open-studio']").click()
    card.locator("div[data-video-action='open-studio']").click()
    card.locator("[data-video-action='watch-notes']").click()
    assert _calls(page) == [["studio", NORMAL]] * 3

    card.locator("[data-video-action='study']").click()
    assert _calls(page)[-1] == ["study", NORMAL, 3]

    details = page.locator(f"#details-content-{NORMAL}")
    assert details.is_hidden()
    card.locator("[data-video-action='toggle-details']").click()
    assert details.is_visible()

    # Stars rate the material: the icons update at once and the change is saved.
    with page.expect_request(f"**/api/videos/{NORMAL}/generate_quiz"):
        card.locator("[data-video-action='rate'][data-level='5']").click()
    filled = card.locator("[data-video-action='rate'] .fill-amber-500")
    assert filled.count() == 5
    assert ("POST", f"videos/{NORMAL}/edit") in sent

    assert card.locator("[onclick]").count() == 0


def test_preview_and_failed_cards(cards_page):
    page = cards_page
    sent = []
    _answer(page, f"**/api/videos/{PREVIEW}/confirm_import", sent)
    _answer(page, f"**/api/videos/{PREVIEW}/watchlist", sent)
    _answer(page, f"**/api/videos/{FAILED}/retry", sent)
    preview = page.locator(f"#video-card-{PREVIEW}")
    failed = page.locator(f"#video-card-{FAILED}")

    with page.expect_request(f"**/api/videos/{FAILED}/retry"):
        failed.locator("[data-video-action='retry']").click()

    with page.expect_request(f"**/api/videos/{PREVIEW}/watchlist"):
        preview.locator("[data-video-action='toggle-watchlist']").click()

    # Discarding asks first; cancelling sends nothing.
    preview.locator("[data-video-action='discard-preview']").click()
    page.locator("#app-confirm-overlay").wait_for(state="visible", timeout=5000)
    page.click("#app-confirm-btn-cancel")
    page.wait_for_timeout(300)
    assert not any(method == "DELETE" for method, _ in sent)

    with page.expect_request(f"**/api/videos/{PREVIEW}/confirm_import"):
        preview.locator("[data-video-action='import-preview']").click()

    assert page.locator("#tab-goals [data-video-action][onclick]").count() == 0


def test_options_menu(cards_page):
    page = cards_page
    sent = []
    _answer(page, f"**/api/videos/{NORMAL}/pause", sent)
    menu = page.locator("#video-context-menu-portal")

    _open_menu(page)
    assert menu.locator("[onclick]").count() == 0
    # The same button closes it again.
    page.click(f"#video-card-{NORMAL} [data-video-action='menu']")
    assert menu.count() == 0

    _open_menu(page)
    # Pausing reloads the goals tab, which renders every card afresh.
    with page.expect_request(f"**/api/videos/{NORMAL}/pause"), page.expect_response("**/api/dashboard"):
        menu.locator("[data-video-menu-action='pause']").click()
    assert menu.count() == 0

    _open_menu(page)
    menu.locator("[data-video-menu-action='edit']").click()
    page.locator("#overlay-edit-video").wait_for(state="visible", timeout=5000)
    assert page.input_value("#edit-video-id") == str(NORMAL)


def test_analytics_sessions_fold_out(cards_page):
    page = cards_page
    _open_menu(page)
    page.locator("#video-context-menu-portal [data-video-menu-action='stats']").click()
    page.locator("#overlay-video-stats").wait_for(state="visible", timeout=5000)
    toggle = page.locator("#stats-attempts-container [data-vstat-session]").first
    toggle.wait_for(timeout=5000)
    session = page.locator("#stats-attempts-container [id^='vstat-session-']").first
    was_open = session.is_visible()
    toggle.click()
    assert session.is_visible() != was_open
    toggle.click()
    assert session.is_visible() == was_open
    assert page.locator("#stats-attempts-container [onclick]").count() == 0
