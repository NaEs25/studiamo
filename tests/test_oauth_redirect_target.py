"""
Regression tests for the post-login redirect target.

The target arrives as a query param on /api/auth/google, travels through the OAuth state,
and is followed after the Google callback. It must only ever be a path on this site: a
leading "/" is not sufficient, since "//host" and "/\\host" are read by browsers as another
origin.
"""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.dependencies import safe_local_path, _sign_oauth_state, _decode_oauth_state

DEST = 0  # index of dest_path in the _decode_oauth_state tuple

REJECTED = [
    "//example.com",
    "//example.com/path",
    "/\\example.com",
    "/\t/example.com",
    "/\n/example.com",
    "https://example.com",
    "example.com",
    "",
    None,
    "\\\\example.com",
]

ACCEPTED = ["/", "/bugs", "/app", "/waitlist-confirmation?ref=abc123", "/science#evidence"]


@pytest.mark.parametrize("value", REJECTED)
def test_safe_local_path_rejects_anything_that_can_leave_the_site(value):
    assert safe_local_path(value) == "/"


@pytest.mark.parametrize("value", ACCEPTED)
def test_safe_local_path_keeps_ordinary_site_paths(value):
    assert safe_local_path(value) == value


@pytest.mark.parametrize("value", REJECTED)
def test_signed_state_never_decodes_to_an_off_site_target(value):
    state = _sign_oauth_state(value, "", False)
    assert _decode_oauth_state(state)[DEST] == "/"


@pytest.mark.parametrize("value", ["//example.com", "/\\example.com"])
def test_legacy_unsigned_state_never_decodes_to_an_off_site_target(value):
    # The legacy "dest|ref|require_existing" format is unsigned, so anyone can hand-write it.
    assert _decode_oauth_state(f"{value}|abc|0")[DEST] == "/"


def test_signed_state_keeps_a_normal_target():
    assert _decode_oauth_state(_sign_oauth_state("/bugs", "", False))[DEST] == "/bugs"


@pytest.mark.parametrize("redirect,expected", [("//example.com", "/"), ("/\\example.com", "/"), ("/bugs", "/bugs")])
def test_google_login_endpoint_sanitizes_redirect_param(monkeypatch, redirect, expected):
    from app.main import app
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/api/auth/google", params={"redirect": redirect})
    assert resp.status_code in (302, 307)
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    assert _decode_oauth_state(state)[DEST] == expected
