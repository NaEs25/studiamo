"""
The one-time reminder step for accounts without a reminder channel, and Chompy's "while you
were away" overlay. Both read state the page fetches on load, which is overridden here, and
every write they make is intercepted, so the account is never changed.
"""
import json
import time


def _override(page, pattern, fields):
    def handle(route):
        if route.request.method != "GET":
            route.continue_()
            return
        response = route.fetch()
        body = response.json()
        body.update(fields)
        route.fulfill(response=response, body=json.dumps(body))
    page.route(pattern, handle)


def _capture_posts(page, pattern, sink):
    def handle(route):
        sink.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json", body='{"status": "ok"}')
    page.route(pattern, handle)


def test_reminder_step_falls_back_to_email(logged_in_page):
    page = logged_in_page
    _override(page, "**/api/user/onboarding_status", {
        "has_seen_onboarding": True,
        "has_seen_reminder_setup": False,
        "has_reminder_channel": False,
        "reminder_email": "learner@example.com",
    })
    saved = []
    _capture_posts(page, "**/api/user/reminder_setup", saved)

    page.goto("/app")
    overlay = page.locator("#overlay-tab-guide")
    overlay.wait_for(state="visible", timeout=15000)
    assert page.inner_text("#onboarding-title") == "Stay on track"
    assert page.locator('[data-step="reminders"]').is_visible()
    assert "learner@example.com" in page.inner_text("#onboarding-reminder-status")

    page.click("#onboarding-next-btn")
    overlay.wait_for(state="hidden", timeout=5000)
    for _ in range(20):
        if saved:
            break
        page.wait_for_timeout(250)
    assert saved and "email" in saved[-1]


def _open_full_tour(page):
    _override(page, "**/api/user/onboarding_status", {
        "has_seen_onboarding": False,
        "has_seen_reminder_setup": False,
        "has_reminder_channel": False,
        "reminder_email": "learner@example.com",
    })
    saved = []
    _capture_posts(page, "**/api/user/reminder_setup", saved)
    page.goto("/app")
    overlay = page.locator("#overlay-tab-guide")
    overlay.wait_for(state="visible", timeout=15000)
    return overlay, saved


def test_tour_starts_with_the_reminder_step(logged_in_page):
    page = logged_in_page
    overlay, saved = _open_full_tour(page)
    assert page.locator('[data-step="reminders"]').is_visible()
    assert page.locator('[data-step="home"]').is_hidden()
    page.click("#onboarding-next-btn")
    page.locator('[data-step="home"]').wait_for(state="visible", timeout=5000)
    assert _wait_for(saved) and "email" in saved[-1]


def test_closing_the_tour_on_the_first_screen_still_saves_the_reminder_choice(logged_in_page):
    page = logged_in_page
    overlay, saved = _open_full_tour(page)
    page.click("#overlay-tab-guide button[onclick^='closeTabGuideModal']")
    overlay.wait_for(state="hidden", timeout=5000)
    assert _wait_for(saved) and "email" in saved[-1]
    page.wait_for_timeout(500)
    assert len(saved) == 1


def _eaten(n):
    return [{"id": 1000 + i, "title": f"Eaten quiz {i + 1}", "importance_rating": 3} for i in range(n)]


def _open_with_eaten(page, n):
    _override(page, "**/api/dashboard", {"chompy": {"eaten_unseen": _eaten(n)}})
    acks = []
    _capture_posts(page, "**/api/chompy/seen", acks)
    page.goto("/app")
    overlay = page.locator("#overlay-chompy-away")
    overlay.wait_for(state="visible", timeout=20000)
    return overlay, acks


def _wait_for(sink):
    for _ in range(20):
        if sink:
            return True
        time.sleep(0.25)
    return False


def test_one_eaten_quiz_offers_the_tickle(logged_in_page):
    page = logged_in_page
    overlay, acks = _open_with_eaten(page, 1)
    assert page.inner_text("#chompy-away-title") == "Chompy ate 'Eaten quiz 1'"
    assert page.locator("#chompy-away-tickle-btn").is_visible()
    assert page.locator("#chompy-away-full").is_hidden()
    page.click("#chompy-away-later")
    overlay.wait_for(state="hidden", timeout=5000)
    assert _wait_for(acks)


def test_tickling_waits_for_the_user_to_start_the_quiz(logged_in_page):
    page = logged_in_page
    overlay, acks = _open_with_eaten(page, 1)
    assert page.locator("#chompy-away-tickle-speech").is_hidden()
    page.click("#chompy-away-tickle-btn")
    page.locator("#chompy-away-start-btn").wait_for(state="visible", timeout=5000)
    assert page.inner_text("#chompy-away-title") == "He spat it back out"
    assert page.inner_text("#chompy-away-tickle-speech") == "Hehe, that tickles!"
    assert page.locator("#chompy-away-tickle-btn").is_hidden()
    assert "chompy-tickled" in page.locator("#chompy-away-tickle-img").get_attribute("src")
    page.wait_for_timeout(1500)
    assert overlay.is_visible()
    page.click("#chompy-away-later")
    overlay.wait_for(state="hidden", timeout=5000)
    assert _wait_for(acks)


def test_the_nothing_is_lost_note_opens_on_click(logged_in_page):
    page = logged_in_page
    overlay, acks = _open_with_eaten(page, 6)
    assert page.locator("#chompy-away-info-text").is_hidden()
    page.click("#chompy-away-info-btn")
    assert "Nothing is lost" in page.inner_text("#chompy-away-info-text")
    page.click("#chompy-away-info-btn")
    assert page.locator("#chompy-away-info-text").is_hidden()
    page.click("#chompy-away-close")
    overlay.wait_for(state="hidden", timeout=5000)


def test_two_to_four_play_the_belt_then_show_the_count(logged_in_page):
    page = logged_in_page
    overlay, acks = _open_with_eaten(page, 3)
    assert page.locator("#chompy-away-roll").is_visible()
    page.locator("#chompy-away-full").wait_for(state="visible", timeout=8000)
    assert page.inner_text("#chompy-away-title") == "Chompy ate 3 quizzes while you were away"
    assert page.inner_text("#chompy-away-bubble") == "3x"
    assert "Eaten quiz" not in overlay.inner_text()
    page.click("#chompy-away-close")
    overlay.wait_for(state="hidden", timeout=5000)
    assert _wait_for(acks)


def test_the_belt_scene_is_a_gif_that_loads_even_with_reduced_motion(logged_in_page):
    page = logged_in_page
    page.emulate_media(reduced_motion="reduce")
    overlay, acks = _open_with_eaten(page, 3)
    assert page.locator("#chompy-away-roll").is_visible()
    assert page.inner_text("#chompy-away-title") == "While you were away..."
    gif = page.locator("#chompy-away-roll img")
    assert gif.get_attribute("src").endswith(".gif")
    assert gif.evaluate("img => img.complete && img.naturalWidth > 0")
    page.locator("#chompy-away-full").wait_for(state="visible", timeout=8000)
    page.click("#chompy-away-close")
    overlay.wait_for(state="hidden", timeout=5000)


def test_more_than_four_show_the_count_only(logged_in_page):
    page = logged_in_page
    overlay, acks = _open_with_eaten(page, 6)
    assert page.locator("#chompy-away-roll").is_hidden()
    assert page.locator("#chompy-away-full").is_visible()
    assert page.inner_text("#chompy-away-bubble") == "6x"
    assert page.inner_text("#chompy-away-title") == "Chompy ate 6 quizzes while you were away"
    page.click("#chompy-away-close")
    overlay.wait_for(state="hidden", timeout=5000)
    assert _wait_for(acks)


def _open_with_due(page, eaten_in_days, day_progress=0.0):
    """Answers the dashboard with one goal, one video per quiz and the given due quizzes, at
    the given point of the user's local day."""
    videos, quizzes = [], []
    for i, days in enumerate(eaten_in_days):
        vid = 990000 + i
        videos.append({"id": vid, "title": f"Due video {i + 1}", "importance_rating": 3, "is_archived": 0,
                       "is_paused": 0, "is_watchlist": 0, "youtube_id": None, "goal_title": "E2E goal",
                       "learning_goal_id": 990000, "summary": [], "status": "done"})
        quizzes.append({"id": vid, "video_id": vid, "quiz_type": "video", "srs_stage": 1, "importance_level": 3,
                        "mastered": False, "is_due": True, "days_until_due": 0, "days_until_eaten": days,
                        "next_review_at": "2026-01-01T00:00:00", "in_progress_index": None})

    def handle(route):
        response = route.fetch()
        body = response.json()
        body.update({
            "goals": [{"id": 990000, "title": "E2E goal", "description": "", "order_index": 0,
                       "has_saved_recommendations": 0}],
            "videos": videos, "quizzes": quizzes, "chompy": {"eaten_unseen": []},
        })
        body.setdefault("user", {})["day_progress"] = day_progress
        route.fulfill(response=response, body=json.dumps(body))

    page.route("**/api/dashboard", handle)
    page.route("**/api/daily-recommendations**", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"recommendations": []}'))
    page.goto("/app")
    page.locator("#due-quizzes-hero").wait_for(state="visible", timeout=15000)
    page.wait_for_function("document.getElementById('belt-chompy-img').dataset.state", timeout=10000)


def test_belt_sleeps_with_nothing_overdue(logged_in_page):
    page = logged_in_page
    _open_with_due(page, [2])
    assert page.locator("#belt-chompy-speech").is_hidden()
    assert page.locator("#belt-chompy-zz").is_visible()
    assert page.locator('[data-belt-station="today"] .belt-doc').count() == 1
    assert page.locator('[data-belt-station="over2"] .belt-doc').count() == 0


def test_belt_and_cards_heat_up_toward_chompy(logged_in_page):
    page = logged_in_page
    _open_with_due(page, [0, 2, 2, 2, 2])
    assert page.inner_text("#belt-chompy-speech") == "Dinner is at midnight!"
    # Four due today collapse into one note with a count.
    assert page.inner_text('[data-belt-station="today"] .belt-doc-badge') == "4x"
    assert page.locator('[data-belt-station="over2"] .belt-doc').count() == 1
    # The overdue card is first, red, and has no "+1 Day".
    first = page.locator("#due-quizzes-list .due-card").first
    assert "due-card-over2" in first.get_attribute("class")
    assert "Save it now" in first.inner_text()
    assert first.locator("[data-plus-day]").count() == 0
    assert page.locator("#due-quizzes-list .due-card-today [data-plus-day]").count() == 4


def test_groups_creep_along_the_belt_through_the_day(logged_in_page):
    page = logged_in_page
    _open_with_due(page, [1, 2], day_progress=0.5)   # noon: half way through each station
    assert page.locator('[data-belt-station="over1"]').evaluate("el => el.style.left") == "50%"
    assert page.locator('[data-belt-station="today"]').evaluate("el => el.style.transform") == "translateX(-50%)"


def test_eaten_card_buttons_work_without_inline_handlers(logged_in_page):
    page = logged_in_page
    videos = [{"id": 990100, "title": "Eaten video", "importance_rating": 3, "is_archived": 0, "is_paused": 1,
               "is_watchlist": 0, "youtube_id": None, "goal_title": "E2E goal", "learning_goal_id": 990000,
               "summary": [], "status": "done", "eaten_at": "2026-10-01T08:00:00"}]

    def handle(route):
        response = route.fetch()
        body = response.json()
        body.update({"goals": [{"id": 990000, "title": "E2E goal", "description": "", "order_index": 0,
                                "has_saved_recommendations": 0}],
                     "videos": videos, "quizzes": [], "chompy": {"eaten_unseen": []}})
        route.fulfill(response=response, body=json.dumps(body))

    page.route("**/api/dashboard", handle)
    page.route("**/api/daily-recommendations**", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"recommendations": []}'))
    page.goto("/app")
    page.wait_for_function("window._videoCardCache && window._videoCardCache[990100]", timeout=15000)
    page.evaluate("window.openStudyStudio = id => { window.__studio = id; }")
    page.evaluate("document.body.insertAdjacentHTML('beforeend', '<div id=\"probe\">' + renderVideoCard(window._videoCardCache[990100]) + '</div>')")
    card = page.locator("#probe #video-card-990100")
    assert card.locator("[data-win-back]").count() == 1
    assert card.locator("[onclick]").locator("text=Watch").count() == 0
    card.locator("[data-open-studio]").dispatch_event("click")
    assert page.evaluate("window.__studio") == 990100
