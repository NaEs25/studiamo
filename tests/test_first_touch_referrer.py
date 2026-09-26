"""Pins the first-touch rule of capture_first_touch_referrer_middleware.

The orig_ref cookie is written once and must never be overwritten by a later request.
Without that guard it becomes last-touch and every OAuth signup is credited to whatever
page the visitor saw last. Plain GETs only: the suite runs against the shared staging
database, so these assert on Set-Cookie and create no rows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app

EXTERNAL = "https://www.reddit.com/r/learnitalian"


def _client():
    return TestClient(app, base_url="http://localhost:5005")


def test_existing_orig_ref_is_not_overwritten():
    client = _client()
    client.cookies.set("orig_ref", "utm:reddit")
    res = client.get("/login?utm_source=youtube", headers={"Referer": "https://t.co/abc"})
    assert res.status_code == 200
    assert "orig_ref" not in res.cookies


def test_utm_source_wins_over_external_referer():
    res = _client().get("/login?utm_source=reddit", headers={"Referer": "https://t.co/abc"})
    assert res.cookies.get("orig_ref") == "utm:reddit"


def test_static_paths_set_nothing():
    res = _client().get("/static/manifest.json", headers={"Referer": EXTERNAL})
    assert "orig_ref" not in res.cookies


def test_non_get_requests_set_nothing():
    # HEAD reaches the middleware without touching any handler that writes.
    res = _client().head("/login", headers={"Referer": EXTERNAL})
    assert "orig_ref" not in res.cookies
