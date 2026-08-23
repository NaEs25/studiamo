"""
Streak and XP rules, kept in one place because the call sites used to disagree about them.

Grading (routers/quizzes.py) advanced a streak on a 48 hour grace, while the dashboard read
path (routers/dashboard.py) expired it after 24 rolling hours and wrote that zero back to the
database, and the Telegram warning (telegram_bot.py) used the same 24 hour deadline. The
dashboard runs on every app boot, before the user can grade anything, so the reset always won
and no account ever held a streak above 1.

Two rules replace all of that, and both are calendar-day based in UTC:

  * a streak survives while the last quiz was today or yesterday,
  * only grading writes to user_profile.streak. Read paths derive what to show with
    effective_streak() and persist nothing, so a stale stored value can never be displayed
    and a display can never destroy a stored value.
"""
from datetime import datetime, time, timedelta, timezone
from math import floor, sqrt

# XP required for level N is 50 * (N - 1)^2. Inverted here so every call site agrees; this
# used to be an inline floor(sqrt(xp / 50)) + 1 in three separate modules.
XP_PER_LEVEL_UNIT = 50


def utc_now() -> datetime:
    """Returns the current UTC time as a naive datetime, the form stored columns compare against."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_naive_utc(value):
    """Normalizes a timestamp column (datetime, ISO string, or None) to naive UTC.

    Aware values are converted to UTC before the offset is dropped rather than simply having
    tzinfo stripped, which would shift a non-UTC timestamp by its offset and could move it
    across the date boundary these rules turn on.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def level_for_xp(total_xp) -> int:
    """Returns the level a given lifetime XP total earns. Never below 1."""
    try:
        xp = int(total_xp)
    except (TypeError, ValueError):
        return 1
    if xp <= 0:
        return 1
    return floor(sqrt(xp / XP_PER_LEVEL_UNIT)) + 1


def _stored_streak(value) -> int:
    try:
        current = int(value)
    except (TypeError, ValueError):
        return 0
    return current if current > 0 else 0


def advance_streak(stored_streak, last_quiz_at, now=None) -> int:
    """Returns the streak after a quiz is graded at `now`. Only grading may use this."""
    now = now or utc_now()
    last = as_naive_utc(last_quiz_at)
    current = _stored_streak(stored_streak)

    if last is None:
        return 1

    days = (now.date() - last.date()).days
    if days == 0:
        # Already counted today. A stored 0 still becomes 1: the day is being claimed now,
        # and accounts left at 0 by the old dashboard reset must be able to climb out of it.
        return current or 1
    if days == 1:
        return current + 1
    # Two or more days elapsed, or last_quiz_at sits in the future (clock skew). Either way
    # today is the first day of a new streak.
    return 1


def effective_streak(stored_streak, last_quiz_at, now=None) -> int:
    """Returns the streak to display. Pure: never writes, never mutates its arguments.

    A stored streak whose last quiz predates yesterday has lapsed and reads as 0, so read
    paths no longer need to correct the column to show the right number.
    """
    now = now or utc_now()
    last = as_naive_utc(last_quiz_at)
    current = _stored_streak(stored_streak)

    if current == 0 or last is None:
        return 0
    return current if (now.date() - last.date()).days <= 1 else 0


def streak_deadline(last_quiz_at):
    """Returns the instant a streak lapses: midnight UTC ending the day after the last quiz.

    A quiz on day D keeps the streak alive through the end of D+1, so this is the start of
    D+2. Returns None when there is no last quiz to measure from.
    """
    last = as_naive_utc(last_quiz_at)
    if last is None:
        return None
    return datetime.combine(last.date() + timedelta(days=2), time.min)


def hours_until_streak_lapses(last_quiz_at, now=None):
    """Returns hours remaining before the streak lapses, or None if there is no deadline."""
    deadline = streak_deadline(last_quiz_at)
    if deadline is None:
        return None
    now = now or utc_now()
    return (deadline - now).total_seconds() / 3600.0
