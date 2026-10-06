"""Coarse account activity: when an account last changed something, and on which days.

An "action" is any signed-in request that is not a read (POST, PUT, PATCH, DELETE), so opening
the app or loading a tab does not count, but answering a quiz, importing, moving a goal or
saving a setting does. Two things are stored, both keyed by the account's user_uuid:

- user_profile.last_active_at / last_action: the latest action and its route template (for
  example "POST /api/goals/{id}"), never request contents or ids.
- user_activity_days: one row per UTC day with at least one action.

Writes are throttled in memory so a busy session costs one UPDATE every few minutes, not one
per request, and a failed write never breaks the request that triggered it. The throttle is
per process, so after a restart the first action of each account writes again, which is
harmless because both writes are idempotent.
"""
import logging
import time
from datetime import datetime, timezone

from fastapi import Request

from app import database

logger = logging.getLogger("studiamo")

# Minimum gap between two last_active_at writes for the same account.
WRITE_INTERVAL_SECONDS = 300
# Daily rows are kept this long; the notification scheduler prunes older ones.
ACTIVITY_RETENTION_DAYS = 400

_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_last_write: dict[str, float] = {}


def note_activity(request: Request, username: str) -> None:
    """Records that `username` just performed a write request. Never raises."""
    if request.method in _READ_METHODS:
        return
    now = time.monotonic()
    last = _last_write.get(username)
    if last is not None and now - last < WRITE_INTERVAL_SECONDS:
        return
    _last_write[username] = now

    route = request.scope.get("route")
    path = getattr(route, "path", None) or "unknown"
    action = f"{request.method} {path}"[:120]
    today = datetime.now(timezone.utc).date()

    conn = None
    try:
        conn = database.get_db_connection(username)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET last_active_at = NOW(), last_action = %s WHERE user_uuid = %s;",
            (action, conn.user_uuid),
        )
        cursor.execute(
            "INSERT INTO user_activity_days (user_uuid, day) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (conn.user_uuid, today),
        )
        conn.commit()
    except Exception as e:
        # Let the next action retry instead of waiting out the interval.
        _last_write.pop(username, None)
        logger.warning(f"Recording activity failed for {username}: {e}")
    finally:
        if conn is not None:
            conn.close()


def prune_activity_days() -> None:
    """Deletes daily rows past the retention window. Called from the notification scheduler."""
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_activity_days WHERE day < CURRENT_DATE - %s;",
            (ACTIVITY_RETENTION_DAYS,),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Pruning user_activity_days failed: {e}")
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)
