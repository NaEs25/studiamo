"""
Which referrer the two row-writing read sites store, and in what order they prefer sources.

- POST /api/waitlist: the client-sent document.referrer, then the orig_ref cookie, then the
  Referer header (which on this POST is our own landing page, so it is a last resort).
- Google callback, new account on the waitlist: the referrer carried in the signed OAuth
  state, then orig_ref, then the Referer header (which at this point is Google's consent
  screen).

Swapping two sources in either chain credits signups to the wrong channel without anything
visibly breaking, which is what these pin. Both handlers write rows, so they run on bare apps
with the database, email and Google calls replaced by fakes. Nothing reaches the shared
staging database.
"""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app import config, database, email_utils, landing_waitlist_db
from app.dependencies import _sign_oauth_state, limiter
from app.routers import auth, landing_waitlist

EXT_BODY = "https://www.reddit.com/r/learnitalian"
EXT_COOKIE = "utm:youtube"
EXT_HEADER = "https://t.co/abc"


# --------------------------------------------------------------------------------------
# POST /api/waitlist
# --------------------------------------------------------------------------------------

class _WaitlistCursor:
    def __init__(self, inserted):
        self.inserted = inserted
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        if sql.lstrip().startswith("INSERT INTO landing_waitlist"):
            self.inserted.append(params)

    def fetchone(self):
        if "RETURNING id" in self._last:
            return {"id": 1}
        if "COUNT(*)" in self._last:
            return {"count": 1}
        return None


class _WaitlistConn:
    def __init__(self, inserted):
        self.inserted = inserted

    def cursor(self):
        return _WaitlistCursor(self.inserted)

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def waitlist(monkeypatch):
    inserted = []
    monkeypatch.setattr(landing_waitlist, "get_waitlist_db", lambda: _WaitlistConn(inserted))
    monkeypatch.setattr(landing_waitlist, "send_waitlist_confirmation_email", lambda email: False)
    monkeypatch.setattr(limiter, "enabled", False)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(landing_waitlist.router)
    client = TestClient(app, base_url="http://localhost:5005")
    return client, inserted


def _post(client, referrer=None, cookie=None, header=None):
    headers = {"Referer": header} if header else {}
    if cookie:
        client.cookies.set("orig_ref", cookie)
    body = {"email": "lead@example.com"}
    if referrer is not None:
        body["referrer"] = referrer
    res = client.post("/api/waitlist", json=body, headers=headers)
    assert res.status_code == 200, res.text


def _stored_referrer(inserted):
    assert len(inserted) == 1
    return inserted[0][3]  # (uuid, email, preference, referrer, country, user_agent)


def test_waitlist_prefers_the_client_sent_referrer(waitlist):
    client, inserted = waitlist
    _post(client, referrer=EXT_BODY, cookie=EXT_COOKIE, header=EXT_HEADER)
    assert _stored_referrer(inserted) == EXT_BODY


def test_waitlist_falls_back_to_the_cookie_when_the_body_is_blank(waitlist):
    client, inserted = waitlist
    _post(client, referrer="   ", cookie=EXT_COOKIE, header=EXT_HEADER)
    assert _stored_referrer(inserted) == EXT_COOKIE


def test_waitlist_uses_the_header_only_without_body_or_cookie(waitlist):
    client, inserted = waitlist
    _post(client, header=EXT_HEADER)
    assert _stored_referrer(inserted) == EXT_HEADER


def test_waitlist_drops_an_internal_referrer(waitlist):
    client, inserted = waitlist
    _post(client, referrer="https://studiamo.cloud/landing")
    assert _stored_referrer(inserted) is None


def test_waitlist_caps_a_long_client_referrer(waitlist):
    client, inserted = waitlist
    _post(client, referrer=EXT_BODY + "/" + "x" * 800)
    assert len(_stored_referrer(inserted)) == 500


# --------------------------------------------------------------------------------------
# Google callback, new account placed on the waitlist
# --------------------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResponse({"access_token": "token"})

    async def get(self, *args, **kwargs):
        return _FakeResponse({"email": "new.person@example.com", "name": "New Person", "id": "g-123"})


class _NoRowsConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return None


@pytest.fixture
def callback(monkeypatch):
    recorded = []
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(config, "IS_SELFHOSTED", False)
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(database, "find_user_by_google_identity", lambda google_id, email: None)
    monkeypatch.setattr(database, "get_db_connection", lambda username: _NoRowsConn())
    monkeypatch.setattr(database, "generate_referral_code", lambda: "abcdefabcdef")
    monkeypatch.setattr(database, "is_at_capacity", lambda: True)
    monkeypatch.setattr(database, "ensure_user_initialized", lambda *a, **k: None)
    monkeypatch.setattr(config, "write_user_config", lambda *a, **k: None)
    monkeypatch.setattr(config, "get_user_uuid_from_db", lambda username: "00000000-0000-4000-8000-000000000002")
    monkeypatch.setattr(auth.moderation, "validate_display_name", lambda name: (True, ""))
    monkeypatch.setattr(email_utils, "send_waitlist_status_email", lambda *a, **k: False)
    monkeypatch.setattr(landing_waitlist_db, "record_waitlist_lead",
                        lambda email, user_uuid, referrer, *a, **k: recorded.append(referrer))
    app = FastAPI()
    app.include_router(auth.router)
    client = TestClient(app, base_url="http://localhost:5005", follow_redirects=False)
    return client, recorded


def _callback(client, state_referrer="", cookie=None, header=None):
    headers = {"Referer": header} if header else {}
    if cookie:
        client.cookies.set("orig_ref", cookie)
    state = _sign_oauth_state("/", "", False, state_referrer)
    res = client.get("/api/auth/google/callback", params={"code": "c", "state": state}, headers=headers)
    assert res.status_code == 303, res.text
    assert res.headers["location"].startswith("/waitlist-confirmation")


def test_callback_prefers_the_referrer_from_the_signed_state(callback):
    client, recorded = callback
    _callback(client, state_referrer=EXT_BODY, cookie=EXT_COOKIE, header=EXT_HEADER)
    assert recorded == [EXT_BODY]


def test_callback_falls_back_to_the_cookie(callback):
    client, recorded = callback
    _callback(client, cookie=EXT_COOKIE, header=EXT_HEADER)
    assert recorded == [EXT_COOKIE]


def test_callback_drops_googles_own_consent_screen(callback):
    client, recorded = callback
    _callback(client, header="https://accounts.google.com/o/oauth2/v2/auth")
    assert recorded == [None]
