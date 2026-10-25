"""
Per-day activity for the Stats tab: a last-seven-days chart and a month calendar.

Days are the user's own calendar days (see local_days), the same rule the streak uses, so a
quiz answered at 00:30 local time lands on the new day and the calendar agrees with the streak
counter. A day is "active" when at least one question was graded on it.

The functions here are pure: the route does the queries and hands in plain rows.
"""
from collections import defaultdict
from datetime import date, timedelta

from app import local_days

WEEK_DAYS = 7


def bucket_by_local_day(attempts, xp_events, tz) -> dict:
    """Returns {date: {"quizzes": int, "xp": int}} for every local day with activity.

    `attempts` is an iterable of (quiz_id, created_at): quizzes counts distinct quizzes graded
    that day, not questions. `xp_events` is an iterable of (xp, created_at). xp comes from
    xp_events rather than quiz_attempts because those rows outlive the attempts they came from.
    """
    quiz_ids = defaultdict(set)
    xp_totals = defaultdict(int)
    for quiz_id, created_at in attempts:
        day = local_days.local_date(created_at, tz)
        if day is not None:
            quiz_ids[day].add(quiz_id)
    for xp, created_at in xp_events:
        day = local_days.local_date(created_at, tz)
        if day is not None:
            xp_totals[day] += int(xp or 0)
    days = {}
    for day in set(quiz_ids) | set(xp_totals):
        days[day] = {"quizzes": len(quiz_ids.get(day, ())), "xp": xp_totals.get(day, 0)}
    return days


def last_days(days: dict, today: date, count: int = WEEK_DAYS) -> list:
    """Returns the `count` days ending today, oldest first, zero-filled."""
    out = []
    for offset in range(count - 1, -1, -1):
        day = today - timedelta(days=offset)
        entry = days.get(day, {})
        out.append({"date": day.isoformat(), "quizzes": entry.get("quizzes", 0), "xp": entry.get("xp", 0)})
    return out


def parse_month(value, today: date) -> date:
    """Returns the first day of the requested 'YYYY-MM' month, or of today's month if the value
    is missing or malformed. Months after today's are clamped to today's: nothing is there."""
    this_month = today.replace(day=1)
    try:
        year, month = str(value).split("-")
        first = date(int(year), int(month), 1)
    except (TypeError, ValueError):
        return this_month
    return min(first, this_month)


def month_bounds(first: date) -> tuple:
    """Returns (first day, first day of the next month) for the month starting at `first`."""
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return first, nxt


def month_days(days: dict, first: date) -> list:
    """Returns the active days inside the month starting at `first`, oldest first."""
    start, end = month_bounds(first)
    return [
        {"date": day.isoformat(), "quizzes": entry["quizzes"], "xp": entry["xp"]}
        for day, entry in sorted(days.items())
        if start <= day < end
    ]
