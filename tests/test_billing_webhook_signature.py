"""
Regression coverage for the Lemon Squeezy webhook's HMAC check.

_verify_signature is the only thing standing between /webhooks/lemonsqueezy and anyone on
the internet granting themselves a subscription (see its own docstring in routers/billing.py).
Nothing else in the suite exercised it, so a change that silently weakened it, always-True,
wrong digest, non-constant-time comparison, would not have failed anything.
"""
import hashlib
import hmac

from app.routers.billing import _verify_signature

SECRET = "test_webhook_secret"
BODY = b'{"meta":{"event_name":"subscription_created"},"data":{"id":"1"}}'


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_accepts_correct_signature():
    assert _verify_signature(BODY, _sign(BODY, SECRET), SECRET) is True


def test_rejects_wrong_signature():
    assert _verify_signature(BODY, "0" * 64, SECRET) is False


def test_rejects_signature_signed_with_wrong_secret():
    assert _verify_signature(BODY, _sign(BODY, "a_different_secret"), SECRET) is False


def test_rejects_tampered_body():
    valid_sig = _sign(BODY, SECRET)
    assert _verify_signature(BODY + b"tampered", valid_sig, SECRET) is False


def test_rejects_missing_signature():
    assert _verify_signature(BODY, "", SECRET) is False
    assert _verify_signature(BODY, None, SECRET) is False
