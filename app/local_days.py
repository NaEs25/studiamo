"""
Calendar-day rules in the user's own time zone.

Reviews are due on a day, not at an hour: a quiz scheduled for Tuesday is due from the user's
local midnight starting Tuesday, and the hour stored in next_review_at carries no meaning of its
own. New reviews are stored as that local midnight, so a plain timestamp comparison already
agrees with the day rule for them. Rows written before this module existed hold arbitrary
hours, which is why "is it due" compares local dates instead of timestamps.

Timestamps in the database are naive UTC (see as_naive_utc). A user whose time zone is unknown
or invalid is treated as UTC, the behavior every account had before time zones were stored.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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


def resolve_timezone(name):
    """Returns the tzinfo for an IANA name such as 'Europe/Berlin', or UTC if it is unusable."""
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return timezone.utc


def is_valid_timezone(name) -> bool:
    """True for a resolvable IANA name. Used to reject junk before it is stored."""
    if not name or not isinstance(name, str) or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def local_date(value, tz) -> date | None:
    """Returns the calendar date a stored timestamp falls on in the given time zone."""
    dt = as_naive_utc(value)
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(tz or timezone.utc).date()


def local_today(tz, now=None) -> date:
    """Returns today's date in the given time zone. `now` is naive UTC, for tests."""
    return local_date(now or utc_now(), tz)


def local_midnight_utc(day: date, tz) -> datetime:
    """Returns the naive-UTC instant at which `day` begins in the given time zone."""
    start = datetime.combine(day, time.min, tzinfo=tz or timezone.utc)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def schedule_review(days, tz, now=None) -> datetime:
    """Returns the naive-UTC next_review_at for a review `days` from now.

    The result is local midnight of the day the interval lands on, so the review is due for
    that whole local day. Never earlier than tomorrow: short intervals (a 1-day stage times
    a multiplier below 1) could otherwise land on today and hand back the quiz the user just
    finished.
    """
    now = now or utc_now()
    today = local_today(tz, now)
    target = local_date(now + timedelta(days=float(days)), tz)
    target = max(target, today + timedelta(days=1))
    return local_midnight_utc(target, tz)


def days_until_due(next_review_at, tz, now=None) -> int | None:
    """Whole local days from today to the review's due day: 0 is today, negative is overdue."""
    due = local_date(next_review_at, tz)
    if due is None:
        return None
    return (due - local_today(tz, now)).days


def is_due(next_review_at, tz, now=None) -> bool:
    """True when the review's due day is today or earlier in the user's time zone."""
    days = days_until_due(next_review_at, tz, now)
    return days is not None and days <= 0


def day_progress(tz, now=None) -> float:
    """Fraction of the user's current local day that has passed, 0.0 at midnight. Uses the
    day's real length, so it still ends at 1.0 on the 23- and 25-hour days of a DST change."""
    now = now or utc_now()
    today = local_today(tz, now)
    start = local_midnight_utc(today, tz)
    end = local_midnight_utc(today + timedelta(days=1), tz)
    return max(0.0, min(1.0, (now - start).total_seconds() / (end - start).total_seconds()))
