import os
import json
import shutil
import uuid
import csv
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file into os.environ if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
    except ImportError:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'\"")

USERS_DIR = BASE_DIR / "users"
USERS_DIR.mkdir(parents=True, exist_ok=True)

# Application Execution Mode (selfhosted vs cloud)
APP_MODE = os.getenv("APP_MODE", "selfhosted").lower()
IS_CLOUD = (APP_MODE == "cloud")
IS_SELFHOSTED = not IS_CLOUD
MAX_SELFHOSTED_USERS = int(os.getenv("MAX_SELFHOSTED_USERS", "10"))

# Deployed commit, read once at process startup rather than per-request (bug reports
# attach this so a report can be tied to the exact code that produced it -- staging and
# prod can be on different commits). Empty string if this isn't a git checkout at all
# (e.g. a tarball deploy with no .git directory).
try:
    import subprocess
    GIT_COMMIT_HASH = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=BASE_DIR, capture_output=True, text=True, timeout=5
    ).stdout.strip()
except Exception:
    GIT_COMMIT_HASH = ""

# Shared managed Telegram bot (cloud mode only), lets cloud users connect
# notifications without creating their own bot. Optional: if unset, the
# cloud "Connect Telegram" flow is unavailable but nothing else breaks.
TELEGRAM_MANAGED_BOT_TOKEN = os.getenv("TELEGRAM_MANAGED_BOT_TOKEN", "")
TELEGRAM_MANAGED_BOT_USERNAME = os.getenv("TELEGRAM_MANAGED_BOT_USERNAME", "")

# Umami analytics website ID. Defaults to the managed studiamo.cloud tracker in cloud mode
# so the hosted site's behaviour doesn't change. Defaults to empty in self-hosted mode: a
# self-hoster's instance must not silently phone home to the cloud tracker just because it
# shares this codebase. Set UMAMI_WEBSITE_ID (and optionally UMAMI_SCRIPT_URL, for a
# self-hosted Umami instance) explicitly to opt in.
UMAMI_WEBSITE_ID = os.getenv(
    "UMAMI_WEBSITE_ID", "0d15e157-0afb-41c1-8c5e-db6ad375b139" if IS_CLOUD else ""
)
UMAMI_SCRIPT_URL = os.getenv("UMAMI_SCRIPT_URL", "https://cloud.umami.is/script.js")


# Lemon Squeezy subscription billing. Read lazily via get_lemonsqueezy_config() rather
# than at import time: require_env_for_cloud raises when a value is missing in cloud mode,
# and doing that at module import would break `import app.config` for every tool and
# script that only wants an unrelated setting.
LEMONSQUEEZY_BETA_DISCOUNT_CODE = os.getenv("LEMONSQUEEZY_BETA_DISCOUNT_CODE", "")


def require_env_for_cloud(name: str, default: str = "") -> str:
    """Returns the named env var. In cloud mode, refuses to start (raises
    RuntimeError) if it's unset/empty instead of silently using a fallback, a missing secret or config value should be a loud startup failure in
    production, not a quiet misconfiguration. Self-hosted keeps `default`."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    if IS_CLOUD:
        raise RuntimeError(f"{name} must be set when APP_MODE=cloud.")
    return default


def get_lemonsqueezy_config() -> dict:
    """Returns the Lemon Squeezy settings needed for checkout and webhook handling.

    In cloud mode every value is mandatory and a missing one raises, because a half-configured
    payment integration fails in the worst possible way: checkout links that 404, or webhooks
    whose signature can't be verified and are therefore silently dropped, losing a payment the
    customer has already made. Self-hosted returns empty strings, there is no billing there."""
    return {
        "api_key": require_env_for_cloud("LEMONSQUEEZY_API_KEY"),
        "store_id": require_env_for_cloud("LEMONSQUEEZY_STORE_ID"),
        "webhook_secret": require_env_for_cloud("LEMONSQUEEZY_WEBHOOK_SECRET"),
        "buy_url": require_env_for_cloud("LEMONSQUEEZY_BUY_URL"),
        "beta_discount_code": LEMONSQUEEZY_BETA_DISCOUNT_CODE,
    }


# Centralized Global SRS & Recall Defaults
DEFAULT_SRS_INTERVALS = [1, 3, 7, 14, 30]
DEFAULT_QUESTION_COUNTS = [2, 3, 5, 8, 12]
DEFAULT_SRS_MULTIPLIERS = [4.0, 2.5, 1.5, 1.0, 0.7]
DEFAULT_SRS_CAPS = [2, 3, 4, 5, 5]
DEFAULT_ENABLE_STAGE_5_REPETITION = False
DEFAULT_STAGE_5_REPEAT_INTERVAL = 30

# "What's New" popup versioning. user_profile.has_seen_updates stores the version
# number a user has last dismissed (it's an INTEGER column, not a strict boolean).
# Bump this whenever the What's New content in index.html actually changes, so
# existing users (whose stored value is now behind) see the popup again once.
# New signups are inserted with has_seen_updates already equal to this value
# (see database.init_db), so they never see an announcement for changes that
# predate their account. Started at 2 because the column's old boolean-era
# values only ever reached 1.
CURRENT_UPDATE_VERSION = 2

_username_uuid_cache = {}
_uuid_username_cache = {}


def looks_like_uuid(value: str) -> bool:
    """Whether a string has the shape of the UUID4s used as user_uuid."""
    return bool(value) and len(value) == 36 and value.count("-") == 4


def get_user_uuid_from_db(username: str) -> str:
    """Finds user_uuid for username from the Supabase user_profile table. Successful lookups are
    cached in-memory for the process lifetime since a username's user_uuid never changes after creation.

    Returns "" when no profile row exists, never the username itself. Falling back to the username
    used to mean an unknown (or momentarily unreadable) user silently resolved to a *plausible-looking*
    id: signup then wrote it straight into user_profile.user_uuid, and every user_uuid column is TEXT,
    so Postgres accepted a username as a user id without complaint. A DB error raises for the same
    reason, a caller must never get back an id that scopes queries and file paths to the wrong place."""
    if not username:
        return ""
    if looks_like_uuid(username):
        return username
    uname_key = username.lower()
    if uname_key in _username_uuid_cache:
        return _username_uuid_cache[uname_key]
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT user_uuid FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;", (username,))
        row = cursor.fetchone()
        cursor.close()
        if row and row.get("user_uuid"):
            _username_uuid_cache[uname_key] = row["user_uuid"]
            return row["user_uuid"]
    finally:
        if conn is not None:
            release_pooled_connection(conn)
    return ""


def get_username_from_uuid(user_uuid: str) -> str:
    """Resolves the CURRENT username for an (immutable) user_uuid. This is the reverse
    of get_user_uuid_from_db() and is what the session layer must use: the signed
    session cookie names a user_uuid, never a username, because usernames can be
    renamed (see routers/settings.py) and a signed token can't be edited in place, resolving the display name fresh on every request is what keeps a rename from
    silently orphaning every session naming the old username.

    Returns "" when no profile row exists for that uuid (e.g. a deleted account)."""
    if not user_uuid:
        return ""
    if user_uuid in _uuid_username_cache:
        return _uuid_username_cache[user_uuid]
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT username FROM user_profile WHERE user_uuid = %s LIMIT 1;", (user_uuid,))
        row = cursor.fetchone()
        cursor.close()
        if row and row.get("username"):
            username = row["username"]
            _uuid_username_cache[user_uuid] = username
            _username_uuid_cache[username.lower()] = user_uuid
            return username
    finally:
        if conn is not None:
            release_pooled_connection(conn)
    return ""


def cache_user_uuid(username: str, user_uuid: str):
    """Seeds both directions of the username <-> user_uuid cache, used right after a
    profile row is created."""
    if username and user_uuid:
        _username_uuid_cache[username.lower()] = user_uuid
        _uuid_username_cache[user_uuid] = username


def forget_user_uuid(username: str, user_uuid: str = None):
    """Drops a username (and, if known, its user_uuid) from both caches. Must be
    called when an account is deleted: the caches never expire on their own, so
    without this a later signup reusing that username, or a lingering session
    naming the old uuid, would resolve straight back to the deleted account."""
    if username:
        _username_uuid_cache.pop(username.lower(), None)
    if user_uuid:
        _uuid_username_cache.pop(user_uuid, None)


def get_user_dir(username: str) -> Path:
    """Returns the on-disk directory for a user: users/<user_uuid>/.

    Raises for a username with no profile row instead of creating users/<username>/, a user directory is only ever named after a real user_uuid."""
    user_uuid = get_user_uuid_from_db(username)
    if not user_uuid:
        raise ValueError(f"No user_profile row for '{username}' , cannot resolve a user directory.")
    user_dir = USERS_DIR / user_uuid
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

def load_user_config(username: str) -> dict:
    """Loads user configuration directly from Supabase PostgreSQL user_profile table columns."""
    if not username:
        return {}
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT display_name, email, google_id, google_email,
                   password_hash, gemini_api_key, telegram_bot_token, telegram_chat_id,
                   base_url
            FROM user_profile
            WHERE LOWER(username) = LOWER(%s) LIMIT 1;
        """, (username,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            cfg = {}
            if row.get("display_name"):
                cfg["DISPLAY_NAME"] = cfg["display_name"] = row["display_name"]
            if row.get("email"):
                cfg["EMAIL"] = cfg["email"] = row["email"]
            if row.get("google_id"):
                cfg["GOOGLE_ID"] = row["google_id"]
            if row.get("google_email"):
                cfg["GOOGLE_EMAIL"] = row["google_email"]
            if row.get("password_hash"):
                cfg["PASSWORD_HASH"] = row["password_hash"]
            if row.get("gemini_api_key"):
                cfg["GEMINI_API_KEY"] = row["gemini_api_key"]
            if row.get("telegram_bot_token"):
                cfg["TELEGRAM_BOT_TOKEN"] = row["telegram_bot_token"]
            if row.get("telegram_chat_id"):
                cfg["TELEGRAM_CHAT_ID"] = row["telegram_chat_id"]
            if row.get("base_url"):
                cfg["BASE_URL"] = row["base_url"]
            return cfg
        return {}
    finally:
        release_pooled_connection(conn)


def write_user_config(username: str, updates: dict):
    """Writes user configuration updates directly to Supabase PostgreSQL user_profile table columns."""
    if not username:
        return
    from app.database import get_pooled_raw_connection, release_pooled_connection
    import psycopg2.extras
    conn = get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        display_name = updates.get("DISPLAY_NAME") or updates.get("display_name")
        email = updates.get("EMAIL") or updates.get("email")
        google_id = updates.get("GOOGLE_ID")
        google_email = updates.get("GOOGLE_EMAIL")
        password_hash = updates.get("PASSWORD_HASH")
        gemini_api_key = updates.get("GEMINI_API_KEY")
        telegram_bot_token = updates.get("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = updates.get("TELEGRAM_CHAT_ID")
        base_url = updates.get("BASE_URL")
        voice_engine = updates.get("VOICE_ENGINE") or updates.get("voice_engine")
        voice_speed = updates.get("VOICE_SPEED") or updates.get("voice_speed")

        cursor.execute("""
            UPDATE user_profile
            SET display_name = COALESCE(%s, display_name),
                email = COALESCE(%s, email),
                google_id = COALESCE(%s, google_id),
                google_email = COALESCE(%s, google_email),
                password_hash = COALESCE(%s, password_hash),
                gemini_api_key = COALESCE(%s, gemini_api_key),
                telegram_bot_token = COALESCE(%s, telegram_bot_token),
                telegram_chat_id = COALESCE(%s, telegram_chat_id),
                base_url = COALESCE(%s, base_url),
                voice_engine = COALESCE(%s, voice_engine),
                voice_speed = COALESCE(%s, voice_speed)
            WHERE LOWER(username) = LOWER(%s);
        """, (display_name, email, google_id, google_email, password_hash, gemini_api_key,
              telegram_bot_token, telegram_chat_id, base_url, voice_engine, voice_speed, username))
        if not getattr(conn, "autocommit", False):
            conn.commit()
        cursor.close()
    finally:
        release_pooled_connection(conn)

def get_config(key: str, default: str = "", username: str = "") -> str:
    """Gets configuration value from user-specific config, falling back to os.getenv."""
    if key == "BASE_URL" and not default:
        default = os.getenv("BASE_URL", "https://studiamo.cloud")

    # In Cloud mode, GEMINI_API_KEY always uses central global key from .env
    if IS_CLOUD and key == "GEMINI_API_KEY":
        return os.getenv("GEMINI_API_KEY", default)

    # YOUTUBE_API_KEY is admin-set only, in both modes. The only place it can come from is the deployment's own
    # .env, never a per-user config value (there is no write path for one today, but this
    # makes that permanent rather than accidental).
    if key == "YOUTUBE_API_KEY":
        return os.getenv("YOUTUBE_API_KEY", default)

    if username:
        user_cfg = load_user_config(username)
        val = user_cfg.get(key)
        if val:
            return val
    return os.getenv(key, default)

def is_configured(username: str = "") -> bool:
    """Checks if the minimum required settings are configured for this user."""
    return bool(get_config("GEMINI_API_KEY", username=username))

def ensure_user_uuid(username: str) -> str:
    """Gets the authoritative user_uuid for a username directly from PostgreSQL user_profile table."""
    return get_user_uuid_from_db(username)

def sync_user_registry():
    """No-op: User registry is managed directly in Supabase PostgreSQL user_profile table."""
    pass


# Cloud fallback defaults: Used only in cloud mode if unset in the app_settings database table.
# In self-hosted mode, storage and uploads are uncapped by default unless explicitly configured via env.
MAX_USER_STORAGE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_FILE_UPLOAD_BYTES = 20 * 1024 * 1024          # 20 MB

def get_user_storage_quota_bytes() -> int:
    """Returns storage quota per user in bytes. 0 means uncapped.

    In self-hosted mode: reads MAX_USER_STORAGE_GB, MAX_USER_STORAGE_MB, or MAX_USER_STORAGE_BYTES from env (0/unset = uncapped).
    In cloud mode: reads from app_settings ('storage_user_quota_gb', 'storage_user_quota_mb', or 'storage_user_quota_bytes'),
    converting GB/MB into bytes automatically and falling back to MAX_USER_STORAGE_BYTES.
    """
    if IS_SELFHOSTED:
        env_gb = os.getenv("MAX_USER_STORAGE_GB", "").strip()
        if env_gb and env_gb.isdigit():
            return int(env_gb) * 1024 * 1024 * 1024
        env_mb = os.getenv("MAX_USER_STORAGE_MB", "").strip()
        if env_mb and env_mb.isdigit():
            return int(env_mb) * 1024 * 1024
        env_bytes = os.getenv("MAX_USER_STORAGE_BYTES", "").strip()
        if env_bytes and env_bytes.isdigit():
            return int(env_bytes)
        return 0

    from app.database import get_app_setting
    try:
        # Check human-friendly GB key first (e.g. "2" for 2 GB), then MB, then raw bytes
        val_gb = get_app_setting("storage_user_quota_gb", "")
        if val_gb and val_gb.strip().isdigit():
            return int(val_gb.strip()) * 1024 * 1024 * 1024
        val_mb = get_app_setting("storage_user_quota_mb", "")
        if val_mb and val_mb.strip().isdigit():
            return int(val_mb.strip()) * 1024 * 1024
        val_bytes = get_app_setting("storage_user_quota_bytes", "")
        if val_bytes and val_bytes.strip().isdigit():
            return int(val_bytes.strip())
    except Exception:
        pass
    return MAX_USER_STORAGE_BYTES


def get_max_file_upload_bytes() -> int:
    """Returns maximum single-file upload size in bytes. 0 means uncapped.

    In self-hosted mode: reads MAX_FILE_UPLOAD_MB or MAX_FILE_UPLOAD_BYTES from env (0/unset = uncapped).
    In cloud mode: reads from app_settings ('storage_max_upload_mb' or 'storage_max_upload_bytes'),
    converting MB into bytes automatically and falling back to MAX_FILE_UPLOAD_BYTES.
    """
    if IS_SELFHOSTED:
        env_mb = os.getenv("MAX_FILE_UPLOAD_MB", "").strip()
        if env_mb and env_mb.isdigit():
            return int(env_mb) * 1024 * 1024
        env_bytes = os.getenv("MAX_FILE_UPLOAD_BYTES", "").strip()
        if env_bytes and env_bytes.isdigit():
            return int(env_bytes)
        return 0

    from app.database import get_app_setting
    try:
        # Check human-friendly MB key first (e.g. "20" for 20 MB), then raw bytes
        val_mb = get_app_setting("storage_max_upload_mb", "")
        if val_mb and val_mb.strip().isdigit():
            return int(val_mb.strip()) * 1024 * 1024
        val_bytes = get_app_setting("storage_max_upload_bytes", "")
        if val_bytes and val_bytes.strip().isdigit():
            return int(val_bytes.strip())
    except Exception:
        pass
    return MAX_FILE_UPLOAD_BYTES


def get_user_storage_bytes(username: str) -> int:
    """Calculates total disk usage in bytes for a user's directory."""
    user_dir = get_user_dir(username)
    total_bytes = 0
    if user_dir.exists():
        for path, _, filenames in os.walk(user_dir):
            for f in filenames:
                fp = os.path.join(path, f)
                if os.path.exists(fp):
                    total_bytes += os.path.getsize(fp)
    return total_bytes


