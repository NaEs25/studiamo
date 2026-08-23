import asyncio
import httpx
import math
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from app import config, database, gamification
from app.config import USERS_DIR, load_user_config, write_user_config
from app.database import get_db_connection

def notification_app_link(stored_base_url: str = None) -> str:
    """Returns the URL notification messages should link back to. Cloud
    always points at the hosted app regardless of any stored base_url
    (that field is self-hosted-only in Settings , cloud users never set
    it); self-hosted uses its configured local base_url."""
    if config.IS_CLOUD:
        return "https://app.studiamo.cloud"
    return (stored_base_url or "https://studiamo.cloud").rstrip("/") + "/app"


# Shared persistent AsyncClient instance to avoid CPU & SSL handshake churn
_http_client: httpx.AsyncClient | None = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client

async def send_telegram_message(text: str, username: str) -> bool:
    """Sends a message to the Telegram Chat ID configured for a specific user.

    Self-hosted users message through their own bot (TELEGRAM_BOT_TOKEN).
    Cloud users without their own token fall back to the shared managed bot
    , the chat_id (bound via the /start deep link) is still per-user."""
    user_cfg = load_user_config(username)
    token = user_cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = user_cfg.get("TELEGRAM_CHAT_ID")

    if not token and config.IS_CLOUD and config.TELEGRAM_MANAGED_BOT_TOKEN:
        token = config.TELEGRAM_MANAGED_BOT_TOKEN

    if not token or not chat_id:
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        client = get_http_client()
        response = await client.post(url, json=payload)
        if response.status_code == 200:
            return True
        else:
            print(f"Failed to send Telegram message for {username}: {response.text}")
            return False
    except Exception as e:
        print(f"Telegram notification transport error for {username}: {e}")
        return False

def send_admin_telegram(text: str) -> bool:
    """Sends an operator alert to one fixed chat. Returns False if none is configured.

    Consults no user account, by design. send_telegram_message() looks its destination up
    in a user_profile row, which is right for a user's own notifications and wrong for
    operator alerts about other people: it would make the recipient of that data a property
    of an account record rather than of the deployment's configuration.

    Synchronous because the scheduler loop that calls it already is, and because there is
    no reason for an alert to be worth an event loop."""
    chat_id = config.ADMIN_TELEGRAM_CHAT_ID
    token = config.ADMIN_TELEGRAM_BOT_TOKEN or config.TELEGRAM_MANAGED_BOT_TOKEN
    if not chat_id or not token:
        return False

    try:
        import httpx
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return True
        # Logged without the token or the chat id: this line ends up in journalctl.
        print(f"Admin Telegram alert rejected: HTTP {resp.status_code}")
        return False
    except Exception as e:
        print(f"Admin Telegram transport error: {e}")
        return False


def send_telegram_message_sync(text: str, username: str) -> bool:
    """Synchronous wrapper for sending Telegram messages from background worker threads."""
    try:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(send_telegram_message(text, username))).result()
            return loop.run_until_complete(send_telegram_message(text, username))
        except RuntimeError:
            return asyncio.run(send_telegram_message(text, username))
    except Exception as e:
        print(f"Error in send_telegram_message_sync for {username}: {e}")
        return False

# Offsets dictionary for polling updates per user in memory
offsets = {}

async def telegram_long_polling():
    """Runs a low-power long polling loop to check for the /start command from any registered users."""
    print("Telegram multi-user long poller started in background...")
    
    while True:
        has_active_tokens = False
        try:
            client = get_http_client()
            for username in database.get_all_users():
                user_cfg = load_user_config(username)
                token = user_cfg.get("TELEGRAM_BOT_TOKEN")
                if not token:
                    continue
                
                has_active_tokens = True
                offset = offsets.get(username, 0)
                url = f"https://api.telegram.org/bot{token}/getUpdates"
                params = {"offset": offset, "timeout": 2}
                
                try:
                    response = await client.get(url, params=params, timeout=5.0)
                    if response.status_code == 200:
                        data = response.json()
                        for update in data.get("result", []):
                            offsets[username] = update["update_id"] + 1
                            message = update.get("message", {})
                            text = message.get("text", "")
                            chat_id = message.get("chat", {}).get("id")

                            if text.strip() == "/start" and chat_id:
                                write_user_config(username, {"TELEGRAM_CHAT_ID": str(chat_id)})
                                await send_telegram_message(
                                    "🧠 <b>Welcome to Studiamo!</b>\n\n"
                                    f"Hi {username}, your Telegram Chat ID has been registered. "
                                    "You will now receive active recall review reminders directly in this chat.",
                                    username
                                )
                    else:
                        print(f"Telegram getUpdates non-200 for user='{username}': {response.status_code} {response.text[:200]}")
                except Exception as e:
                    # Was a bare `except: pass` , a broken poll for one user was
                    # invisible even though every other user kept working fine.
                    print(f"Telegram getUpdates poll failed for user='{username}': {e}")
        except Exception as e:
            print(f"Telegram long poller global error: {e}")
            
        sleep_duration = 15 if has_active_tokens else 30
        await asyncio.sleep(sleep_duration)


# Telegram allows [A-Za-z0-9_-] and at most 64 characters in a /start payload.
# token_urlsafe(24) spends 32 of them on 192 bits of entropy.
TELEGRAM_LINK_TTL_MINUTES = 15


def generate_telegram_link_payload(username: str) -> str:
    """Issues a single-use /start deep-link payload bound to username.

    Recorded server-side rather than derived from the username, because a payload
    leaves our control the moment it goes into a URL: it reaches Telegram, browser
    history, and wherever the person happens to paste it. A derived payload stays
    valid for as long as the signing key does, so seeing one once was enough to
    replay it later and point that account's notifications at another chat. This
    one expires and stops working after a single /start."""
    token = secrets.token_urlsafe(24)
    database.issue_telegram_link_token(token, username, TELEGRAM_LINK_TTL_MINUTES)
    return token


def resolve_telegram_link_payload(payload: str) -> str | None:
    """Redeems a /start payload and returns the username it was issued to, or None.

    None covers everything that is not a live unredeemed token, including payloads
    minted by the previous derived scheme: those now fail closed, and the caller
    already answers an unresolvable payload by telling the person to press Connect
    Telegram again."""
    if not payload:
        return None
    return database.consume_telegram_link_token(payload) or None


def _managed_poll_backoff(failures: int) -> int:
    """Seconds to wait after `failures` consecutive failed getUpdates calls.

    Doubles to a one minute ceiling, which keeps a permanently bad token to roughly
    one log line a minute instead of thousands, while a transient blip still recovers
    within a couple of seconds."""
    return min(60, 2 ** min(failures, 6))


managed_offset = 0

async def managed_telegram_long_polling():
    """Runs a single long-polling loop against the shared cloud managed bot
    (TELEGRAM_MANAGED_BOT_TOKEN). Separate from telegram_long_polling() above,
    which only polls per-user self-hosted BYO bots , the two never overlap
    since a cloud user has no TELEGRAM_BOT_TOKEN of their own to poll there.
    No-ops immediately if not running in cloud mode or the bot isn't configured."""
    global managed_offset
    if not (config.IS_CLOUD and config.TELEGRAM_MANAGED_BOT_TOKEN):
        return

    print("Telegram managed-bot long poller started in background...")
    client = get_http_client()
    url = f"https://api.telegram.org/bot{config.TELEGRAM_MANAGED_BOT_TOKEN}/getUpdates"

    # Backoff for a getUpdates that keeps failing. Without it the non-200 branch fell
    # straight back into the loop with nothing to wait on: a revoked token answers 401
    # instantly, so the loop ran as fast as the socket allowed and wrote thousands of
    # identical lines a minute into the journal for as long as the token stayed bad.
    failures = 0

    while True:
        try:
            params = {"offset": managed_offset, "timeout": 20}
            response = await client.get(url, params=params, timeout=25.0)
            if response.status_code == 200:
                failures = 0
                data = response.json()
                for update in data.get("result", []):
                    managed_offset = update["update_id"] + 1
                    message = update.get("message", {})
                    text = message.get("text", "")
                    chat_id = message.get("chat", {}).get("id")
                    if not chat_id or not text.strip().startswith("/start"):
                        continue

                    print(f"Managed Telegram poller: received /start from chat_id={chat_id}")

                    parts = text.strip().split(maxsplit=1)
                    payload = parts[1].strip() if len(parts) > 1 else ""
                    username = resolve_telegram_link_payload(payload)
                    if not username:
                        print(f"Managed Telegram poller: unresolvable payload for chat_id={chat_id} , sent 'expired link' notice")
                        await get_http_client().post(
                            f"https://api.telegram.org/bot{config.TELEGRAM_MANAGED_BOT_TOKEN}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "This link has expired or is invalid. Please use the 'Connect Telegram' button in Studiamo Settings again.",
                            },
                        )
                        continue

                    write_user_config(username, {"TELEGRAM_CHAT_ID": str(chat_id)})
                    conn = None
                    try:
                        conn = get_db_connection(username)
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE user_profile SET notify_telegram = true WHERE user_uuid = %s;",
                            (conn.user_uuid,)
                        )
                        conn.commit()
                    finally:
                        if conn is not None:
                            conn.close()

                    await send_telegram_message(
                        "🧠 <b>Studiamo connected!</b>\n\n"
                        f"Hi {username}, your Telegram is now linked. "
                        "You'll receive your enabled notifications directly in this chat.\n\n"
                        f"Open Studiamo: {notification_app_link()}",
                        username
                    )
                    print(f"Managed Telegram poller: bound chat_id={chat_id} to user='{username}'")
            else:
                failures += 1
                delay = _managed_poll_backoff(failures)
                print(
                    f"Managed Telegram getUpdates non-200: {response.status_code} "
                    f"{response.text[:200]} (attempt {failures}, retrying in {delay}s)"
                )
                await asyncio.sleep(delay)
        except Exception as e:
            failures += 1
            delay = _managed_poll_backoff(failures)
            print(f"Managed Telegram poller error: {e} (attempt {failures}, retrying in {delay}s)")
            await asyncio.sleep(delay)

last_check_times = {}

async def check_and_notify_quizzes():
    for username in database.get_all_users():
        conn = None
        try:
            conn = get_db_connection(username)
            user_uuid = conn.user_uuid
            cursor = conn.cursor()

            # Read notification settings directly from user_profile DB columns
            cursor.execute(
                """
                SELECT notifications_enabled, notify_telegram, notify_push, notify_email,
                       notify_cat_quizzes, preferred_hour, base_url, google_email,
                       telegram_bot_token, telegram_chat_id
                FROM user_profile WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            profile = cursor.fetchone() or {}

            if not profile.get("notifications_enabled", 1):
                continue

            if not profile.get("notify_cat_quizzes", 1):
                continue

            # Check preferred daily review hour
            pref_hour = int(profile.get("preferred_hour") or -1)
            if pref_hour != -1:
                current_hour = datetime.now().hour
                if current_hour != pref_hour:
                    continue

            cursor.execute("""
                SELECT q.id, q.quiz_type, q.srs_stage, q.next_review_at, 
                       v.title AS video_title
                FROM quizzes q
                LEFT JOIN videos v ON q.video_id = v.id
                WHERE q.user_uuid = %s
                  AND q.notified = 0
                  AND q.quiz_type = 'video'
                  AND v.is_paused = 0 
                  AND v.is_archived = 0 
                  AND v.is_watchlist = 0
                  AND q.importance_level = v.importance_rating;
            """, (user_uuid,))
            rows = [dict(r) for r in cursor.fetchall()]
            
            now_utc = datetime.utcnow()
            due_rows = []
            for r in rows:
                if r.get("next_review_at"):
                    try:
                        val = r["next_review_at"]
                        dt = val if isinstance(val, datetime) else datetime.fromisoformat(str(val))
                        if dt.tzinfo is not None:
                            dt = dt.replace(tzinfo=None)
                        if dt <= now_utc:
                            due_rows.append(r)
                    except Exception as e:
                        print(f"Failed to parse next_review_at={r.get('next_review_at')!r} for quiz id={r.get('id')}: {e}")

            if not due_rows:
                continue

            count = len(due_rows)
            app_link = notification_app_link(profile.get("base_url"))

            # Independent per-channel delivery , every enabled channel fires.
            if profile.get("notify_push"):
                try:
                    from app.webpush_utils import send_user_web_push
                    push_title = f"🧠 {count} reviews due!" if count > 1 else f"🧠 {due_rows[0].get('video_title') or 'Review'} due!"
                    push_body = f"You have {count} review(s) due in Studiamo."
                    send_user_web_push(username, {
                        "title": push_title,
                        "body": push_body,
                        "url": "/#review-section"
                    })
                except Exception as e_push:
                    print(f"Error triggering Web Push for {username}: {e_push}")

            if count == 1:
                title = due_rows[0].get("video_title") or "Review item"
                msg = (
                    f"🔔 <b>Review Due!</b>\n\n"
                    f"Hi {username}, 1 item is ready for your Active Recall session:\n"
                    f"• <b>{title}</b>\n\n"
                    f"Start your session here:\n"
                    f"{app_link}"
                )
            else:
                msg = (
                    f"🔔 <b>Reviews Due!</b>\n\n"
                    f"Hi {username}, you have <b>{count} reviews due</b> for Active Recall.\n\n"
                    f"Start your session here:\n"
                    f"{app_link}"
                )

            if profile.get("notify_telegram"):
                await send_telegram_message(msg, username)

            if profile.get("notify_email") and profile.get("google_email"):
                try:
                    from app.email_utils import send_notification_email
                    send_notification_email(
                        profile["google_email"],
                        f"🔔 {count} reviews due!" if count > 1 else "🔔 A review is due!",
                        "Review Due" if count == 1 else "Reviews Due",
                        f"You have {count} review(s) due for your Active Recall in Studiamo.",
                        app_link,
                        "Review Now"
                    )
                except Exception as e_mail:
                    print(f"Error sending notification email for {username}: {e_mail}")

            # Mark quizzes as notified in database using existing cursor
            for r in due_rows:
                cursor.execute("UPDATE quizzes SET notified = 1 WHERE id = %s AND user_uuid = %s;", (r["id"], user_uuid))
            conn.commit()

        except Exception as e:
            print(f"Error checking notifications for {username}: {e}")
        finally:
            if conn is not None:
                conn.close()


last_streak_warned_dates = {}

async def check_and_notify_streak():
    """Checks user streaks and sends Telegram warning if <= 5 hours remain before expiration."""
    now_utc = gamification.utc_now()
    today_str = now_utc.strftime("%Y-%m-%d")

    for username in database.get_all_users():
        if last_streak_warned_dates.get(username) == today_str:
            continue

        conn = None
        try:
            conn = get_db_connection(username)
            user_uuid = conn.user_uuid
            cursor = conn.cursor()

            # Read notification settings and streak in one query from user_profile
            cursor.execute(
                """
                SELECT notifications_enabled, notify_telegram, notify_push, notify_email,
                       notify_cat_streak, base_url, google_email,
                       telegram_bot_token, telegram_chat_id,
                       streak, last_quiz_at
                FROM user_profile WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            row = cursor.fetchone()

            if not row:
                continue

            if not row.get("notifications_enabled", 1):
                continue

            if not row.get("notify_cat_streak", 1):
                continue

            # Both the number quoted in the message and the deadline it is counting down to
            # come from app/gamification.py, so this warning cannot promise a streak the app
            # will not honor. It used to bill the deadline as 24 hours after the last quiz,
            # which is not the rule anywhere: a streak survives to the end of the day after
            # the last quiz.
            streak_val = gamification.effective_streak(
                row.get("streak"), row.get("last_quiz_at"), now=now_utc
            )
            if streak_val <= 0:
                continue

            hours_left = gamification.hours_until_streak_lapses(row.get("last_quiz_at"), now=now_utc)
            if hours_left is None:
                continue

            if 0 < hours_left <= 5:
                hours_fmt = int(math.ceil(hours_left))
                app_link = notification_app_link(row.get("base_url"))

                any_channel_enabled = bool(row.get("notify_telegram") or row.get("notify_push") or row.get("notify_email"))

                if row.get("notify_push"):
                    try:
                        from app.webpush_utils import send_user_web_push
                        send_user_web_push(username, {
                            "title": f"🔥 Streak at risk ({streak_val} days)!",
                            "body": f"Your streak expires in ~{hours_fmt} hour(s). Complete 1 quick review now!",
                            "url": "/#review-section"
                        })
                    except Exception as e_push:
                        print(f"Error triggering Web Push streak warning for {username}: {e_push}")

                if row.get("notify_telegram"):
                    msg = (
                        f"🔥 <b>Streak Warning!</b>\n\n"
                        f"Hi {username}, your <b>{streak_val}-day streak</b> expires in ~<b>{hours_fmt} hour(s)</b>!\n\n"
                        f"Complete 1 quick review now to keep it active:\n"
                        f"{app_link}"
                    )
                    await send_telegram_message(msg, username)

                if row.get("notify_email") and row.get("google_email"):
                    try:
                        from app.email_utils import send_notification_email
                        send_notification_email(
                            row["google_email"],
                            f"🔥 Streak Warning ({streak_val} days)!",
                            "Your streak is about to expire",
                            f"Your {streak_val}-day streak expires in ~{hours_fmt} hour(s). Complete 1 quick review now to keep it active.",
                            app_link,
                            "Review Now"
                        )
                    except Exception as e_mail:
                        print(f"Error sending streak notification email for {username}: {e_mail}")

                # Mark as warned for today regardless of per-channel delivery
                # success , the scheduler re-checks every 60s, so this is what
                # prevents retry spam within the same day.
                if any_channel_enabled:
                    last_streak_warned_dates[username] = today_str
        except Exception as e:
            print(f"Error checking streak notification for {username}: {e}")
        finally:
            if conn is not None:
                conn.close()




async def check_and_notify_inactivity():
    """Sends a 'come back' reminder to users who haven't done a quiz in >= 7
    days, at most once every 7 days. Skips users who have never done a quiz, nothing to compare against, and brand-new signups shouldn't be nagged."""
    now_utc = datetime.utcnow()

    for username in database.get_all_users():
        conn = None
        try:
            conn = get_db_connection(username)
            user_uuid = conn.user_uuid
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT notifications_enabled, notify_telegram, notify_push, notify_email,
                       notify_cat_inactivity, base_url, google_email,
                       last_quiz_at, last_inactivity_notified_at
                FROM user_profile WHERE user_uuid = %s LIMIT 1;
                """,
                (user_uuid,)
            )
            row = cursor.fetchone()

            if not row or not row.get("notifications_enabled", 1) or not row.get("notify_cat_inactivity", 1):
                continue

            if not row.get("last_quiz_at"):
                continue

            def _normalize(val):
                dt = val if isinstance(val, datetime) else datetime.fromisoformat(str(val))
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt

            last_quiz = _normalize(row["last_quiz_at"])
            days_inactive = (now_utc - last_quiz).days
            if days_inactive < 7:
                continue

            last_notified = row.get("last_inactivity_notified_at")
            if last_notified and (now_utc - _normalize(last_notified)).days < 7:
                continue

            app_link = notification_app_link(row.get("base_url"))
            sent_any = False

            if row.get("notify_push"):
                try:
                    from app.webpush_utils import send_user_web_push
                    if send_user_web_push(username, {
                        "title": "👋 We miss you!",
                        "body": f"You haven't practiced in {days_inactive} days. Time for a quick review!",
                        "url": "/#review-section"
                    }):
                        sent_any = True
                except Exception as e_push:
                    print(f"Error sending inactivity Web Push for {username}: {e_push}")

            if row.get("notify_telegram"):
                msg = (
                    f"👋 <b>We miss you!</b>\n\n"
                    f"Hi {username}, you haven't practiced in Studiamo for <b>{days_inactive} days</b>.\n\n"
                    f"Start a quick review now:\n"
                    f"{app_link}"
                )
                if await send_telegram_message(msg, username):
                    sent_any = True

            if row.get("notify_email") and row.get("google_email"):
                try:
                    from app.email_utils import send_notification_email
                    if send_notification_email(
                        row["google_email"],
                        "👋 We miss you on Studiamo!",
                        "Time for a review",
                        f"You haven't practiced in Studiamo for {days_inactive} days. Your due reviews are waiting for you.",
                        app_link,
                        "Review Now"
                    ):
                        sent_any = True
                except Exception as e_mail:
                    print(f"Error sending inactivity email for {username}: {e_mail}")

            if sent_any:
                cursor.execute(
                    "UPDATE user_profile SET last_inactivity_notified_at = %s WHERE user_uuid = %s;",
                    (now_utc, user_uuid)
                )
                conn.commit()
        except Exception as e:
            print(f"Error checking inactivity notification for {username}: {e}")
        finally:
            if conn is not None:
                conn.close()


async def run_scheduler_daemon():
    """Runs a background loop to perform review scheduling checks every 1 minute."""
    print("Scheduler daemon started in background...")
    while True:
        try:
            await check_and_notify_quizzes()
            await check_and_notify_streak()
            await check_and_notify_inactivity()
            try:
                from app.import_manager import ImportQueueManager
                ImportQueueManager.get_instance().recover_all_pending_tasks()
            except Exception as e_recovery:
                print(f"Periodic task recovery error in scheduler: {e_recovery}")
        except Exception as e:
            print(f"Scheduler daemon error: {e}")
        await asyncio.sleep(60)


