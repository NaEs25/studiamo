"""
Covers the day-based review rules: a review is due for its whole local day, and the hour stored
in next_review_at does not matter. These replaced adjust_next_review, which snapped reviews to a
preferred UTC hour.
"""
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app import local_days
from app.dependencies import effective_reminder_hour

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")


def test_unknown_or_missing_zone_is_utc():
    assert local_days.resolve_timezone(None) is timezone.utc
    assert local_days.resolve_timezone("") is timezone.utc
    assert local_days.resolve_timezone("Not/AZone") is timezone.utc
    assert local_days.resolve_timezone("Europe/Berlin") == BERLIN


@pytest.mark.parametrize("name, ok", [
    ("Europe/Berlin", True),
    ("UTC", True),
    ("Not/AZone", False),
    ("", False),
    (None, False),
    ("../../etc/passwd", False),
    ("x" * 100, False),
])
def test_is_valid_timezone(name, ok):
    assert local_days.is_valid_timezone(name) is ok


def test_schedule_review_lands_on_local_midnight():
    now = datetime(2026, 8, 17, 10, 0)  # Monday 12:00 Berlin
    due = local_days.schedule_review(3, BERLIN, now=now)
    # Thursday 00:00 Berlin is Wednesday 22:00 UTC in summer.
    assert due == datetime(2026, 8, 19, 22, 0)
    assert local_days.local_date(due, BERLIN) == date(2026, 8, 20)


def test_schedule_review_is_never_earlier_than_tomorrow():
    # 0.7 days from 06:00 would still be today; the user just finished this quiz.
    now = datetime(2026, 8, 17, 4, 0)  # Monday 06:00 Berlin
    due = local_days.schedule_review(0.7, BERLIN, now=now)
    assert local_days.local_date(due, BERLIN) == date(2026, 8, 18)


def test_fractional_intervals_follow_the_clock():
    # 1.5 days from Monday 20:00 lands Wednesday 08:00, so the review is due Wednesday.
    now = datetime(2026, 8, 17, 18, 0)  # Monday 20:00 Berlin
    due = local_days.schedule_review(1.5, BERLIN, now=now)
    assert local_days.local_date(due, BERLIN) == date(2026, 8, 19)


def test_due_for_the_whole_local_day():
    due = local_days.schedule_review(1, BERLIN, now=datetime(2026, 8, 17, 10, 0))  # due Tuesday
    assert not local_days.is_due(due, BERLIN, now=datetime(2026, 8, 17, 21, 59))  # Mon 23:59
    assert local_days.is_due(due, BERLIN, now=datetime(2026, 8, 17, 22, 0))       # Tue 00:00
    assert local_days.is_due(due, BERLIN, now=datetime(2026, 8, 18, 21, 0))       # Tue 23:00


def test_legacy_rows_with_an_hour_are_due_from_the_start_of_that_day():
    # Rows written before day-based scheduling hold arbitrary hours, e.g. 18:00 UTC.
    legacy = datetime(2026, 8, 18, 18, 0)
    assert local_days.is_due(legacy, BERLIN, now=datetime(2026, 8, 18, 6, 0))


def test_days_until_due():
    due = datetime(2026, 8, 20, 22, 0)  # Friday 00:00 Berlin
    now = datetime(2026, 8, 17, 10, 0)  # Monday
    assert local_days.days_until_due(due, BERLIN, now=now) == 4
    assert local_days.days_until_due(due, BERLIN, now=datetime(2026, 8, 23, 10, 0)) == -2
    assert local_days.days_until_due(None, BERLIN, now=now) is None


def test_missing_next_review_is_not_due():
    assert local_days.is_due(None, BERLIN) is False


def test_iso_strings_and_aware_values_are_accepted():
    now = datetime(2026, 8, 18, 10, 0)
    assert local_days.is_due("2026-08-18T00:00:00", BERLIN, now=now)
    assert local_days.is_due(datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc), BERLIN, now=now)


def test_dst_change_keeps_midnight():
    # Berlin leaves summer time on 2026-10-25: midnight moves from 22:00 to 23:00 UTC.
    before = local_days.local_midnight_utc(date(2026, 10, 25), BERLIN)
    after = local_days.local_midnight_utc(date(2026, 10, 26), BERLIN)
    assert before == datetime(2026, 10, 24, 22, 0)
    assert after == datetime(2026, 10, 25, 23, 0)


def test_result_does_not_depend_on_the_host_time_zone(monkeypatch):
    now = datetime(2026, 8, 17, 10, 0)
    expected = local_days.schedule_review(3, NEW_YORK, now=now)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        assert local_days.schedule_review(3, NEW_YORK, now=now) == expected
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


class TestEffectiveReminderHour:
    def test_own_choice_wins(self):
        assert effective_reminder_hour(7, 3, BERLIN) == 7

    def test_midnight_is_a_real_choice(self):
        assert effective_reminder_hour(0, None, BERLIN) == 0

    def test_legacy_utc_hour_is_converted_to_local(self):
        hour = effective_reminder_hour(None, 16, BERLIN)
        assert hour in (17, 18)  # CET or CEST, depending on when the test runs

    def test_legacy_any_time_falls_back_to_default(self):
        from app.config import DEFAULT_REMINDER_HOUR
        assert effective_reminder_hour(None, -1, BERLIN) == DEFAULT_REMINDER_HOUR
        assert effective_reminder_hour(None, None, BERLIN) == DEFAULT_REMINDER_HOUR

    def test_out_of_range_values_are_ignored(self):
        from app.config import DEFAULT_REMINDER_HOUR
        assert effective_reminder_hour(99, None, BERLIN) == DEFAULT_REMINDER_HOUR
        assert effective_reminder_hour("junk", 5, timezone.utc) == 5


def test_day_progress():
    assert local_days.day_progress(BERLIN, now=datetime(2026, 8, 17, 22, 0)) == 0.0   # 00:00 Berlin
    assert local_days.day_progress(BERLIN, now=datetime(2026, 8, 18, 10, 0)) == 0.5   # 12:00 Berlin
    # 25-hour day when summer time ends: 12:30 local is 13.5 of 25 hours in.
    assert abs(local_days.day_progress(BERLIN, now=datetime(2026, 10, 25, 11, 30)) - 13.5 / 25) < 1e-9
