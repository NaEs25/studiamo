import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.dependencies import clean_external_referrer, _decode_oauth_state
from app.main import app


def test_clean_external_referrer_filters_internal():
    assert clean_external_referrer("https://www.studiamo.cloud/login") is None
    assert clean_external_referrer("https://studiamo.cloud/landing") is None
    assert clean_external_referrer("http://localhost:5005/login") is None
    assert clean_external_referrer("http://127.0.0.1:8000/") is None
    assert clean_external_referrer("/login") is None
    assert clean_external_referrer("") is None
    assert clean_external_referrer(None) is None
    assert clean_external_referrer("https://accounts.google.com/signin/oauth") is None


def test_clean_external_referrer_matches_host_header():
    assert clean_external_referrer("https://custom.domain.com/page", request_host="custom.domain.com") is None
    assert clean_external_referrer("https://custom.domain.com:5005/page", request_host="custom.domain.com:5005") is None


def test_clean_external_referrer_preserves_external_and_utm():
    reddit = "https://www.reddit.com/r/learnitalian/comments/123"
    assert clean_external_referrer(reddit) == reddit

    twitter = "https://t.co/abc123"
    assert clean_external_referrer(twitter) == twitter

    google = "https://www.google.com/"
    assert clean_external_referrer(google) == google

    assert clean_external_referrer("utm:youtube") == "utm:youtube"


def test_first_touch_middleware_sets_orig_ref_cookie():
    client = TestClient(app, base_url="http://localhost:5005")
    
    # 1. Arrival from external site sets orig_ref cookie
    res = client.get("/login", headers={"Referer": "https://www.reddit.com/r/learnitalian"})
    assert res.status_code == 200
    assert "orig_ref" in res.cookies
    assert "reddit.com" in res.cookies["orig_ref"]

    # 2. Arrival with utm_source sets utm tag in orig_ref cookie
    res_utm = client.get("/login?utm_source=youtube_launch")
    assert res_utm.status_code == 200
    assert "orig_ref" in res_utm.cookies
    assert res_utm.cookies["orig_ref"] == "utm:youtube_launch"

    # 3. Internal navigation does not set orig_ref
    res_internal = client.get("/login", headers={"Referer": "http://localhost:5005/science"})
    assert res_internal.status_code == 200
    assert "orig_ref" not in res_internal.cookies


def test_oauth_login_carries_orig_ref_cookie_into_state():
    from urllib.parse import urlparse, parse_qs
    client = TestClient(app, base_url="http://localhost:5005")
    client.cookies.set("orig_ref", "https://www.reddit.com/r/learnitalian")

    # Click continue with Google on /login (browser sends internal referer header)
    res = client.get(
        "/api/auth/google",
        headers={"Referer": "http://localhost:5005/login"},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303, 307)
    loc = res.headers["location"]
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query)
    state = qs["state"][0]
    
    dest, ref, require_existing, referrer, link_intent = _decode_oauth_state(state)
    assert referrer == "https://www.reddit.com/r/learnitalian"
