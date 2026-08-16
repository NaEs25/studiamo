"""
Database module for Studiamo, Supabase PostgreSQL Integration
Provides unified connection pool & parameter wrapping for clean execution across the app.
"""
import os
import sys
import logging
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from pathlib import Path

logger = logging.getLogger("studiamo")

BASE_DIR = Path(__file__).resolve().parent.parent

_DB_URL = None
_pool = None
_schema_ensured = False
_initialized_users = set()

POOL_MIN_CONN = int(os.environ.get("SUPABASE_POOL_MIN_CONN", "4"))
POOL_MAX_CONN = int(os.environ.get("SUPABASE_POOL_MAX_CONN", "50"))

def get_supabase_db_url():
    global _DB_URL
    if _DB_URL:
        return _DB_URL
    
    from app.config import IS_CLOUD
    
    if IS_CLOUD:
        url = os.getenv("CLOUD_DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    else:
        url = os.getenv("SELFHOSTED_DATABASE_URL") or os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

    if not url:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                env_vars = {}
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            v = v[1:-1]
                        env_vars[k] = v

                if IS_CLOUD:
                    url = env_vars.get("CLOUD_DATABASE_URL") or env_vars.get("SUPABASE_DB_URL") or env_vars.get("DATABASE_URL")
                else:
                    url = env_vars.get("SELFHOSTED_DATABASE_URL") or env_vars.get("DATABASE_URL") or env_vars.get("SUPABASE_DB_URL")

    if url:
        _DB_URL = url
        return url
    raise ValueError("No database URL (CLOUD_DATABASE_URL / SELFHOSTED_DATABASE_URL / DATABASE_URL) found in environment or .env")

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Returns the shared connection pool, creating it lazily on first use."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(POOL_MIN_CONN, POOL_MAX_CONN, get_supabase_db_url())
    return _pool

def get_pooled_raw_connection():
    """Borrows a raw psycopg2 connection from the shared pool for admin/no-user-context queries."""
    conn = _get_pool().getconn()
    conn.autocommit = True
    return conn

def release_pooled_connection(raw_conn):
    """Returns a raw connection to the shared pool, rolling back any uncommitted state first."""
    try:
        if not raw_conn.autocommit:
            raw_conn.rollback()
    except Exception as e:
        # Rollback failing usually means the connection is already broken, proceed to
        # putconn/close below regardless, but this is worth knowing if the pool ever
        # seems to be leaking connections.
        logger.debug(f"[release_pooled_connection] rollback failed (connection may be dead): {e}")
    try:
        _get_pool().putconn(raw_conn)
    except Exception:
        try:
            raw_conn.close()
        except Exception as e:
            logger.warning(f"[release_pooled_connection] Failed to return AND close a connection, likely leaked: {e}")

class CursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        if isinstance(sql, str) and "?" in sql:
            sql = sql.replace("?", "%s")
        if params is not None:
            return self.cursor.execute(sql, params)
        return self.cursor.execute(sql)

    def executemany(self, sql, param_list):
        if isinstance(sql, str) and "?" in sql:
            sql = sql.replace("?", "%s")
        return self.cursor.executemany(sql, param_list)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchmany(self, size=None):
        return self.cursor.fetchmany(size) if size else self.cursor.fetchmany()

    @property
    def rowcount(self):
        return self.cursor.rowcount

    @property
    def lastrowid(self):
        return getattr(self.cursor, "lastrowid", None)

    def __iter__(self):
        return iter(self.cursor)

class ConnectionWrapper:
    def __init__(self, raw_conn, user_uuid=None):
        self._conn = raw_conn
        self.user_uuid = user_uuid

    def cursor(self, *args, **kwargs):
        if "cursor_factory" not in kwargs:
            kwargs["cursor_factory"] = RealDictCursor
        return CursorWrapper(self._conn.cursor(*args, **kwargs))

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        if not getattr(self._conn, "autocommit", False):
            self._conn.commit()

    def rollback(self):
        if not getattr(self._conn, "autocommit", False):
            self._conn.rollback()

    def close(self):
        release_pooled_connection(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

def get_db_connection(username: str):
    """Borrows a pooled Supabase PostgreSQL connection and returns it wrapped."""
    from app.config import ensure_user_uuid
    user_uuid = ensure_user_uuid(username)
    raw_conn = get_pooled_raw_connection()
    raw_conn.autocommit = True
    return ConnectionWrapper(raw_conn, user_uuid=user_uuid)

def first_val(row, default=0):
    """Safely extracts the first column value whether row is a dict, tuple, or Row."""
    if not row:
        return default
    if isinstance(row, dict):
        return list(row.values())[0]
    return row[0]

def init_db(username: str, status: str = "active", referral_code: str = None, referred_by_uuid: str = None):
    """Ensures user profile and default SRS settings exist for a user in Supabase PostgreSQL.
    status/referral_code/referred_by_uuid only take effect on first creation (ON CONFLICT DO NOTHING), used by the Google-SSO signup path to set waitlist status and referral linkage atomically at creation."""
    if not username:
        return
    import uuid as _uuid
    from app.config import cache_user_uuid, load_user_config

    conn = get_db_connection(username)
    user_uuid = conn.user_uuid
    cursor = conn.cursor()
    try:
        if not user_uuid:
            # No profile row for this username yet, so this is the account's
            # creation. Mint a real UUID here, this is the only place one is
            # generated. Every user_uuid column is TEXT, so nothing downstream
            # would reject a username used as an id; it has to be right here.
            user_uuid = str(_uuid.uuid4())
            u_cfg = load_user_config(username)
            display_name = u_cfg.get("DISPLAY_NAME") or u_cfg.get("display_name", username)
            from app.config import CURRENT_UPDATE_VERSION
            try:
                cursor.execute(
                    """INSERT INTO user_profile
                       (user_uuid, username, display_name, xp, level, streak, badges, review_mode, status, referral_code, referred_by, has_seen_updates)
                       VALUES (%s, %s, %s, 0, 1, 0, '[]', 'video', %s, %s, %s, %s)
                       ON CONFLICT (user_uuid) DO NOTHING;""",
                    (user_uuid, username, display_name, status, referral_code, referred_by_uuid, CURRENT_UPDATE_VERSION)
                )
            except psycopg2.IntegrityError:
                # A concurrent signup already inserted this username and the
                # unique index on lower(username) rejected ours. Not an error:
                # the re-read below adopts the winning row.
                pass

            # Re-read by username so a concurrent signup that won the race is
            # the one authoritative row: whoever inserted first owns the
            # user_uuid, and the loser's freshly generated one is discarded
            # rather than being used to scope this request's writes.
            cursor.execute(
                "SELECT user_uuid FROM user_profile WHERE LOWER(username) = LOWER(%s) ORDER BY id LIMIT 1;",
                (username,)
            )
            row = cursor.fetchone()
            if row and row.get("user_uuid"):
                user_uuid = row["user_uuid"]
            conn.user_uuid = user_uuid
            cache_user_uuid(username, user_uuid)

        cursor.execute("SELECT COUNT(*) FROM srs_settings WHERE user_uuid = %s;", (user_uuid,))
        if first_val(cursor.fetchone()) == 0:
            cursor.execute(
                "INSERT INTO srs_settings (user_uuid, stage_1_days, stage_2_days, stage_3_days, stage_4_days, stage_5_days) VALUES (%s, 1, 3, 7, 14, 30) ON CONFLICT (user_uuid) DO NOTHING;",
                (user_uuid,)
            )
    finally:
        conn.close()


def ensure_user_initialized(username: str, status: str = "active", referral_code: str = None, referred_by_uuid: str = None):
    """Runs init_db for a given user once per process lifetime; a cheap no-op on every subsequent call.
    Use this instead of init_db() on hot paths like per-request auth checks."""
    if not username or username in _initialized_users:
        return
    init_db(username, status=status, referral_code=referral_code, referred_by_uuid=referred_by_uuid)
    _initialized_users.add(username)


def generate_referral_code() -> str:
    """Returns a fresh 12-character cryptographically random referral code."""
    import secrets
    return secrets.token_hex(6)


def get_app_setting(key: str, default: str = "") -> str:
    """Reads a single config value from the app_settings table."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT value FROM app_settings WHERE key = %s;", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def set_app_setting(key: str, value: str) -> None:
    """Writes a single config value to the app_settings table, upserting by key."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO app_settings (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;""",
            (key, value)
        )
        conn.commit()
        cursor.close()
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def get_max_users() -> int:
    """Returns the registration cap from app_settings.max_users. 0 (unset/invalid) means uncapped."""
    try:
        return int(get_app_setting("max_users", "0"))
    except (TypeError, ValueError):
        return 0


def count_active_users() -> int:
    """Returns the number of user_profile rows with status = 'active'."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT COUNT(*) AS n FROM user_profile WHERE status = 'active';")
        return cursor.fetchone()["n"]
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def is_at_capacity() -> bool:
    """Whether a new signup would land on the waitlist right now. Unset/zero cap means uncapped."""
    max_users = get_max_users()
    if max_users <= 0:
        return False
    return count_active_users() >= max_users


def find_user_by_referral_code(code: str):
    """Returns {"username", "user_uuid", "referral_count"} for the owner of a referral code, or None."""
    if not code:
        return None
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT username, user_uuid, referral_count FROM user_profile WHERE referral_code = %s LIMIT 1;",
            (code,)
        )
        return cursor.fetchone()
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def credit_referral(referral_code: str) -> bool:
    """Atomically increments the referrer's referral_count if under the 5-referral cap.
    Single UPDATE (not read-then-write) so concurrent referrals can't double-credit past the cap.
    Returns True if credited, False if the code doesn't exist or is already at the cap."""
    if not referral_code:
        return False
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "UPDATE user_profile SET referral_count = referral_count + 1 WHERE referral_code = %s AND referral_count < 5 RETURNING user_uuid;",
            (referral_code,)
        )
        return cursor.fetchone() is not None
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def promote_next_n_users(n: int) -> list:
    """Promotes up to n waitlist users to 'active', front of the queue first
    (highest referral_count, then oldest created_at, position is computed on
    read rather than a stored column, so ordering here is the source of truth).
    Returns the promoted rows [{"username", "email", "google_email"}, ...] so
    the caller can send promotion emails."""
    if n <= 0:
        return []
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            UPDATE user_profile SET status = 'active'
            WHERE user_uuid IN (
                SELECT user_uuid FROM user_profile
                WHERE status = 'waitlist'
                ORDER BY referral_count DESC, created_at ASC
                LIMIT %s
            )
            RETURNING username, email, google_email;
            """,
            (n,)
        )
        return cursor.fetchall()
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def ensure_referral_code(username: str) -> str:
    """Returns the user's referral_code, generating and persisting a unique one first if they don't have one yet."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT referral_code FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;", (username,))
        row = cursor.fetchone()
        if row and row.get("referral_code"):
            return row["referral_code"]
        for _ in range(5):
            code = generate_referral_code()
            try:
                cursor.execute(
                    "UPDATE user_profile SET referral_code = %s WHERE LOWER(username) = LOWER(%s);",
                    (code, username)
                )
                return code
            except Exception:
                continue
        raise RuntimeError(f"Could not generate a unique referral code for '{username}'.")
    finally:
        if conn is not None:
            release_pooled_connection(conn)


# Lemon Squeezy subscription statuses that grant access on their own.
#   active, paid and renewing
#   on_trial, inside a free trial (no trial is offered today, but LS can set this)
#   past_due, payment failed and LS is retrying. Access is deliberately kept during
#              dunning: cutting someone off for an expired card, before LS has finished
#              retrying it, punishes the customer for a bank's decision.
_ACCESS_GRANTING_STATUSES = {"active", "on_trial", "past_due"}


def has_app_access(username: str) -> bool:
    """Whether this account may use the cloud app: a subscription in good standing, or the
    tester flag.

    'cancelled' is handled separately and deliberately. In Lemon Squeezy it means "will not
    renew", NOT "access ends now", the customer has paid through the end of the current
    period and keeps access until ls_ends_at. Treating it as an immediate revocation would
    cut off people who have already paid for the month they are in.

    Returns False for statuses that genuinely end access ('paused', 'unpaid', 'expired',
    'inactive') and for any username with no profile row."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """SELECT subscription_status, is_tester, ls_ends_at
               FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;""",
            (username,)
        )
        row = cursor.fetchone()
        if not row:
            return False
        if row["is_tester"]:
            return True

        status = (row["subscription_status"] or "").lower()
        if status in _ACCESS_GRANTING_STATUSES:
            return True

        if status == "cancelled" and row["ls_ends_at"]:
            from datetime import datetime, timezone
            ends_at = row["ls_ends_at"]
            # ls_ends_at is TIMESTAMPTZ, but a naive value can still arrive via a direct
            # DB edit; compare in UTC either way rather than raising on the subtraction.
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            return ends_at > datetime.now(timezone.utc)

        return False
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def set_tester_access(username: str, is_tester: bool) -> bool:
    """Admin action: grants or revokes free tester access for one account. Returns True if a row was updated."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "UPDATE user_profile SET is_tester = %s WHERE LOWER(username) = LOWER(%s) RETURNING user_uuid;",
            (is_tester, username)
        )
        return cursor.fetchone() is not None
    finally:
        if conn is not None:
            release_pooled_connection(conn)


# Tables holding per-user data, keyed by user_uuid with no FK/cascade back to
# user_profile, every one has to be cleaned explicitly. Ordered so rows with
# FKs to other tables in this list are deleted before what they reference
# (quiz_attempts -> quizzes; import_tasks -> videos; quizzes/daily_recommendations/videos -> goals).
_USER_DATA_TABLES_DELETE_ORDER = [
    "quiz_attempts",
    "import_tasks",
    "quizzes",
    "daily_recommendations",
    "videos",
    "goals",
    "ai_usage_logs",
    "srs_settings",
    "dismissed_recommendations",
    "goal_recommendations",
    "push_subscriptions",
]


def delete_user_account(username: str, dry_run: bool = True) -> dict:
    """Deletes a user and all their data: every per-user table (none of which
    cascade from user_profile, see _USER_DATA_TABLES_DELETE_ORDER), the
    user_profile row itself, and their users/<user_uuid>/ directory on disk.

    Single source of truth for account deletion so both admin cleanup scripts
    and any future self-service "delete my account" endpoint stay consistent.

    Runs as one transaction: a user is either fully gone or untouched. Without
    that, a failure partway through left a profile row whose data had already
    been deleted, an account that still exists but is empty.

    With dry_run=True (default), only counts rows that would be deleted, nothing is removed. Pass dry_run=False to actually delete.
    Returns {"user_uuid", "username", "counts": {table: n}, "dir_removed": bool}.
    """
    from app.config import forget_user_uuid

    conn = None
    try:
        conn = get_pooled_raw_connection()
        conn.autocommit = False
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT user_uuid, username FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"No user_profile row found for username '{username}'.")
        user_uuid = row["user_uuid"]
        real_username = row["username"]

        counts = {}
        for table in _USER_DATA_TABLES_DELETE_ORDER:
            if dry_run:
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_uuid = %s;", (user_uuid,))
                counts[table] = cursor.fetchone()["n"]
            else:
                cursor.execute(f"DELETE FROM {table} WHERE user_uuid = %s;", (user_uuid,))
                counts[table] = cursor.rowcount

        # Anyone this user referred keeps their account, but their referred_by
        # pointer has to go first: user_profile.referred_by is a FK back to
        # user_profile.user_uuid with no ON DELETE rule, so deleting a user who
        # referred even one person raised a ForeignKeyViolation and aborted.
        cursor.execute("SELECT COUNT(*) AS n FROM user_profile WHERE referred_by = %s;", (user_uuid,))
        counts["referrals_orphaned"] = cursor.fetchone()["n"]
        if not dry_run:
            cursor.execute("UPDATE user_profile SET referred_by = NULL WHERE referred_by = %s;", (user_uuid,))

        if dry_run:
            counts["user_profile"] = 1
        else:
            cursor.execute("DELETE FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
            counts["user_profile"] = cursor.rowcount

        from app.config import USERS_DIR
        user_dir = USERS_DIR / user_uuid
        dir_removed = False

        if dry_run:
            conn.rollback()
            dir_removed = user_dir.exists()  # would be removed
        else:
            # Commit before touching disk, so a failed transaction can never
            # leave the database intact with the user's files already gone.
            conn.commit()
            # Both caches are keyed by username and never expire, so a signup
            # reusing this username later in the same process would otherwise
            # resolve straight back to the deleted account's user_uuid. Matched
            # case-insensitively because callers reach these by either spelling.
            forget_user_uuid(real_username, user_uuid)
            for cached in [u for u in _initialized_users if u.lower() in (real_username.lower(), username.lower())]:
                _initialized_users.discard(cached)
            if user_dir.exists():
                import shutil
                shutil.rmtree(user_dir)
                dir_removed = True

        return {"user_uuid": user_uuid, "username": real_username, "counts": counts, "dir_removed": dir_removed}
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def get_all_users():
    """Returns list of usernames registered in Supabase PostgreSQL."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT username FROM user_profile ORDER BY username ASC;")
        users = [r["username"] for r in cursor.fetchall() if r.get("username")]
        cursor.close()
        return users
    except Exception as e:
        print(f"[database] Error in get_all_users: {e}")
        return []
    finally:
        if conn is not None:
            release_pooled_connection(conn)
