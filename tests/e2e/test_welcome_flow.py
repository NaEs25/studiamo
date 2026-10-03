"""
The welcome flow new accounts go through once (settings.js ONBOARDING_FLOWS.welcome), and the tab
tour behind Settings' "Welcome Guide" button. The onboarding status
and the dashboard are answered with fixed data, and every write the flow makes (goal, import,
reminder choice, onboarding status) is answered by a mocked route, so the test account is never
changed.
"""
import json
import re
import time

import pytest

GOAL_ID = 990500
VIDEO_ID = 990600
QUIZ_ID = 990700
TASK_ID = 990800
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

NEW_ACCOUNT = {
    "has_seen_onboarding": False,
    "has_seen_updates": True,
    "has_seen_reminder_setup": False,
    "has_reminder_channel": False,
    "reminder_email": "learner@example.com",
}

def _form(request):
    """The fields of a multipart form body, which is what fetch sends for a FormData."""
    return dict(re.findall(r'name="([^"]+)"\r\n\r\n(.*?)\r\n--', request.post_data or "", re.S))


def _json(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class Backend:
    """Answers every route the welcome flow touches, and records what it was sent."""

    def __init__(self, page, status):
        self.status = dict(status)
        self.goals = []
        self.task_status = "processing"
        self.imported = False
        self.sent = {}  # route name -> list of form dicts
        self.errors = []
        page.on("pageerror", lambda err: self.errors.append(str(err)))

        page.route("**/api/user/onboarding_status", self._onboarding_status)
        page.route("**/api/user/reminder_setup", self._record("reminder_setup", {"status": "ok"}))
        page.route("**/api/dashboard", lambda route: _json(route, self._dashboard()))
        page.route("**/api/daily-recommendations**", lambda route: _json(route, {"recommendations": []}))
        page.route("**/api/goals", self._goals)
        page.route("**/api/goals/*/edit", self._edit_goal)
        page.route("**/api/videos", self._import)
        page.route("**/api/videos/import-tasks", lambda route: _json(route, self._tasks()))
        page.route(f"**/api/videos/{VIDEO_ID}/generate_quiz",
                   self._record("generate_quiz", {"status": "success", "quiz_id": QUIZ_ID}))
        page.route(f"**/api/quiz/{QUIZ_ID}", lambda route: _json(route, {
            "quiz_type": "video", "video_title": "My first video", "is_due": True,
            "questions": [{"question": "What does a node do?", "answer": "It applies one adjustment.",
                           "options": ["One adjustment", "Nothing", "Exports", "Imports"],
                           "correct_index": 0}],
        }))

    def calls(self, name):
        return self.sent.get(name, [])

    def _note(self, name, route):
        self.sent.setdefault(name, []).append(_form(route.request))

    def _record(self, name, body):
        def handle(route):
            self._note(name, route)
            _json(route, body)
        return handle

    def _onboarding_status(self, route):
        if route.request.method == "GET":
            _json(route, self.status)
            return
        self._note("onboarding_status", route)
        _json(route, {"status": "ok"})

    def _dashboard(self):
        return {"goals": self.goals, "archived_goals": [], "videos": [], "archived": [], "quizzes": [],
                "chompy": {"eaten_unseen": []}}

    def _goals(self, route):
        if route.request.method == "GET":
            _json(route, self.goals)
            return
        self._note("create_goal", route)
        title = self.sent["create_goal"][-1]["title"]
        self.goals.append({"id": GOAL_ID, "title": title, "description": "", "order_index": 1,
                           "has_saved_recommendations": 0})
        _json(route, {"status": "success", "goal_id": GOAL_ID, "title": title})

    def _edit_goal(self, route):
        self._note("edit_goal", route)
        self.goals[0]["title"] = self.sent["edit_goal"][-1]["title"]
        _json(route, {"status": "success"})

    def _import(self, route):
        self._note("import", route)
        self.imported = True
        _json(route, {"status": "processing", "video_id": VIDEO_ID, "task_id": TASK_ID,
                      "title": "YouTube Video (abcDEF12345)"})

    def _tasks(self):
        if not self.imported:
            return []
        return [{"id": TASK_ID, "video_id": VIDEO_ID, "task_type": "youtube", "title": "My first video",
                 "status": self.task_status, "progress_stage": None, "error_message": None,
                 "thumbnail_url": None, "youtube_id": "abcDEF12345", "duration_seconds": 600}]


def _wait_until(page, predicate, timeout=5000):
    # page.wait_for_timeout rather than time.sleep: route handlers only run while Playwright
    # has control, so sleeping would hold back the very request being waited for.
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if predicate():
            return True
        page.wait_for_timeout(100)
    return predicate()


def _open(page, status=NEW_ACCOUNT):
    backend = Backend(page, status)
    page.goto("/app")
    page.locator("#overlay-tab-guide").wait_for(state="visible", timeout=15000)
    return backend


def _step(page, name):
    page.locator(f'#onboarding-steps [data-step="{name}"]').wait_for(state="visible", timeout=5000)


def _next(page):
    page.click("#onboarding-next-btn")


def _to_goal_step(page):
    _step(page, "chompy")
    _next(page)
    _step(page, "how")
    _next(page)
    _step(page, "goal")


def _to_video_step(page, title="Video editing"):
    _to_goal_step(page)
    page.fill("#onboarding-goal-input", title)
    _next(page)
    _step(page, "video")


def _to_reminders_with_a_link(page):
    _to_video_step(page)
    page.fill("#onboarding-video-url", "https://www.youtube.com/watch?v=abcDEF12345")
    _next(page)
    _step(page, "reminders")


def test_full_flow_with_a_link_starts_the_first_quiz(logged_in_page):
    page = logged_in_page
    # Headless Chromium reports notifications as denied whatever is granted. A desktop browser
    # that has not asked yet says "default", which is what this test is about.
    page.add_init_script("Object.defineProperty(Notification, 'permission', { get: () => 'default' })")
    backend = _open(page)

    # Email is the fallback from the moment the flow opens, so a tab closed anywhere in it
    # still leaves the account with reminders.
    assert _wait_until(page, lambda: backend.calls("reminder_setup"))
    assert backend.calls("reminder_setup")[0]["channel"] == "email"

    assert page.inner_text("#onboarding-eyebrow").lower() == "welcome"
    assert page.locator("#onboarding-dots .onboarding-dot").count() == 5
    assert page.inner_text("#onboarding-next-btn").strip() == "How do I stop him?"
    assert page.locator("#onboarding-back-btn").is_hidden()
    _next(page)
    _step(page, "how")
    _next(page)
    _step(page, "goal")

    # The goal is required.
    _next(page)
    assert page.locator("#onboarding-goal-error").is_visible()
    assert not backend.calls("create_goal")
    _step(page, "goal")

    page.click('[data-goal-chip="Video editing"]')
    assert page.input_value("#onboarding-goal-input") == "Video editing"
    assert "is-active" in page.get_attribute('[data-goal-chip="Video editing"]', "class")
    _next(page)
    _step(page, "video")
    assert backend.calls("create_goal") == [{"title": "Video editing"}]

    _next(page)
    assert page.locator("#onboarding-video-error").is_visible()
    assert not backend.calls("import")

    page.fill("#onboarding-video-url", "https://www.youtube.com/watch?v=abcDEF12345")
    _next(page)
    _step(page, "reminders")
    sent = backend.calls("import")[0]
    assert sent["url"] == "https://www.youtube.com/watch?v=abcDEF12345"
    assert sent["learning_goal_id"] == str(GOAL_ID)
    assert page.inner_text("#onboarding-import-status-text") == "Your first quiz is being made"

    # Desktop Chromium can take push in the tab, so it gets the button, not the iPhone steps.
    assert page.locator("#onboarding-reminder-push-btn").is_visible()
    assert page.locator("#onboarding-ios-install").is_hidden()
    assert "email your reminders" in page.inner_text("#onboarding-reminder-status")
    assert page.locator("#onboarding-reminder-settings-btn").is_hidden()

    # Back shows the started import instead of offering to send another.
    page.click("#onboarding-back-btn")
    _step(page, "video")
    assert page.locator("#onboarding-video-started").is_visible()
    assert page.locator("#onboarding-video-pick").is_hidden()
    _next(page)
    _step(page, "reminders")
    assert len(backend.calls("import")) == 1

    backend.task_status = "completed"
    page.wait_for_function(
        "document.getElementById('onboarding-import-status-text').textContent === 'Your first quiz is ready'",
        timeout=10000)
    assert page.inner_text("#onboarding-next-btn").strip() == "Start learning"
    _next(page)
    page.locator("#overlay-quiz").wait_for(state="visible", timeout=10000)
    assert page.locator("#overlay-tab-guide").is_hidden()
    assert backend.calls("generate_quiz")
    assert {"has_seen_onboarding": "true"} in backend.calls("onboarding_status")
    assert not backend.errors


def test_going_back_renames_the_goal_instead_of_adding_one(logged_in_page):
    page = logged_in_page
    backend = _open(page)
    _to_video_step(page, "Programming")
    page.click("#onboarding-back-btn")
    _step(page, "goal")
    page.fill("#onboarding-goal-input", "Python")
    _next(page)
    _step(page, "video")
    assert len(backend.calls("create_goal")) == 1
    assert backend.calls("edit_goal") == [{"title": "Python"}]


def test_a_quiz_still_being_made_lands_on_home_with_the_import_list(logged_in_page):
    page = logged_in_page
    backend = _open(page)
    _to_reminders_with_a_link(page)
    _next(page)
    page.locator("#overlay-tab-guide").wait_for(state="hidden", timeout=5000)
    assert page.locator("#tab-dashboard").is_visible()
    page.locator("#import-widget-panel").wait_for(state="visible", timeout=5000)
    assert not backend.calls("generate_quiz")


def test_skipping_the_video_lands_on_the_goals_tab(logged_in_page):
    page = logged_in_page
    backend = _open(page)
    _to_video_step(page)
    page.click("#onboarding-skip-video-btn")
    _step(page, "reminders")
    assert page.locator("#onboarding-import-status").is_hidden()
    _next(page)
    page.locator("#overlay-tab-guide").wait_for(state="hidden", timeout=5000)
    assert not backend.calls("import")

    page.locator("#tab-goals").wait_for(state="visible", timeout=5000)
    assert not backend.errors


def test_there_is_no_way_out_but_forward(logged_in_page):
    page = logged_in_page
    _open(page)
    overlay = page.locator("#overlay-tab-guide")
    for name in ("chompy", "how", "goal"):
        _step(page, name)
        assert page.locator("#onboarding-close-btn").is_hidden()
        page.keyboard.press("Escape")
        page.mouse.click(5, 5)  # the backdrop, outside the card
        assert overlay.is_visible()
        if name == "goal":
            break
        _next(page)
    _step(page, "goal")


@pytest.mark.browser_context_args(user_agent=IPHONE_UA, viewport={"width": 390, "height": 844})
def test_iphone_safari_gets_the_install_steps_instead_of_push(logged_in_page):
    page = logged_in_page
    _open(page)
    _to_video_step(page)
    page.click("#onboarding-skip-video-btn")
    _step(page, "reminders")
    assert page.locator("#onboarding-ios-install").is_visible()
    assert "Add to Home Screen" in page.inner_text("#onboarding-ios-install")
    assert page.locator("#onboarding-reminder-push-btn").is_hidden()

    info = page.locator("#onboarding-reminder-info")
    assert info.is_hidden()
    page.click("#onboarding-reminder-info-btn")
    assert info.is_visible()
    assert "email is the default" in info.inner_text()
    assert page.get_attribute("#onboarding-reminder-info-btn", "aria-expanded") == "true"


def test_accounts_that_finished_onboarding_do_not_see_it(logged_in_page):
    page = logged_in_page
    backend = Backend(page, {**NEW_ACCOUNT, "has_seen_onboarding": True, "has_seen_reminder_setup": True,
                             "has_reminder_channel": True})
    with page.expect_response("**/api/user/onboarding_status"):
        page.goto("/app")
    page.wait_for_timeout(1000)
    assert page.locator("#overlay-tab-guide").is_hidden()
    assert not backend.calls("reminder_setup")
    assert not backend.calls("onboarding_status")


def test_the_welcome_guide_button_opens_the_tab_tour(logged_in_page):
    page = logged_in_page
    backend = Backend(page, {**NEW_ACCOUNT, "has_seen_onboarding": True, "has_seen_reminder_setup": True,
                             "has_reminder_channel": True})
    page.goto("/app")
    page.click("#nav-settings")
    page.click("#tab-settings button[onclick^='openTabGuideModal']")
    overlay = page.locator("#overlay-tab-guide")
    overlay.wait_for(state="visible", timeout=5000)
    _step(page, "tour-home")
    assert page.inner_text("#onboarding-eyebrow").lower() == "app tour"
    assert page.locator("#onboarding-close-btn").is_visible()
    _next(page)
    _step(page, "tour-goals")
    page.keyboard.press("Escape")
    overlay.wait_for(state="hidden", timeout=5000)
    assert not backend.calls("reminder_setup")
    assert not backend.calls("onboarding_status")
