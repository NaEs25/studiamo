"""
Regression tests for the OAuth state's link intent.

Background: google_callback used to decide "is this a login or a request to link a Google
account to the account already signed in?" by looking at whether a yb_session cookie was
present. A session cookie says nothing about intent, so an ordinary login that arrived with
one took the linking path and overwrote the signed-in account's GOOGLE_ID/GOOGLE_EMAIL/EMAIL
with whichever Google account came back. The original owner then failed to match their own
account on the next login and silently got a new empty one instead.

The intent now travels in the signed state, which only /auth/google?link=true sets. These
tests pin the invariant that matters: nothing except an explicit link request may produce a
state that authorizes rebinding, and no malformed, forged, or legacy state may either.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.dependencies import _sign_oauth_state, _decode_oauth_state

LINK_INTENT = 4  # index of link_intent in the _decode_oauth_state tuple


def test_login_flow_state_never_carries_link_intent():
    state = _sign_oauth_state("/", "", False, "https://www.example.com/login")
    assert _decode_oauth_state(state)[LINK_INTENT] is False


def test_link_flow_state_carries_link_intent():
    state = _sign_oauth_state("/", "", False, "https://www.example.com/", link_intent=True)
    assert _decode_oauth_state(state)[LINK_INTENT] is True


def test_round_trip_preserves_the_other_fields():
    state = _sign_oauth_state("/dev/bugs", "abc123def456", True, "https://www.example.com/x", True)
    dest, ref, require_existing, referrer, link_intent = _decode_oauth_state(state)
    assert dest == "/dev/bugs"
    assert ref == "abc123def456"
    assert require_existing is True
    assert referrer == "https://www.example.com/x"
    assert link_intent is True


@pytest.mark.parametrize("state", [
    None,
    "",
    "not-a-signed-state",
    "/dash|abc123def456|1",           # legacy plain format, predates the intent flag
    _sign_oauth_state("/", "", False, "", True).replace(".", "x", 1),  # tampered signature
])
def test_unusable_state_never_authorizes_a_rebind(state):
    """Every failure path has to fail closed. A state we cannot verify is exactly the case
    where an attacker gets to choose the input, so it must not be the thing that grants the
    one capability that can take an account away from its owner."""
    assert _decode_oauth_state(state)[LINK_INTENT] is False


def test_expired_state_never_authorizes_a_rebind(monkeypatch):
    """The 15 minute window is enforced before any field is read, so an old link state that
    resurfaces (a stale tab, a replayed URL) is inert rather than still privileged."""
    import time
    state = _sign_oauth_state("/", "", False, "", True)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 1000)
    assert _decode_oauth_state(state)[LINK_INTENT] is False
