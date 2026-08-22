"""
Tells you when someone signs up.

Deliberately a poller, not a hook in the signup path. A notifier is a nice-to-have and
account creation is the most important thing the app does; wiring one into the other means
a bug in the pleasant part can cost a real user their account. Nothing here can affect
whether a signup succeeds, because none of it runs while one is happening.

It is not a separate process or a cron job either. It rides the scheduler loop that already
runs (telegram_bot.run_scheduler_daemon), so the cost is one indexed query every few
minutes and no new moving parts to keep alive.

The watermark lives in app_settings, so a restart resumes where it left off rather than
re-announcing everyone or missing the gap.

The alert goes to one chat id from .env, never to a user account. Signup data is about
other people, so its destination is a property of the deployment rather than of a
user_profile row that could be edited, mistyped, or handed to someone else.
"""
import logging
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from app import database

logger = logging.getLogger("studiamo")

# How far apart the checks are. Signup is not an emergency; this is the difference between
# knowing within five minutes and hammering the database for no reason.
CHECK_INTERVAL_SECONDS = 300

_WATERMARK_SETTING = "signup_notify_watermark"
_last_checked_monotonic = None


def _pretty_source(url: str) -> str:
    """A raw HTTP referrer as something worth putting in a message, or '' for nothing worth
    saying.

    Returns empty for our own site and for the Google sign-in flow. Neither is where anyone
    came *from*: studiamo.cloud/login is the page before the form, and accounts.google.com
    is a step inside signing up. Reporting either as a traffic source would be noise
    dressed up as information, and would drown the handful of lines that mean something.
    """
    if not url:
        return ""
    raw = url.strip().lower()

    # The Reddit app reports android-app://com.reddit.frontpage/, which has no hostname.
    if raw.startswith("android-app://"):
        host = raw.split("://", 1)[1].strip("/")
    else:
        host = raw.split("://", 1)[-1].split("/", 1)[0]
    host = host.replace("www.", "").replace("old.", "").replace("m.", "")

    if "studiamo" in host or "accounts.google" in host:
        return ""
    if "reddit" in host:
        return "Reddit"
    if any(s in host for s in ("google.", "bing.", "duckduckgo")):
        return "Search"
    if host in ("t.co", "x.com") or "twitter" in host:
        return "X"
    if "youtube" in host or "youtu.be" in host:
        return "YouTube"
    for name in ("instagram", "facebook", "linkedin", "tiktok"):
        if name in host:
            return name.capitalize()
    return host or ""


def _format(row) -> str:
    """One signup as a message. Kept to three short lines: who, where from, and what
    state they landed in, which is what decides whether you need to do anything."""
    bits = [f"New signup: {row['username']}"]

    source = _pretty_source(row.get("source_referrer") or "")
    where = " · ".join(x for x in (source, row.get("source_country") or "") if x)
    if where:
        bits.append(where)

    if row["status"] == "waitlist":
        bits.append(f"On the waitlist (#{row['waitlist_place']})")
    else:
        bits.append("Active, can sign in now")
    return "\n".join(bits)


def _fetch_new_signups(cursor, since):
    cursor.execute(
        """
        SELECT p.username, p.status, p.created_at,
               lead.referrer AS source_referrer, lead.country AS source_country,
               q.place AS waitlist_place
          FROM user_profile p
          LEFT JOIN LATERAL (
               SELECT l.referrer, l.country FROM landing_waitlist l
                WHERE LOWER(l.email) IN (LOWER(p.google_email), LOWER(p.email))
                ORDER BY (LOWER(l.email) = LOWER(p.google_email)) DESC, l.created_at DESC
                LIMIT 1
          ) lead ON TRUE
          LEFT JOIN (
               SELECT user_uuid,
                      ROW_NUMBER() OVER (ORDER BY referral_count DESC, created_at ASC) AS place
                 FROM user_profile WHERE status = 'waitlist'
          ) q ON q.user_uuid = p.user_uuid
         WHERE p.created_at > %s
         ORDER BY p.created_at
         LIMIT 20;
        """,
        (since,),
    )
    return cursor.fetchall()


def check_and_notify_new_signups() -> int:
    """Announces accounts created since the last run. Returns how many were announced.

    Silent and harmless when unconfigured: no ADMIN_TELEGRAM_CHAT_ID means it does nothing
    at all, not even a query, so this costs nothing on a deployment that has not asked for
    it. Staging and production are configured independently, because each has its own .env.

    The watermark advances even when the send fails. A notifier that retries forever would
    turn one broken evening into a backlog that arrives all at once, and the signup itself
    is recorded in the database either way."""
    global _last_checked_monotonic
    import time

    now_monotonic = time.monotonic()
    if _last_checked_monotonic is not None and \
            (now_monotonic - _last_checked_monotonic) < CHECK_INTERVAL_SECONDS:
        return 0
    _last_checked_monotonic = now_monotonic

    # Configured by ADMIN_TELEGRAM_CHAT_ID in .env, and by nothing else. Checked before any
    # query so an unconfigured deployment does no work at all.
    from app import config
    if not config.ADMIN_TELEGRAM_CHAT_ID:
        return 0

    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        watermark = database.get_app_setting(_WATERMARK_SETTING, "").strip()
        if not watermark:
            # First run: start from now rather than announcing every account ever created.
            database.set_app_setting(_WATERMARK_SETTING, datetime.now(timezone.utc).isoformat())
            return 0

        rows = _fetch_new_signups(cursor, watermark)
        if not rows:
            return 0

        from app.telegram_bot import send_admin_telegram
        sent = 0
        for row in rows:
            try:
                if send_admin_telegram(_format(row)):
                    sent += 1
            except Exception as e:
                logger.warning(f"[signup_notify] Could not announce {row['username']}: {e}")

        database.set_app_setting(_WATERMARK_SETTING, rows[-1]["created_at"].isoformat())
        logger.info(f"[signup_notify] Announced {sent}/{len(rows)} new signup(s).")
        return sent
    except Exception as e:
        # Never let this take the scheduler loop down with it.
        logger.warning(f"[signup_notify] Check failed: {e}")
        return 0
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)
