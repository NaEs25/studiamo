"""
HTTP-level checks of what an account without a plan can and cannot do.

The test account carries a subscription, so these tests force the plan to "free" inside the
process (the client runs the real app in-process) instead of creating a third account in the
shared database. Nothing here reaches Gemini: every AI route is refused before it would, and
the one that would start an import has its claim replaced.
"""
import pytest

from app import ai, plans


@pytest.fixture
def free_client(client_as, test_username, monkeypatch):
    monkeypatch.setattr(plans, "IS_CLOUD", True)
    monkeypatch.setattr(plans, "get_plan", lambda username: plans.PLAN_FREE)
    from app import config
    monkeypatch.setattr(config, "IS_CLOUD", True)
    return client_as(test_username)


def test_free_account_can_use_routes_that_do_no_ai(free_client):
    assert free_client.get("/api/goals").status_code == 200


def test_free_account_gets_an_empty_home_feed_with_a_flag_instead_of_an_error(free_client):
    response = free_client.get("/api/daily-recommendations")
    assert response.status_code == 200
    body = response.json()
    assert body["requires_plan"] is True and body["recommendations"] == []


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/goals/1/recommendations"),
    ("POST", "/api/goals/1/recommendations/reload_all"),
    ("POST", "/api/daily-recommendations/refresh"),
    ("POST", "/api/quiz/verify-guess"),
])
def test_free_account_is_refused_ai_only_routes_with_a_plan_code(free_client, method, path):
    response = free_client.request(method, path, data={})
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == ai.PLAN_REQUIRED_CODE


def test_import_is_refused_when_the_free_video_is_used(free_client, monkeypatch):
    monkeypatch.setattr(plans, "claim_free_video", lambda user_uuid, ip_hash: plans.CLAIM_USED)
    response = free_client.post("/api/videos", data={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["code"] == ai.PLAN_REQUIRED_CODE and "used" in detail["message"]


def test_import_is_refused_when_no_claim_can_be_made(free_client, monkeypatch):
    monkeypatch.setattr(plans, "claim_free_video", lambda user_uuid, ip_hash: plans.CLAIM_UNAVAILABLE)
    response = free_client.post("/api/videos", data={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == ai.PLAN_REQUIRED_CODE


def test_ai_routes_still_require_a_session(make_client):
    anonymous = make_client(follow_redirects=False)
    assert anonymous.get("/api/goals/1/recommendations").status_code == 401
    assert anonymous.post("/api/videos", data={"url": "https://youtu.be/x"}).status_code == 401
