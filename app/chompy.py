"""
Chompy: the forgetting monster who eats reviews that are left undone for too long.

A review due on local day D can be done on D, D+1 or D+2. If it is still undone when D+2 ends
(local midnight), Chompy eats it: the video is paused with videos.eaten_at set, which keeps its
SRS stage and schedule but takes it out of every "due" list until the user wins it back with a
quiz. Nothing is deleted.

The clock for reviews that were already overdue when Chompy arrived starts at that moment
instead of at their old due date, so the first night does not eat a whole backlog at once. That
moment is stored once per database in app_settings (CLOCK_START_KEY).
"""
import logging
from datetime import date, timedelta

from app import database, local_days

logger = logging.getLogger("studiamo")

# Local days a due review may stay undone: the due day itself plus two more.
GRACE_DAYS = 3
CLOCK_START_KEY = "chompy_clock_started_at"


def eat_day(next_review_at, tz, clock_start=None) -> date | None:
    """The local date at whose end Chompy eats this review if it is still undone."""
    due = local_days.local_date(next_review_at, tz)
    if due is None:
        return None
    start = local_days.local_date(clock_start, tz) if clock_start else None
    if start and start > due:
        due = start
    return due + timedelta(days=GRACE_DAYS - 1)


def days_until_eaten(next_review_at, tz, clock_start=None, now=None) -> int | None:
    """0 means tonight, 1 tomorrow night. Negative means the eating is overdue."""
    day = eat_day(next_review_at, tz, clock_start)
    if day is None:
        return None
    return (day - local_days.local_today(tz, now)).days


def eaten_tonight(next_review_at, tz, clock_start=None, now=None) -> bool:
    """True when this due review gets eaten at the coming local midnight."""
    return days_until_eaten(next_review_at, tz, clock_start, now) == 0


def should_be_eaten(next_review_at, tz, clock_start=None, now=None) -> bool:
    """True once the review's last grace day has ended in the user's time zone."""
    days = days_until_eaten(next_review_at, tz, clock_start, now)
    return days is not None and days < 0


_clock_start_cache = None


def get_clock_start(create: bool = True):
    """Returns the naive-UTC moment Chompy started eating on this database.

    Written once, by the scheduler's first run (create=True), so every environment gets its own
    start. Read paths pass create=False and never write. Returns None when there is no start
    yet or the setting cannot be read: with no known start, nothing is eaten and no warning is
    sent, which is the safe direction.
    """
    global _clock_start_cache
    if _clock_start_cache is not None:
        return _clock_start_cache
    try:
        stored = database.get_app_setting(CLOCK_START_KEY, "")
        if not stored:
            if not create:
                return None
            stored = local_days.utc_now().isoformat()
            database.set_app_setting(CLOCK_START_KEY, stored)
        _clock_start_cache = local_days.as_naive_utc(stored)
    except Exception as e:
        logger.warning(f"Chompy clock start unavailable: {e}")
        return None
    return _clock_start_cache


# Same "active review" filter as the dashboard and the reminders: only reviews the user can
# currently see as due are ever eaten.
_DUE_CANDIDATES_SQL = """
    SELECT q.video_id, q.next_review_at
    FROM quizzes q
    JOIN videos v ON q.video_id = v.id AND q.user_uuid = v.user_uuid
    WHERE q.user_uuid = %s
      AND q.quiz_type = 'video'
      AND v.is_paused = 0 AND v.is_archived = 0 AND v.is_watchlist = 0
      AND COALESCE(v.is_temporary, 0) = 0
      AND q.importance_level = v.importance_rating;
"""


def eat_for_user(username, clock_start, now=None) -> int:
    """Pauses every review of this user whose last grace day has ended. Returns how many."""
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT timezone FROM user_profile WHERE user_uuid = %s LIMIT 1;", (conn.user_uuid,))
        row = cursor.fetchone()
        tz = local_days.resolve_timezone(row.get("timezone") if row else None)
        cursor.execute(_DUE_CANDIDATES_SQL, (conn.user_uuid,))
        video_ids = sorted({
            r["video_id"] for r in cursor.fetchall()
            if should_be_eaten(r.get("next_review_at"), tz, clock_start, now)
        })
        if not video_ids:
            return 0
        cursor.execute(
            """UPDATE videos SET is_paused = 1, eaten_at = NOW()
               WHERE user_uuid = %s AND id = ANY(%s) AND is_paused = 0;""",
            (conn.user_uuid, video_ids),
        )
        eaten = cursor.rowcount
        conn.commit()
        return eaten
    finally:
        conn.close()


def run_eating(now=None) -> int:
    """One pass over every user. Idempotent, so the scheduler can run it as often as it likes;
    eating is only ever due right after a local midnight."""
    clock_start = get_clock_start()
    if clock_start is None:
        return 0
    total = 0
    for username in database.get_all_users():
        try:
            total += eat_for_user(username, clock_start, now)
        except Exception as e:
            logger.error(f"Chompy eating failed for {username}: {e}")
    return total
