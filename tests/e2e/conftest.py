"""
Fixtures for browser-driven end-to-end tests.

These tests need a real HTTP server for the browser to talk to (unlike the rest of the
suite, which drives the ASGI app in-process via starlette's TestClient), and they run
against the same shared staging Supabase database as everything else in tests/, under
the same constraint: never create/modify/delete real user data.

To keep that promise, all authenticated flows here run as the dedicated test account
(test_username in tests/conftest.py), not a real customer, and tests that create data
through the UI (e.g. a learning goal) delete it again before finishing.

The local server is started with lifespan="off", like the client fixture in
tests/conftest.py. The real app lifespan starts Telegram long-polling and the notification
scheduler daemon and resumes pending imports (see app/main.py's `lifespan`), all of which the
staging service is already running against the same database. None of that is needed to
serve requests.

Analytics requests to Umami are aborted for every page, so test runs do not show up as
visits in the real analytics.
"""
import json
import re
import socket
import threading
import time
import urllib.request
import urllib.error

import pytest
import uvicorn


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    from app.main import app

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            break
        except urllib.error.HTTPError:
            break  # server responded, just not with 2xx, that's fine, it's up
        except urllib.error.URLError:
            time.sleep(0.1)
    else:
        raise RuntimeError("live_server did not become ready in time")

    yield url

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def base_url(live_server):
    return live_server


@pytest.fixture
def e2e_session_cookies(live_server, test_username, session_token):
    """The yb_session/username cookie pair for the test account, matching exactly what
    app/routers/auth.py sets on a real login (see its set_cookie calls)."""
    return [
        {"name": "yb_session", "value": session_token(test_username), "url": live_server,
         "httpOnly": True, "sameSite": "Lax"},
        {"name": "username", "value": test_username, "url": live_server, "httpOnly": False, "sameSite": "Lax"},
    ]


@pytest.fixture(autouse=True)
def _block_analytics(request):
    if "page" not in request.fixturenames:
        return
    page = request.getfixturevalue("page")
    page.route(re.compile(r"^https://([a-z0-9-]+\.)*umami\.is/"),
               lambda route: route.fulfill(status=200, content_type="application/javascript", body=""))


@pytest.fixture
def logged_in_page(page, e2e_session_cookies):
    page.context.add_cookies(e2e_session_cookies)
    # The app stores the browser's time zone on first load (settings.js
    # captureTimezoneIfMissing). Answered here so test runs never write one to the account.
    page.route("**/api/user/timezone", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"status": "ok", "stored": false}'))
    # The onboarding overlays, What's New and Chompy's "while you were away" overlay would
    # otherwise cover the page whenever the test account's real state calls for them. The
    # onboarding status is answered in full, as an account that has finished onboarding, and
    # its writes are answered too; tests that need another state route over it. Nothing is
    # written to the account.
    page.route("**/api/user/onboarding_status", _answer_json(ONBOARDED_STATUS))
    page.route("**/api/dashboard", _override_json({"chompy": {"eaten_unseen": []}}))
    yield page
    # Handlers that pass a request through (route.fetch) can still be in flight when the test
    # ends, and their failure then surfaces in the next test's setup instead of this one.
    page.unroute_all(behavior="ignoreErrors")


ONBOARDED_STATUS = {
    "has_seen_onboarding": True,
    "has_seen_updates": True,
    "has_seen_reminder_setup": True,
    "has_reminder_channel": True,
    "reminder_email": "",
    "tab_tips": [],
    "suggestions_available": False,
}


def _answer_json(get_body):
    """Route handler that answers GETs with get_body and every other method with a plain ok."""
    def handle(route):
        body = get_body if route.request.method == "GET" else {"status": "ok", "tab_tips": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    return handle


def _override_json(fields):
    """Route handler that passes GETs through to the server and overwrites top-level fields."""
    def handle(route):
        if route.request.method != "GET":
            route.continue_()
            return
        response = route.fetch()
        try:
            body = response.json()
        except Exception:
            route.fulfill(response=response)
            return
        if isinstance(body, dict):
            body.update(fields)
        route.fulfill(response=response, body=json.dumps(body))
    return handle


# A fixed goals tab for the browser tests that work on it: two goals with materials, a study
# queue entry, a loose material, an archived goal and an archived material. Answers the dashboard
# request in full, so nothing is read from the test account's real data.
GOALS_DASHBOARD = {
    "goals": [
        {"id": 9001, "title": "Kubernetes Basics", "description": "Pods and deployments"},
        {"id": 9002, "title": "Spanish", "description": "Everyday conversation"},
    ],
    "archived_goals": [
        {"id": 9003, "title": "Old Photography Course", "description": ""},
    ],
    "videos": [
        {"id": 8001, "title": "Helm charts explained", "learning_goal_id": 9001},
        {"id": 8002, "title": "Pod networking deep dive", "learning_goal_id": 9001},
        {"id": 8003, "title": "Subjuntivo para principiantes", "learning_goal_id": 9002},
        {"id": 8004, "title": "Café vocabulary", "learning_goal_id": 9002},
        {"id": 8005, "title": "Docker cheat sheet", "learning_goal_id": None, "is_watchlist": 1},
        {"id": 8006, "title": "Loose notes on Git", "learning_goal_id": None},
    ],
    "archived": [
        {"id": 8007, "title": "Exposure triangle", "learning_goal_id": None},
    ],
    "quizzes": [],
    "chompy": {"eaten_unseen": []},
}

for _v in GOALS_DASHBOARD["videos"] + GOALS_DASHBOARD["archived"]:
    _v.setdefault("is_watchlist", 0)
    _v.update({"status": "completed", "importance_rating": 3, "importance_level": 3,
               "url": "", "summary": "", "custom_notes": ""})


@pytest.fixture
def goals_page(logged_in_page):
    """The app on the goals tab, showing GOALS_DASHBOARD."""
    page = logged_in_page
    page.route("**/api/dashboard", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(GOALS_DASHBOARD)))
    page.goto("/app")
    page.click("#nav-goals")
    page.wait_for_selector("[data-goal-card='9001']", state="attached", timeout=15000)
    return page
