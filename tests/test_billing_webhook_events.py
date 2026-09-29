"""
Which Lemon Squeezy webhook events are allowed to change a user's subscription state.

The subscription_payment_* events carry a subscription invoice rather than a subscription.
Applying one wrote the invoice status ("paid") into user_profile.subscription_status, a value
has_app_access() does not grant access for, and the invoice id into ls_subscription_id.

Everything here runs against a bare app with the billing router and a fake connection, so
no request reaches the database or Lemon Squeezy.
"""
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.routers import billing

SECRET = "test_webhook_secret"


def _subscription_payload(event_name: str, status: str = "active") -> dict:
    return {
        "meta": {"event_name": event_name, "custom_data": {"user_uuid": "00000000-0000-4000-8000-000000000001"}},
        "data": {
            "type": "subscriptions",
            "id": "111",
            "attributes": {"status": status, "customer_id": 222, "variant_id": 333},
        },
    }


def _invoice_payload(event_name: str, status: str = "paid") -> dict:
    return {
        "meta": {"event_name": event_name, "custom_data": {"user_uuid": "00000000-0000-4000-8000-000000000001"}},
        "data": {
            "type": "subscription-invoices",
            "id": "999",
            "attributes": {"status": status, "subscription_id": 111, "customer_id": 222},
        },
    }


class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchone(self):
        return {"username": "someone", "user_uuid": "00000000-0000-4000-8000-000000000001"}


class _FakeConn:
    autocommit = True

    def __init__(self, log):
        self.log = log

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.log)


@pytest.fixture
def executed(monkeypatch):
    """Records every statement _apply_subscription_event runs instead of executing it."""
    log = []
    monkeypatch.setattr(billing.database, "get_pooled_raw_connection", lambda: _FakeConn(log))
    monkeypatch.setattr(billing.database, "release_pooled_connection", lambda conn: None)
    monkeypatch.setattr(billing.database, "mark_tester_converted", lambda user_uuid: None)
    return log


@pytest.mark.parametrize("event_name", [
    "subscription_payment_success",
    "subscription_payment_failed",
    "subscription_payment_recovered",
])
def test_payment_events_are_not_subscription_events(event_name):
    assert event_name not in billing._SUBSCRIPTION_EVENTS


def test_invoice_payload_is_refused_without_touching_the_database(executed):
    assert billing._apply_subscription_event("subscription_updated", _invoice_payload("subscription_updated")) is False
    assert executed == []


def test_payload_without_type_is_refused(executed):
    payload = _subscription_payload("subscription_updated")
    del payload["data"]["type"]
    assert billing._apply_subscription_event("subscription_updated", payload) is False
    assert executed == []


def test_subscription_payload_writes_its_own_status_and_id(executed):
    payload = _subscription_payload("subscription_updated", status="past_due")
    assert billing._apply_subscription_event("subscription_updated", payload) is True

    sql, params = executed[-1]
    assert "UPDATE user_profile" in sql
    assert params[0] == "past_due"
    assert params[1] == "111"


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.setattr(billing.config, "IS_CLOUD", True)
    monkeypatch.setattr(billing.config, "get_lemonsqueezy_config", lambda: {"webhook_secret": SECRET})
    app = FastAPI()
    app.include_router(billing.router)
    return TestClient(app)


def _post_signed(client, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/lemonsqueezy",
        content=body,
        headers={"X-Signature": signature, "Content-Type": "application/json"},
    )


def test_signed_payment_success_is_acknowledged_but_not_applied(webhook_client, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("a payment event must not reach _apply_subscription_event")

    monkeypatch.setattr(billing, "_apply_subscription_event", fail)
    response = _post_signed(webhook_client, _invoice_payload("subscription_payment_success"))

    assert response.status_code == 200
    assert response.json() == {"received": True, "handled": False}


def test_signed_subscription_update_is_applied(webhook_client, executed):
    response = _post_signed(webhook_client, _subscription_payload("subscription_updated"))

    assert response.status_code == 200
    assert response.json() == {"received": True, "handled": True}
    assert executed and executed[-1][1][0] == "active"
