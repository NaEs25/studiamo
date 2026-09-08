"""
Coverage for the tester-access notification follow-through (app/tester_notify.py).

The thing worth testing here is not the email body, it is the reporting. A grant that
committed while the email did not go out is a normal, recoverable outcome, and the only way
anyone finds out is the report this module returns. So every branch has to be distinguishable
from "it all worked": a caller that cannot tell them apart shows a tick and the person is
never told.

No database and no network: notify_granted's only two side effects are the send and the
stamp, and both are replaced here. In line with the rest of this suite, which runs against
the shared staging database and must never write to it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import tester_notify


NOW = datetime.now(timezone.utc)


@pytest.fixture
def sends(monkeypatch):
    """Records what would have been emailed and stamped, and lets a test choose the outcome.

    `result` is what the fake send returns (True/False), `raises` makes it raise, standing in
    for Resend being unreachable."""
    calls = {"emails": [], "stamps": [], "result": True, "raises": None}

    def fake_send(recipient, expires_at=None):
        calls["emails"].append((recipient, expires_at))
        if calls["raises"]:
            raise calls["raises"]
        return calls["result"]

    def fake_stamp(grant_id, conn=None):
        calls["stamps"].append(grant_id)

    monkeypatch.setattr(tester_notify.email_utils, "send_tester_access_email", fake_send)
    monkeypatch.setattr(tester_notify.database, "mark_tester_notified", fake_stamp)
    return calls


def _row(**overrides):
    row = {"username": "tester_one", "google_email": "signin@example.com",
           "email": "old@example.com", "grant_id": 42,
           "expires_at": NOW + timedelta(days=30)}
    row.update(overrides)
    return row


def test_sends_to_google_email_and_stamps(sends):
    report = tester_notify.notify_granted(_row())
    assert report["email_sent"] is True
    assert report["reason"] is None
    assert sends["emails"] == [("signin@example.com", _row()["expires_at"])]
    assert sends["stamps"] == [42]


def test_google_email_wins_over_the_profile_email(sends):
    """`email` can hold a hand-seeded value with nothing behind it; google_email is the
    address tied to the identity the account actually signs in with."""
    tester_notify.notify_granted(_row())
    assert sends["emails"][0][0] == "signin@example.com"


def test_falls_back_to_email_when_there_is_no_google_email(sends):
    tester_notify.notify_granted(_row(google_email=None))
    assert sends["emails"][0][0] == "old@example.com"


def test_unlimited_grant_passes_no_expiry(sends):
    """period_days = 0 means no end date, and the email says so instead of naming a date."""
    tester_notify.notify_granted(_row(expires_at=None))
    assert sends["emails"][0][1] is None


def test_send_email_false_sends_nothing_and_says_why(sends):
    report = tester_notify.notify_granted(_row(), send_email=False)
    assert sends["emails"] == []
    assert sends["stamps"] == []
    assert report["email_sent"] is False
    assert "as requested" in report["reason"]
    # Flagged as well as worded, so a surface can tell the one reason the operator chose
    # apart from the two that went wrong without matching on the sentence.
    assert report["email_skipped"] is True


@pytest.mark.parametrize("row, result", [
    (_row(), True),
    (_row(google_email=None, email=None), True),
    (_row(), False),
])
def test_email_skipped_is_only_true_when_the_operator_asked(sends, row, result):
    """Every other outcome is something to raise, so none of them may borrow the one flag
    that suppresses the message."""
    sends["result"] = result
    assert tester_notify.notify_granted(row)["email_skipped"] is False


def test_no_address_on_file_is_reported_not_raised(sends):
    """The grant is already committed by the time this runs, so a missing address is
    something to report, never something to fail on."""
    report = tester_notify.notify_granted(_row(google_email=None, email=None))
    assert sends["emails"] == []
    assert report["email_sent"] is False
    assert report["recipient"] is None
    assert "No email address on file" in report["reason"]


def test_a_failed_send_is_not_stamped(sends):
    """notified_at means "this person was told". Stamping a failed send would turn a
    recoverable miss into an invisible one."""
    sends["result"] = False
    report = tester_notify.notify_granted(_row())
    assert sends["stamps"] == []
    assert report["email_sent"] is False
    assert "could not be sent" in report["reason"]


def test_a_raising_send_is_caught_and_reported(sends):
    sends["raises"] = RuntimeError("resend is down")
    report = tester_notify.notify_granted(_row())
    assert report["email_sent"] is False
    assert "could not be sent" in report["reason"]


def test_a_failed_stamp_does_not_undo_a_successful_send(sends, monkeypatch):
    """The email is out and cannot be recalled, so a stamp that fails must not report the
    send as having failed. It is logged and the report stays truthful about what happened."""
    def boom(grant_id, conn=None):
        raise RuntimeError("wrong database")

    monkeypatch.setattr(tester_notify.database, "mark_tester_notified", boom)
    report = tester_notify.notify_granted(_row())
    assert report["email_sent"] is True
    assert report["reason"] is None
