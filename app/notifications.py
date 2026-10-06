"""
Review reminders: at most two a day per user, each about something that is still open.

  1. Daily reminder, at the user's reminder hour (local time): the quizzes due today that are
     not finished yet.
  2. Evening warning, at SAVE_HOUR: only when something is at stake tonight, i.e. a quiz Chompy
     eats at midnight (app/chompy.py) and/or a streak that ends at midnight. Users whose
     reminder hour is LATE_REMINDER_HOUR or later get no separate evening message; their daily
     reminder carries the warning instead, so two messages never land close together.

After WELCOME_BACK_DAYS days without a quiz, the daily slot sends a welcome-back message
instead, and after the last of those days it stays silent.

decide() is pure and holds every rule above. The rest gathers its inputs, delivers the chosen
text on every enabled channel, and records the send in notification_log, which is also what
makes each slot fire once per local day however often the scheduler ticks.
"""
import asyncio
import html
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import timezone

from app import activity, chompy, database, gamification, local_days
from app import notification_templates as templates
from app.dependencies import effective_reminder_hour

logger = logging.getLogger("studiamo")

SAVE_HOUR = 21
LATE_REMINDER_HOUR = 20
MAX_PER_DAY = 2
WELCOME_BACK_DAYS = (3, 7, 14, 30)
CONVERSION_WINDOW_HOURS = 3
LOG_RETENTION_DAYS = 30
_PRUNE_INTERVAL_SECONDS = 3600


@dataclass
class UserState:
    local_hour: int
    reminder_hour: int
    cat_quizzes: bool = True
    cat_streak: bool = True
    cat_inactivity: bool = True
    due_count: int = 0
    at_risk: list = field(default_factory=list)   # [(quiz_id, title)] Chompy eats tonight
    streak: int = 0
    streak_at_risk: bool = False
    days_since_last_quiz: int | None = None
    eaten_while_away: int = 0
    sent_kinds_today: frozenset = frozenset()


@dataclass(frozen=True)
class Decision:
    kind: str
    case: str
    target_quiz_ids: tuple = ()


def _save_decision(state: UserState):
    if not state.cat_streak:
        return None
    chompy_at_stake = bool(state.at_risk)
    if chompy_at_stake and state.streak_at_risk:
        case = "both"
    elif chompy_at_stake:
        case = "chompy"
    elif state.streak_at_risk:
        case = "streak"
    else:
        return None
    return Decision("save", case, tuple(qid for qid, _ in state.at_risk))


def decide(state: UserState):
    """Returns what to send to this user right now, or None."""
    if len(state.sent_kinds_today) >= MAX_PER_DAY:
        return None
    sent = state.sent_kinds_today

    if state.local_hour == state.reminder_hour and not sent & {"daily", "welcome_back", "save"}:
        if state.cat_inactivity and state.days_since_last_quiz in WELCOME_BACK_DAYS:
            return Decision("welcome_back", "eaten" if state.eaten_while_away else "plain")
        if state.reminder_hour >= LATE_REMINDER_HOUR:
            warning = _save_decision(state)
            if warning:
                return warning
        if state.cat_quizzes and state.due_count > 0:
            return Decision("daily", "default")
        return None

    if (state.reminder_hour < LATE_REMINDER_HOUR and state.local_hour == SAVE_HOUR
            and "save" not in sent):
        return _save_decision(state)
    return None


def pick_template(kind: str, case: str, last_sent: dict):
    """Least recently sent variant for this user; unseen variants first, in random order so
    their stats fill evenly. `last_sent` maps template_id to its latest sent_at."""
    candidates = templates.active_templates(kind, case)
    if not candidates:
        return None
    unseen = [t for t in candidates if t.id not in last_sent]
    if unseen:
        return random.choice(unseen)
    return min(candidates, key=lambda t: last_sent[t.id])


# ---------------------------------------------------------------------------------------------
# Gathering state
# ---------------------------------------------------------------------------------------------

_PROFILE_SQL = """
    SELECT user_uuid, notifications_enabled, notify_telegram, notify_push, notify_email,
           notify_cat_quizzes, notify_cat_streak, notify_cat_inactivity,
           preferred_hour, reminder_hour, timezone, base_url, google_email,
           streak, last_quiz_at
    FROM user_profile WHERE user_uuid = %s LIMIT 1;
"""

# Same "active review" filter the dashboard applies: paused (which includes eaten), archived
# and watchlist videos are out, as are quiz rows left over from an earlier importance level.
_ACTIVE_QUIZZES_SQL = """
    SELECT q.id, q.next_review_at, v.title
    FROM quizzes q
    JOIN videos v ON q.video_id = v.id AND q.user_uuid = v.user_uuid
    WHERE q.user_uuid = %s
      AND q.quiz_type = 'video'
      AND v.is_paused = 0 AND v.is_archived = 0 AND v.is_watchlist = 0
      AND q.importance_level = v.importance_rating;
"""


def _has_channel(profile) -> bool:
    return bool(profile.get("notify_telegram") or profile.get("notify_push")
                or (profile.get("notify_email") and profile.get("google_email")))


def _build_state(cursor, profile, tz, now, clock_start):
    user_uuid = str(profile["user_uuid"])
    local_now = now.replace(tzinfo=timezone.utc).astimezone(tz)
    reminder_hour = effective_reminder_hour(profile.get("reminder_hour"), profile.get("preferred_hour"), tz)
    state = UserState(
        local_hour=local_now.hour,
        reminder_hour=reminder_hour,
        cat_quizzes=bool(profile.get("notify_cat_quizzes", True)),
        cat_streak=bool(profile.get("notify_cat_streak", True)),
        cat_inactivity=bool(profile.get("notify_cat_inactivity", True)),
    )
    if state.local_hour not in (reminder_hour, SAVE_HOUR):
        return state, []

    cursor.execute(_ACTIVE_QUIZZES_SQL, (user_uuid,))
    quizzes = [dict(r) for r in cursor.fetchall()]
    due = [q for q in quizzes if local_days.is_due(q.get("next_review_at"), tz, now)]
    state.due_count = len(due)
    if clock_start:
        state.at_risk = [(q["id"], q.get("title") or "a quiz") for q in due
                         if chompy.eaten_tonight(q.get("next_review_at"), tz, clock_start, now)]

    last_quiz_at = profile.get("last_quiz_at")
    state.streak = gamification.effective_streak(profile.get("streak"), last_quiz_at, now=now, tz=tz)
    last_day = local_days.local_date(last_quiz_at, tz)
    today = local_days.local_today(tz, now)
    if last_day is not None:
        state.days_since_last_quiz = (today - last_day).days
        # Alive but not yet extended today: it ends at the coming midnight.
        state.streak_at_risk = state.streak > 0 and state.days_since_last_quiz == 1
        if state.days_since_last_quiz in WELCOME_BACK_DAYS:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE user_uuid = %s AND eaten_at IS NOT NULL AND eaten_at > %s;",
                (user_uuid, last_quiz_at),
            )
            state.eaten_while_away = int(cursor.fetchone()["n"])

    cursor.execute(
        "SELECT DISTINCT kind FROM notification_log WHERE user_uuid = %s AND local_day = %s;",
        (user_uuid, today),
    )
    state.sent_kinds_today = frozenset(r["kind"] for r in cursor.fetchall())
    return state, due


# ---------------------------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------------------------

async def _deliver(username, profile, title, body, log_id=None) -> list[str]:
    """Sends on every enabled channel and returns the ones that went through."""
    from app.telegram_bot import notification_app_link, send_telegram_message
    from app.webpush_utils import send_user_web_push
    from app.email_utils import send_notification_email

    app_link = notification_app_link(profile.get("base_url"))
    delivered = []

    if profile.get("notify_push"):
        try:
            if await asyncio.to_thread(send_user_web_push, username,
                                       {"title": title, "body": body, "url": "/#review-section", "log_id": log_id}):
                delivered.append("push")
        except Exception as e:
            logger.warning(f"Reminder push failed for {username}: {e}")

    if profile.get("notify_telegram"):
        try:
            # Video titles are user content and Telegram parses this message as HTML.
            text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}\n\n{app_link}"
            if await send_telegram_message(text, username):
                delivered.append("telegram")
        except Exception as e:
            logger.warning(f"Reminder Telegram message failed for {username}: {e}")

    if profile.get("notify_email") and profile.get("google_email"):
        try:
            if await asyncio.to_thread(send_notification_email, profile["google_email"], title, title, body, app_link,
                                       "Open Studiamo", f"{app_link}#notifications"):
                delivered.append("email")
        except Exception as e:
            logger.warning(f"Reminder email failed for {username}: {e}")

    return delivered


def _record_send(cursor, user_uuid, decision, template_id, local_day) -> int:
    cursor.execute(
        """INSERT INTO notification_log (user_uuid, kind, template_id, local_day, target_quiz_ids)
           VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id;""",
        (user_uuid, decision.kind, template_id, local_day,
         json.dumps([int(q) for q in decision.target_quiz_ids])),
    )
    return cursor.fetchone()["id"]


async def _process_user(username, now, clock_start):
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(_PROFILE_SQL, (conn.user_uuid,))
        profile = cursor.fetchone()
        if not profile or not profile.get("notifications_enabled", 1) or not _has_channel(profile):
            return
        profile = dict(profile)
        tz = local_days.resolve_timezone(profile.get("timezone"))
        state, due = _build_state(cursor, profile, tz, now, clock_start)
        decision = decide(state)
        if decision is None:
            return

        user_uuid = str(profile["user_uuid"])
        cursor.execute(
            """SELECT template_id, MAX(sent_at) AS last_sent FROM notification_log
               WHERE user_uuid = %s AND kind = %s GROUP BY template_id;""",
            (user_uuid, decision.kind),
        )
        last_sent = {r["template_id"]: r["last_sent"] for r in cursor.fetchall()}
        template = pick_template(decision.kind, decision.case, last_sent)
        if template is None:
            return

        titles = [t for _, t in state.at_risk]
        title, body = templates.render(template, count=state.due_count, titles=titles,
                                       streak=state.streak, eaten=state.eaten_while_away)

        # Recorded before delivery and committed, so a crash mid-send cannot make the next
        # tick send the same slot again.
        log_id = _record_send(cursor, user_uuid, decision, template.id, local_days.local_today(tz, now))
        conn.commit()

        channels = await _deliver(username, profile, title, body, log_id)
        if channels:
            cursor.execute("UPDATE notification_log SET channels = %s WHERE id = %s;", (",".join(channels), log_id))
            cursor.execute(
                """INSERT INTO notification_template_stats (template_id, sent) VALUES (%s, 1)
                   ON CONFLICT (template_id) DO UPDATE SET sent = notification_template_stats.sent + 1;""",
                (template.id,),
            )
            conn.commit()
    finally:
        conn.close()


_last_prune_at = 0.0


def _prune_log():
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM notification_log WHERE sent_at < NOW() - make_interval(days => %s);",
            (LOG_RETENTION_DAYS,),
        )
        conn.commit()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


async def run_tick(now=None):
    """One scheduler pass over every user. Safe to call every minute."""
    global _last_prune_at
    now = now or local_days.utc_now()
    clock_start = chompy.get_clock_start()
    for username in database.get_all_users():
        try:
            await _process_user(username, now, clock_start)
        except Exception as e:
            logger.error(f"Reminder check failed for {username}: {e}")

    if time.time() - _last_prune_at >= _PRUNE_INTERVAL_SECONDS:
        _last_prune_at = time.time()
        try:
            await asyncio.to_thread(_prune_log)
        except Exception as e:
            logger.warning(f"Pruning notification_log failed: {e}")
        await asyncio.to_thread(activity.prune_activity_days)


# ---------------------------------------------------------------------------------------------
# Clicks (push only)
# ---------------------------------------------------------------------------------------------

def mark_clicked(user_uuid, log_id: int) -> bool:
    """Stamps a push notification as clicked, once, and counts it per template.

    Only the account the reminder was sent to can click it (user_uuid is part of the match),
    so a guessed id changes nothing. Returns whether a row was stamped."""
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE notification_log SET clicked_at = NOW()
               WHERE id = %s AND user_uuid = %s AND clicked_at IS NULL AND channels LIKE '%%push%%'
               RETURNING template_id;""",
            (int(log_id), str(user_uuid)),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE notification_template_stats SET clicked = clicked + 1 WHERE template_id = %s;",
                (row[0],),
            )
        conn.commit()
        return row is not None
    except Exception as e:
        logger.warning(f"Marking notification {log_id} clicked failed: {e}")
        return False
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


# ---------------------------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------------------------

def mark_converted(user_uuid, quiz_id, quiz_finished: bool, tz, now=None):
    """Stamps the reminders this answer converts, and counts them per template.

    A reminder converts when the user studies within CONVERSION_WINDOW_HOURS of it and on the
    same local day. An evening warning about specific quizzes converts only when one of them is
    finished; any other reminder converts on any answer.

    Best-effort and on its own connection: bookkeeping must never fail a grade.
    """
    now = now or local_days.utc_now()
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE notification_log SET converted_at = NOW()
               WHERE user_uuid = %s AND converted_at IS NULL AND channels <> ''
                 AND local_day = %s
                 AND sent_at >= NOW() - make_interval(hours => %s)
                 AND (jsonb_array_length(target_quiz_ids) = 0
                      OR (%s AND target_quiz_ids @> to_jsonb(ARRAY[%s::int])))
               RETURNING template_id;""",
            (str(user_uuid), local_days.local_today(tz, now), CONVERSION_WINDOW_HOURS,
             bool(quiz_finished), int(quiz_id)),
        )
        for (template_id,) in cursor.fetchall():
            cursor.execute(
                "UPDATE notification_template_stats SET converted = converted + 1 WHERE template_id = %s;",
                (template_id,),
            )
        conn.commit()
    except Exception as e:
        logger.warning(f"Marking reminder conversion failed for quiz {quiz_id}: {e}")
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)
