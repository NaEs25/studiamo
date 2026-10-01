"""
Fixtures for browser-driven end-to-end tests.

These tests need a real HTTP server for the browser to talk to (unlike the rest of the
suite, which drives the ASGI app in-process via starlette's TestClient), and they run
against the same shared staging Supabase database as everything else in tests/, under
the same constraint: never create/modify/delete real user data.

To keep that promise, all authenticated flows here run as one dedicated, clearly-named
account (`E2E_TEST_USERNAME` below), not a real customer, and tests that create data
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

E2E_TEST_USERNAME = "e2e_test_bot"


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
def e2e_session_cookies(live_server):
    """The yb_session/username cookie pair for E2E_TEST_USERNAME, matching exactly what
    app/routers/auth.py sets on a real login (see its set_cookie calls), minted directly
    via app.dependencies._make_session_token instead of driving a real Google OAuth
    consent screen, which isn't something a headless browser can do against Google."""
    from app.config import get_user_uuid_from_db
    from app.dependencies import _make_session_token

    user_uuid = get_user_uuid_from_db(E2E_TEST_USERNAME)
    assert user_uuid, (
        f"Test account '{E2E_TEST_USERNAME}' not found in the database. "
        "See tests/e2e/conftest.py docstring for how it's provisioned."
    )
    token = _make_session_token(user_uuid)
    return [
        {"name": "yb_session", "value": token, "url": live_server, "httpOnly": True, "sameSite": "Lax"},
        {"name": "username", "value": E2E_TEST_USERNAME, "url": live_server, "httpOnly": False, "sameSite": "Lax"},
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
    # The test account has no reminder channel and may have reviews Chompy ate, so the one-time
    # reminder step and the "while you were away" overlay would cover the page in every test.
    # Both are answered as already handled; nothing is written to the account.
    page.route("**/api/user/onboarding_status", _override_json({"has_seen_reminder_setup": True}))
    page.route("**/api/dashboard", _override_json({"chompy": {"eaten_unseen": []}}))
    yield page
    # Handlers that pass a request through (route.fetch) can still be in flight when the test
    # ends, and their failure then surfaces in the next test's setup instead of this one.
    page.unroute_all(behavior="ignoreErrors")


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
