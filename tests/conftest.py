"""
Shared pytest fixtures.

These tests run against the shared staging Supabase database. That constraint shapes what test_smoke_routes.py is allowed
to do: hit real endpoints, but never in a way that creates, modifies, or
deletes real data. See the module docstring there for exactly how each
route is handled.

Tests that do need to write (quiz grading, ownership checks, browser tests that create a goal)
run as one of two dedicated staging accounts, never a real customer, and remove every row they
create. Both accounts carry an active subscription status, set by hand, so they pass the
paid-access gate:

- e2e_test_bot: the account every authenticated test uses (test_username).
- e2e_test_bot_b: a second account whose rows the first must never reach, for the ownership
  tests (other_test_username).

Clients here are never entered as a context manager, which would run app.main.lifespan: it
starts the Telegram pollers and the notification scheduler and resumes every pending import task
in the shared staging database, all alongside the running staging service. That means Telegram
getUpdates conflicts, possible duplicate notifications, and imports processed twice. None of it
is needed to serve a request, and the schema it would verify is the one the staging service
already applies on boot.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from starlette.testclient import TestClient

# The host the app's referrer and first-touch logic treats as itself.
LOCAL_BASE_URL = "http://localhost:5005"


@pytest.fixture(scope="session")
def client():
    """In-process client for the real app, shared by every test that uses it, cookie jar
    included. Tests that set cookies use make_client instead."""
    from app.main import app
    yield TestClient(app, follow_redirects=False)


@pytest.fixture
def make_client():
    """Builds a client with a cookie jar of its own, served as LOCAL_BASE_URL. For the real app
    by default, or for a small app a test assembles from one router. Keyword arguments go to
    TestClient (follow_redirects, base_url)."""
    from app.main import app as main_app

    def make(app=None, **kwargs):
        kwargs.setdefault("base_url", LOCAL_BASE_URL)
        return TestClient(app if app is not None else main_app, **kwargs)
    return make


@pytest.fixture(scope="session")
def test_username():
    return "e2e_test_bot"


@pytest.fixture(scope="session")
def other_test_username():
    return "e2e_test_bot_b"


@pytest.fixture(scope="session")
def session_token():
    """Returns the yb_session value app/routers/auth.py sets after a real login, for one of the
    test accounts, minted directly instead of through Google OAuth (which a test cannot drive)."""
    from app.config import get_user_uuid_from_db
    from app.dependencies import _make_session_token

    def mint(username):
        user_uuid = get_user_uuid_from_db(username)
        assert user_uuid, (
            f"Test account '{username}' not found in the database. See the tests/conftest.py "
            "docstring for the accounts the suite expects."
        )
        return _make_session_token(user_uuid)
    return mint


@pytest.fixture
def client_as(make_client, session_token):
    """Builds a client for the real app that is logged in as the given test account."""
    def make(username):
        logged_in = make_client(follow_redirects=False)
        logged_in.cookies.set("yb_session", session_token(username))
        return logged_in
    return make
