"""
Covers the streak rules that three modules used to implement differently.

The regression these lock down: the dashboard expired a streak after 24 rolling hours and
wrote the zero back, while grading allowed 48 hours, so a daily user whose quiz landed even a
minute later in the day than the previous one lost everything. Production bore this out, an
account with 21 active days was sitting at streak 0.
"""
import unittest
from datetime import datetime, timedelta, timezone

from app.gamification import (
    advance_streak,
    effective_streak,
    hours_until_streak_lapses,
    level_for_xp,
    streak_deadline,
)

MON_09 = datetime(2026, 8, 17, 9, 0)
MON_23 = datetime(2026, 8, 17, 23, 0)
TUE_09 = datetime(2026, 8, 18, 9, 0)
TUE_10 = datetime(2026, 8, 18, 10, 0)
WED_08 = datetime(2026, 8, 19, 8, 0)
THU_09 = datetime(2026, 8, 20, 9, 0)


class TestAdvanceStreak(unittest.TestCase):
    def test_first_ever_quiz_starts_at_one(self):
        self.assertEqual(advance_streak(0, None, now=MON_09), 1)

    def test_consecutive_days_increment(self):
        self.assertEqual(advance_streak(3, MON_09, now=TUE_09), 4)

    def test_later_in_the_day_still_counts(self):
        """The 24 hour rolling deadline broke exactly here: 25 hours apart, but consecutive days."""
        self.assertEqual(advance_streak(3, MON_09, now=TUE_10), 4)

    def test_almost_two_full_days_apart_still_consecutive(self):
        """Monday 00:01 to Tuesday 23:59 is 47 hours and remains a two day streak."""
        self.assertEqual(advance_streak(1, datetime(2026, 8, 17, 0, 1), now=datetime(2026, 8, 18, 23, 59)), 2)

    def test_second_quiz_same_day_does_not_double_count(self):
        self.assertEqual(advance_streak(4, TUE_09, now=TUE_10), 4)

    def test_same_day_lifts_a_zero_left_by_the_old_reset(self):
        self.assertEqual(advance_streak(0, TUE_09, now=TUE_10), 1)

    def test_skipped_day_restarts_at_one(self):
        self.assertEqual(advance_streak(9, MON_09, now=WED_08), 1)

    def test_future_timestamp_restarts_rather_than_going_negative(self):
        self.assertEqual(advance_streak(5, THU_09, now=MON_09), 1)

    def test_accepts_iso_strings_and_aware_datetimes(self):
        self.assertEqual(advance_streak(2, MON_09.isoformat(), now=TUE_09), 3)
        self.assertEqual(advance_streak(2, MON_09.replace(tzinfo=timezone.utc), now=TUE_09), 3)

    def test_aware_non_utc_is_converted_not_truncated(self):
        """23:00 UTC+2 on Monday is 21:00 UTC Monday, so Tuesday is still the next day."""
        aware = datetime(2026, 8, 17, 23, 0, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(advance_streak(2, aware, now=TUE_09), 3)


class TestEffectiveStreak(unittest.TestCase):
    def test_quiz_today_shows_stored_value(self):
        self.assertEqual(effective_streak(6, TUE_09, now=TUE_10), 6)

    def test_quiz_yesterday_still_alive(self):
        self.assertEqual(effective_streak(6, MON_23, now=TUE_09), 6)

    def test_lapsed_reads_as_zero(self):
        self.assertEqual(effective_streak(6, MON_09, now=WED_08), 0)

    def test_never_quizzed_is_zero(self):
        self.assertEqual(effective_streak(0, None, now=TUE_09), 0)
        self.assertEqual(effective_streak(4, None, now=TUE_09), 0)

    def test_does_not_invent_a_streak_from_a_stored_zero(self):
        self.assertEqual(effective_streak(0, TUE_09, now=TUE_10), 0)

    def test_tolerates_null_and_garbage_stored_values(self):
        self.assertEqual(effective_streak(None, TUE_09, now=TUE_10), 0)
        self.assertEqual(effective_streak("", TUE_09, now=TUE_10), 0)


class TestStreakDeadline(unittest.TestCase):
    def test_deadline_is_end_of_the_day_after_the_last_quiz(self):
        self.assertEqual(streak_deadline(MON_09), datetime(2026, 8, 19, 0, 0))

    def test_no_last_quiz_has_no_deadline(self):
        self.assertIsNone(streak_deadline(None))
        self.assertIsNone(hours_until_streak_lapses(None))

    def test_warning_window_opens_on_the_evening_after(self):
        """The <= 5 hour warning must not fire on the day the user actually quizzed."""
        self.assertGreater(hours_until_streak_lapses(MON_09, now=MON_23), 5)
        self.assertLessEqual(hours_until_streak_lapses(MON_09, now=datetime(2026, 8, 18, 20, 0)), 5)

    def test_lapsed_streak_reports_negative_hours(self):
        self.assertLess(hours_until_streak_lapses(MON_09, now=THU_09), 0)


class TestDeadlineWireFormat(unittest.TestCase):
    """Pins the string /api/dashboard sends as user.streak_deadline.

    app.js stopped deriving the countdown itself (it used last_quiz_at + 24 rolling hours, the
    rule this module replaced, and showed an expiry up to a day early) and now renders whatever
    this field says. Its frontend parser, parseDate() in static/js/core.js, appends a Z only
    when the string carries no zone at all, so a value that is naive-but-not-UTC, or offset in
    any way, is read as a different instant than the server meant, silently shifting the
    countdown. The stored column is naive UTC, hence the explicit Z.
    """

    def _wire_value(self, last_quiz_at):
        """The exact transformation app/routers/dashboard.py applies."""
        deadline = streak_deadline(last_quiz_at)
        return deadline.isoformat() + "Z" if deadline else None

    def test_deadline_is_sent_as_explicit_utc(self):
        self.assertEqual(self._wire_value(MON_09), "2026-08-19T00:00:00Z")

    def test_no_last_quiz_sends_null_rather_than_a_guess(self):
        self.assertIsNone(self._wire_value(None))

    def test_wire_value_round_trips_to_the_same_instant(self):
        """Guards a 'simplification' that drops the Z and shifts the instant by the reader's offset."""
        wire = self._wire_value(MON_09)
        parsed = datetime.fromisoformat(wire.replace("Z", "+00:00"))
        self.assertEqual(parsed, streak_deadline(MON_09).replace(tzinfo=timezone.utc))


class TestLevelForXp(unittest.TestCase):
    def test_known_boundaries(self):
        self.assertEqual(level_for_xp(0), 1)
        self.assertEqual(level_for_xp(49), 1)
        self.assertEqual(level_for_xp(50), 2)
        self.assertEqual(level_for_xp(200), 3)
        self.assertEqual(level_for_xp(1206), 5)

    def test_never_below_one(self):
        self.assertEqual(level_for_xp(None), 1)
        self.assertEqual(level_for_xp(-10), 1)


if __name__ == "__main__":
    unittest.main()
