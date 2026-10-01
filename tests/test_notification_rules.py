"""
The reminder rules in app/notifications.decide and Chompy's eating clock. Pure functions, no
database: the scheduler feeds decide() a UserState and sends whatever it returns.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import chompy
from app.notifications import Decision, UserState, decide, pick_template, SAVE_HOUR

BERLIN = ZoneInfo("Europe/Berlin")


def state(**kw):
    base = dict(local_hour=18, reminder_hour=18)
    base.update(kw)
    return UserState(**base)


class TestDailySlot:
    def test_sends_when_quizzes_are_due(self):
        assert decide(state(due_count=3)) == Decision("daily", "default")

    def test_nothing_due_means_no_message(self):
        assert decide(state(due_count=0)) is None

    def test_only_in_the_reminder_hour(self):
        assert decide(state(local_hour=17, due_count=3)) is None

    def test_once_per_day(self):
        assert decide(state(due_count=3, sent_kinds_today=frozenset({"daily"}))) is None

    def test_category_toggle(self):
        assert decide(state(due_count=3, cat_quizzes=False)) is None


class TestEveningSlot:
    def test_streak_only(self):
        s = state(local_hour=SAVE_HOUR, streak=5, streak_at_risk=True)
        assert decide(s) == Decision("save", "streak")

    def test_chompy_only_targets_the_quizzes(self):
        s = state(local_hour=SAVE_HOUR, at_risk=[(7, "A"), (9, "B")])
        assert decide(s) == Decision("save", "chompy", (7, 9))

    def test_both(self):
        s = state(local_hour=SAVE_HOUR, at_risk=[(7, "A")], streak=5, streak_at_risk=True)
        assert decide(s).case == "both"

    def test_nothing_at_stake_means_no_message(self):
        assert decide(state(local_hour=SAVE_HOUR, due_count=4)) is None

    def test_sent_after_the_daily_reminder(self):
        s = state(local_hour=SAVE_HOUR, streak_at_risk=True, streak=2, sent_kinds_today=frozenset({"daily"}))
        assert decide(s).kind == "save"

    def test_once_per_day(self):
        s = state(local_hour=SAVE_HOUR, streak_at_risk=True, streak=2, sent_kinds_today=frozenset({"save"}))
        assert decide(s) is None

    def test_toggle_covers_streak_and_chompy(self):
        s = state(local_hour=SAVE_HOUR, at_risk=[(1, "A")], streak_at_risk=True, cat_streak=False)
        assert decide(s) is None


class TestLateReminderHour:
    def test_late_daily_slot_carries_the_warning(self):
        s = state(local_hour=21, reminder_hour=21, due_count=2, at_risk=[(3, "A")])
        assert decide(s) == Decision("save", "chompy", (3,))

    def test_late_daily_slot_without_stake_is_a_normal_reminder(self):
        s = state(local_hour=20, reminder_hour=20, due_count=2)
        assert decide(s) == Decision("daily", "default")

    def test_no_separate_evening_message(self):
        # Reminder at 22:00 and the daily slot already went out: 21:00 stays quiet.
        s = state(local_hour=SAVE_HOUR, reminder_hour=22, streak_at_risk=True, streak=3)
        assert decide(s) is None


class TestWelcomeBack:
    def test_on_the_listed_days(self):
        for days in (3, 7, 14, 30):
            assert decide(state(days_since_last_quiz=days)) == Decision("welcome_back", "plain")

    def test_mentions_what_chompy_ate(self):
        assert decide(state(days_since_last_quiz=3, eaten_while_away=2)).case == "eaten"

    def test_silent_between_and_after(self):
        for days in (4, 10, 31, 60):
            assert decide(state(days_since_last_quiz=days)) is None

    def test_replaces_the_daily_reminder(self):
        assert decide(state(days_since_last_quiz=7, due_count=5)).kind == "welcome_back"

    def test_toggle(self):
        assert decide(state(days_since_last_quiz=3, cat_inactivity=False, due_count=1)).kind == "daily"


def test_never_more_than_two_a_day():
    s = state(local_hour=SAVE_HOUR, streak_at_risk=True, streak=3,
              sent_kinds_today=frozenset({"daily", "welcome_back"}))
    assert decide(s) is None


class TestPickTemplate:
    def test_unseen_variants_first(self):
        t = pick_template("daily", "default", {"daily_01": datetime(2026, 9, 1)})
        assert t.id != "daily_01"

    def test_least_recently_sent_once_all_are_seen(self):
        from app.notification_templates import active_templates
        ids = [t.id for t in active_templates("daily", "default")]
        last_sent = {tid: datetime(2026, 9, 10) for tid in ids}
        last_sent[ids[3]] = datetime(2026, 9, 1)
        assert pick_template("daily", "default", last_sent).id == ids[3]


class TestChompyClock:
    START = datetime(2026, 9, 1, 8, 0)  # Tuesday morning UTC, Chompy arrives

    def test_three_local_days_then_eaten(self):
        due = datetime(2026, 9, 6, 22, 0)  # Monday 7 Sept 00:00 Berlin
        assert chompy.eat_day(due, BERLIN, self.START) == date(2026, 9, 9)
        assert not chompy.should_be_eaten(due, BERLIN, self.START, now=datetime(2026, 9, 9, 21, 59))
        assert chompy.eaten_tonight(due, BERLIN, self.START, now=datetime(2026, 9, 9, 12, 0))
        assert chompy.should_be_eaten(due, BERLIN, self.START, now=datetime(2026, 9, 9, 22, 0))

    def test_old_backlog_gets_a_fresh_clock_at_rollout(self):
        long_overdue = datetime(2026, 8, 1, 10, 0)
        assert chompy.eat_day(long_overdue, BERLIN, self.START) == date(2026, 9, 3)
        assert not chompy.should_be_eaten(long_overdue, BERLIN, self.START, now=datetime(2026, 9, 2, 12, 0))

    def test_not_yet_due_is_never_at_risk(self):
        future = datetime(2026, 9, 20, 22, 0)
        assert not chompy.eaten_tonight(future, BERLIN, self.START, now=datetime(2026, 9, 10, 12, 0))
        assert not chompy.should_be_eaten(future, BERLIN, self.START, now=datetime(2026, 9, 10, 12, 0))
