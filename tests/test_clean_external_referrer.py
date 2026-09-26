"""Pins first-touch referrer attribution: clean_external_referrer and the orig_ref cookie.

Nothing user-facing breaks when this goes wrong. The analytics do: signups get credited to
our own pages, to accounts.google.com, or to nothing, and real acquisition channels quietly
disappear from the landing_waitlist and signup referrer columns.
"""
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
    # Both empty shapes reach this: the `or ""` fallbacks and an unset Pydantic field.
    assert clean_external_referrer("") is None
    assert clean_external_referrer(None) is None
    assert clean_external_referrer("   ") is None
    assert clean_external_referrer("https://accounts.google.com/signin/oauth") is None


def test_clean_external_referrer_matches_domains_not_substrings():
    # "studiamo" is an ordinary Italian word, so sites containing it are real referrers.
    assert clean_external_referrer("https://studiamoinsieme.it/corso") == "https://studiamoinsieme.it/corso"
    assert clean_external_referrer("https://studiamo.cloud.example.com/") == "https://studiamo.cloud.example.com/"
    assert clean_external_referrer("https://notlocalhost.com/p") == "https://notlocalhost.com/p"
    assert clean_external_referrer("https://staging.studiamo.cloud/app") is None


def test_clean_external_referrer_matches_host_header():
    assert clean_external_referrer("https://custom.domain.com/page", request_host="custom.domain.com") is None
    assert clean_external_referrer("https://custom.domain.com:5005/page", request_host="custom.domain.com:5005") is None


def test_clean_external_referrer_preserves_external_and_utm():
    reddit = "https://www.reddit.com/r/learnitalian/comments/123"
    assert clean_external_referrer(reddit) == reddit

    # Not redundant: proves the accounts.google rule leaves ordinary Google search alone.
    google = "https://www.google.com/"
    assert clean_external_referrer(google) == google

    assert clean_external_referrer("HTTPS://REDDIT.COM/X") == "HTTPS://REDDIT.COM/X"
    assert clean_external_referrer("utm:youtube") == "utm:youtube"
    assert clean_external_referrer("UTM:reddit") == "UTM:reddit"


def test_clean_external_referrer_rejects_malformed_input():
    # landing_waitlist feeds client JSON straight in, so this is the one untrusted shape.
    assert clean_external_referrer("reddit.com/r/x") is None
    assert clean_external_referrer("https://user:pw@example.com/p") is None


def test_clean_external_referrer_caps_length():
    long_url = "https://www.reddit.com/" + "a" * 600
    assert clean_external_referrer(long_url) == long_url[:500]
    assert len(clean_external_referrer("utm:" + "x" * 600)) == 500


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
