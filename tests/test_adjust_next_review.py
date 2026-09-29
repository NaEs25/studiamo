"""
adjust_next_review applies the preferred hour as a UTC hour, whatever the host's time zone.
"""
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.dependencies import adjust_next_review


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_any_time_leaves_the_date_alone():
    due = _utc_now() + timedelta(days=3)
    assert adjust_next_review(due, -1) == due


def test_future_day_moves_to_that_utc_hour():
    due = (_utc_now() + timedelta(days=3)).replace(hour=14, minute=37)
    adjusted = adjust_next_review(due, 8)
    assert adjusted == due.replace(hour=8, minute=0, second=0, microsecond=0)


def test_hour_already_past_today_moves_to_tomorrow():
    now = _utc_now()
    past_hour = (now - timedelta(hours=1)).hour
    if past_hour > now.hour:
        pytest.skip("within an hour after midnight UTC, there is no earlier hour today")
    adjusted = adjust_next_review(now, past_hour)
    assert adjusted > now
    assert adjusted.hour == past_hour
    assert adjusted.date() == now.date() + timedelta(days=1)


def test_result_does_not_depend_on_the_host_time_zone(monkeypatch):
    due = (_utc_now() + timedelta(days=2)).replace(hour=14, minute=0)
    expected = adjust_next_review(due, 8)

    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        assert adjust_next_review(due, 8) == expected
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
