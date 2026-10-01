import asyncio
import httpx
import secrets
import time
from app import config, database
from app.config import load_user_config, write_user_config
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

_last_tester_sweep_at: float = 0.0
_TESTER_SWEEP_INTERVAL_SECONDS = 3600
# Chompy eats right after local midnight; a few minutes' delay does not matter, and each pass
# reads every user's due reviews, so it runs less often than the reminder check.
_last_chompy_pass_at: float = 0.0
_CHOMPY_INTERVAL_SECONDS = 600


async def run_scheduler_daemon():
    """Runs a background loop to perform review scheduling checks every 1 minute."""
    print("Scheduler daemon started in background...")
    global _last_tester_sweep_at, _last_chompy_pass_at
    while True:
        try:
            if time.time() - _last_chompy_pass_at >= _CHOMPY_INTERVAL_SECONDS:
                _last_chompy_pass_at = time.time()
                try:
                    from app.chompy import run_eating
                    eaten = await asyncio.to_thread(run_eating)
                    if eaten:
                        print(f"Chompy paused {eaten} overdue review(s).")
                except Exception as e_chompy:
                    print(f"Chompy pass error: {e_chompy}")

            from app.notifications import run_tick as run_reminder_tick
            await run_reminder_tick()
            try:
                from app.import_manager import ImportQueueManager
                ImportQueueManager.get_instance().recover_all_pending_tasks()
            except Exception as e_recovery:
                print(f"Periodic task recovery error in scheduler: {e_recovery}")
            # Cosmetic admin-list hygiene only (see check_and_expire_testers' docstring),
            # so this runs at most hourly rather than on every 60-second tick.
            now = time.time()
            if now - _last_tester_sweep_at >= _TESTER_SWEEP_INTERVAL_SECONDS:
                _last_tester_sweep_at = now
                try:
                    flipped = await asyncio.to_thread(database.check_and_expire_testers)
                    if flipped:
                        print(f"Tester expiry sweep: flipped is_tester for {flipped} account(s).")
                except Exception as e_sweep:
                    print(f"Tester expiry sweep error: {e_sweep}")
        except Exception as e:
            print(f"Scheduler daemon error: {e}")
        await asyncio.sleep(60)


