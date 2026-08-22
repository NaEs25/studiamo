"""
Database module for Studiamo, Supabase PostgreSQL Integration
Provides unified connection pool & parameter wrapping for clean execution across the app.
"""
import json
import os
import sys
import time
import logging
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("studiamo")

BASE_DIR = Path(__file__).resolve().parent.parent

_DB_URL = None
_pool = None
_schema_ensured = False
_initialized_users = set()

POOL_MIN_CONN = int(os.environ.get("SUPABASE_POOL_MIN_CONN", "4"))
POOL_MAX_CONN = int(os.environ.get("SUPABASE_POOL_MAX_CONN", "50"))

# How long a connection may sit unused in the pool before it is pinged on the way out, and
# how many dead ones a single borrow will discard before giving up. See
# _verify_pooled_connection for why the pool cannot be trusted to hand back a live socket.
POOL_IDLE_VERIFY_SECONDS = int(os.environ.get("SUPABASE_POOL_IDLE_VERIFY_SECONDS", "60"))
POOL_BORROW_ATTEMPTS = 3

# Monotonic timestamp of when each pooled connection was last released, keyed by id(). The
# pool holds a strong reference to every connection it owns, so an id stays unambiguous for
# as long as the entry is needed; entries are dropped as connections are borrowed or closed.
_pool_idle_since = {}

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

def _verify_pooled_connection(conn) -> bool:
    """Returns True if a connection borrowed from the pool can still reach the server.

    Supabase drops connections that sit idle, and psycopg2's pool has no liveness check of
    its own: it hands back whatever it is holding, so a socket the server closed minutes ago
    surfaces as `SSL SYSCALL error: EOF detected` inside whichever query happens to run next.

    Connections borrowed again quickly skip the check, so the hot path keeps its single round
    trip; only ones that sat idle long enough to plausibly have been reaped are pinged."""
    if conn.closed:
        return False
    idle_since = _pool_idle_since.get(id(conn))
    if idle_since is not None and (time.monotonic() - idle_since) < POOL_IDLE_VERIFY_SECONDS:
        return True
    try:
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        cursor.fetchone()
        cursor.close()
        return True
    except psycopg2.Error:
        return False


def get_pooled_raw_connection():
    """Borrows a live raw psycopg2 connection from the shared pool for admin/no-user-context queries.

    Dead connections are closed out of the pool rather than returned to it, so each retry gets
    a socket the pool has to open fresh. Bounded, because every attempt that finds a dead
    connection also removes one."""
    pool = _get_pool()
    conn = None
    for _ in range(POOL_BORROW_ATTEMPTS):
        conn = pool.getconn()
        # Verify before dropping the idle stamp: _verify_pooled_connection reads it to decide
        # whether this connection has been sitting long enough to be worth a ping.
        live = _verify_pooled_connection(conn)
        _pool_idle_since.pop(id(conn), None)
        if live:
            conn.autocommit = True
            return conn
        try:
            pool.putconn(conn, close=True)
        except Exception as e:
            logger.debug(f"[get_pooled_raw_connection] discarding a dead connection failed: {e}")
        conn = None
    # Every attempt came back dead, which points at the database being unreachable rather
    # than at stale sockets. Hand back a connection anyway and let the caller's query raise
    # the real driver error, that says far more than an exception invented here would.
    logger.warning(f"[get_pooled_raw_connection] No live connection after {POOL_BORROW_ATTEMPTS} attempts.")
    conn = pool.getconn()
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
        _pool_idle_since[id(raw_conn)] = time.monotonic()
        _get_pool().putconn(raw_conn)
    except Exception:
        _pool_idle_since.pop(id(raw_conn), None)
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

_UNSET = object()


def get_video_row(video_id: int, username: str) -> dict:
    """Returns one video row by primary key, or {} if the user does not own it.

    Replaces storage.get_video_json, which took a filename-shaped string ("<youtube_id>" or
    "doc_<video_id>") and matched it against two columns with an OR. That indirection is what
    let document rows silently miss, since their key matched neither column.
    """
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, user_uuid, youtube_id, title, category, thumbnail_url,
                      importance_rating, learning_goal_id, is_archived, is_paused, is_watchlist,
                      custom_notes, status, summary, outline, fact_check, created_at
                 FROM videos
                WHERE id = %s AND user_uuid = %s
                LIMIT 1;""",
            (video_id, conn.user_uuid)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return {}
    data = dict(row)
    created = data.get("created_at")
    if hasattr(created, "isoformat"):
        data["created_at"] = created.isoformat()
    return data


def save_video_analysis(video_id: int, username: str, summary=None, outline=None, fact_check=None) -> None:
    """Writes a video's AI analysis. Only the fields passed are touched.

    Replaces storage.save_video_json, which accepted a whole payload dict but persisted exactly
    three columns from it and ignored the rest, so callers could not tell what would survive.
    Several call sites passed status, is_temporary or expires_at and silently changed nothing.
    """
    sets, params = [], []
    if summary is not None:
        sets.append("summary = %s::jsonb")
        params.append(json.dumps(summary))
    if outline is not None:
        sets.append("outline = %s::jsonb")
        params.append(json.dumps(outline))
    if fact_check is not None:
        sets.append("fact_check = %s::jsonb")
        params.append(json.dumps(fact_check))
    if not sets:
        return

    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        params.extend([video_id, conn.user_uuid])
        cursor.execute(
            f"UPDATE videos SET {', '.join(sets)} WHERE id = %s AND user_uuid = %s;",
            tuple(params)
        )
        if cursor.rowcount == 0:
            logger.warning(f"save_video_analysis matched no video row for id {video_id} (user {username}).")
        conn.commit()
    finally:
        conn.close()


def get_quiz_row(quiz_id: int, username: str) -> dict:
    """Returns one quiz row by primary key, with questions_json decoded as `questions`."""
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, video_id, goal_id, quiz_type, srs_stage, next_review_at,
                      importance_level, in_progress_index, questions_json
                 FROM quizzes
                WHERE id = %s AND user_uuid = %s
                LIMIT 1;""",
            (quiz_id, conn.user_uuid)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return {}
    data = dict(row)
    questions = data.pop("questions_json", None) or []
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
        except (TypeError, ValueError):
            questions = []
    data["questions"] = questions if isinstance(questions, list) else []
    next_review = data.get("next_review_at")
    data["next_review_at"] = next_review.isoformat() if hasattr(next_review, "isoformat") else (
        str(next_review) if next_review else ""
    )
    return data


def update_quiz_progress(quiz_id: int, username: str, srs_stage=None, next_review_at=None,
                         in_progress_index=_UNSET) -> None:
    """Updates a quiz's SRS position. Only the arguments given are written.

    in_progress_index takes a sentinel rather than None as its default, because clearing it is
    a real instruction ("this session finished") and has to be distinguishable from "leave it
    alone". storage.save_quiz_json wrote it unconditionally from whatever the payload happened
    to contain, so a caller that only meant to bump next_review_at silently dropped a
    half-finished session's position.
    """
    sets, params = [], []
    if srs_stage is not None:
        sets.append("srs_stage = %s")
        params.append(srs_stage)
    if next_review_at is not None:
        sets.append("next_review_at = %s::timestamptz")
        params.append(next_review_at)
    if in_progress_index is not _UNSET:
        sets.append("in_progress_index = %s")
        params.append(in_progress_index)
    if not sets:
        return

    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        params.extend([quiz_id, conn.user_uuid])
        cursor.execute(
            f"UPDATE quizzes SET {', '.join(sets)} WHERE id = %s AND user_uuid = %s;",
            tuple(params)
        )
        conn.commit()
    finally:
        conn.close()


def save_quiz_concept_pool(quiz_id: int, concept_pool: list, username: str) -> None:
    """Persists a quiz's full multi-stage question pool.

    Deliberately a narrow, explicitly-keyed write rather than another field on
    storage.save_quiz_json: that function persists a hardcoded column list and silently drops
    anything else in the payload it is handed, which is why every stage above 0 was discarded
    for as long as it existed. Keying on the primary key means this cannot miss its row.
    """
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE quizzes SET concept_pool = %s::jsonb WHERE id = %s AND user_uuid = %s;",
            (json.dumps(concept_pool or []), quiz_id, conn.user_uuid)
        )
        conn.commit()
    finally:
        conn.close()


def save_quiz_active_questions(quiz_id: int, questions: list, username: str) -> None:
    """Materializes the questions a quiz is currently serving into questions_json.

    questions_json is the positional contract for the rest of the app: POST
    /api/quiz/verify-guess looks a question up by its index in this list, and
    quiz_attempts.question_index records answers against it. Once GET /api/quiz started
    drawing stage-appropriate questions from concept_pool, leaving questions_json holding the
    stage-0 set would mean verifying a typed guess against a different question than the one
    on screen. Writing back what was served keeps the two in step.

    Deliberately narrow: storage.save_quiz_json would also overwrite in_progress_index, which
    would drop a half-finished session.
    """
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE quizzes SET questions_json = %s::jsonb WHERE id = %s AND user_uuid = %s;",
            (json.dumps(questions or []), quiz_id, conn.user_uuid)
        )
        conn.commit()
    finally:
        conn.close()


def save_quiz_focus(quiz_id: int, focus_topics: dict, questions: list, username: str) -> None:
    """Stores a focus selection and the question list it produces, in one statement.

    The two belong together: focus_topics is what the user chose, questions_json is what that
    choice currently resolves to for the active stage. Writing them separately would leave a
    window where a quiz opened between the two reads a selection its questions do not match.
    in_progress_index is cleared because the position a half-finished session was holding
    refers to the previous list.
    """
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE quizzes
                  SET focus_topics = %s::jsonb,
                      questions_json = %s::jsonb,
                      in_progress_index = NULL
                WHERE id = %s AND user_uuid = %s;""",
            (json.dumps(focus_topics or {}), json.dumps(questions or []), quiz_id, conn.user_uuid)
        )
        conn.commit()
    finally:
        conn.close()


def get_quiz_pool_and_focus(quiz_id: int, username: str) -> tuple:
    """Returns (concept_pool, focus_topics) for a quiz, both already decoded from JSONB."""
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT concept_pool, focus_topics FROM quizzes WHERE id = %s AND user_uuid = %s LIMIT 1;",
            (quiz_id, conn.user_uuid)
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return [], {}

    pool = row.get("concept_pool") or []
    focus = row.get("focus_topics") or {}
    if isinstance(pool, str):
        try:
            pool = json.loads(pool)
        except (TypeError, ValueError):
            pool = []
    if isinstance(focus, str):
        try:
            focus = json.loads(focus)
        except (TypeError, ValueError):
            focus = {}
    return (pool if isinstance(pool, list) else []), (focus if isinstance(focus, dict) else {})


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


def find_user_by_google_identity(google_id: str, email: str):
    """Returns {"username", "user_uuid", "status", "referral_code"} for the account that owns a
    Google identity, or None.

    Deliberately matches only on identities an account has already proven belongs to it. Matching
    by bare username would let anyone claim an existing account just by registering a Google
    address whose local-part equals that username (alice@anydomain.com for the account "alice").

    The ordering is the point, not decoration. google_id is Google's stable subject id and is
    authoritative; google_email and email are weaker and can go stale when someone changes their
    Google address. An unordered LIMIT 1 lets Postgres pick either row whenever two accounts
    overlap on these columns, so the same person could land in a different account from one login
    to the next. Ranking makes the winner the same every time.
    """
    if not google_id and not email:
        return None
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT username, user_uuid, status, referral_code
              FROM user_profile
             WHERE (google_id IS NOT NULL AND google_id = %s)
                OR (google_email IS NOT NULL AND LOWER(google_email) = LOWER(%s))
                OR (email IS NOT NULL AND LOWER(email) = LOWER(%s))
             ORDER BY CASE
                        WHEN google_id IS NOT NULL AND google_id = %s THEN 0
                        WHEN google_email IS NOT NULL AND LOWER(google_email) = LOWER(%s) THEN 1
                        ELSE 2
                      END,
                      id
             LIMIT 1;
            """,
            (str(google_id), email, email, str(google_id), email)
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


def promote_user_to_active(user_uuid: str, conn=None) -> dict:
    """Promotes one specific account off the waitlist, regardless of queue position.

    Distinct from promote_next_n_users, which takes the front of the queue. This is a
    deliberate queue jump for a named account, which is what an admin looking at one person
    actually wants; the ordering rules do not apply and are not consulted.

    Returns {"username", "email", "google_email"} so the caller can send the promotion
    email, or None if nothing was promoted.

    The `AND status = 'waitlist'` is what makes this idempotent, and it is load-bearing
    rather than tidy: without it a second call would "succeed" on an already-active account
    and the caller would send a second "your spot is ready" email to someone who has been
    using the product for a week.

    `conn` lets a caller run this on a database other than the app's own. The admin cockpit
    administers production from inside a staging process, and every write belonging to one
    promotion has to land in the same place. A supplied connection is left open."""
    borrowed = conn is None
    try:
        conn = get_pooled_raw_connection() if borrowed else conn
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """UPDATE user_profile SET status = 'active'
                WHERE user_uuid = %s AND status = 'waitlist'
            RETURNING username, email, google_email;""",
            (user_uuid,)
        )
        row = cursor.fetchone()
        if borrowed and not getattr(conn, "autocommit", False):
            conn.commit()
        return row
    finally:
        if borrowed and conn is not None:
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


# --- Tester access -------------------------------------------------------------------
#
# Tester grants are time-boxed rows in `tester_access` (see app/schema.py). The *current*
# grant for a user is the newest row by granted_at, revoked or not: reading the newest row
# unconditionally, rather than the newest un-revoked one, is what makes "revoke" actually
# mean revoked even if an older un-revoked row is still lying around from a manual edit.
#
# period_days = 0 means "no end date" and is the only case where expires_at IS NULL. A CHECK
# constraint in schema.py enforces that pairing, so nothing here has to defend against a row
# where the two disagree.

# Fallbacks used only when the app_settings row is missing. Not business-sensitive numbers,
# unlike the AI budget ceilings in app.ai, so plain literals are fine here.
_TESTER_DEFAULT_PERIOD_DAYS = 14
_TESTER_MAX_PERIOD_DAYS = 90


def _as_utc(value):
    """Returns a tz-aware UTC datetime, or None.

    Every timestamp column involved is TIMESTAMPTZ, but a naive value can still arrive via a
    direct DB edit, and comparing naive to aware raises TypeError rather than returning a
    wrong answer. Normalise instead of trusting the column type."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _tester_days_left(expires_at):
    """Whole days from today until `expires_at`, by calendar date in UTC. None when unlimited.

    Calendar dates rather than 24-hour blocks: someone granted access at 23:50 should not
    read as "0 days left" ten minutes later. Clamped at 0, never negative."""
    expires_at = _as_utc(expires_at)
    if expires_at is None:
        return None
    return max(0, (expires_at.date() - datetime.now(timezone.utc).date()).days)


def get_tester_period_setting(key: str, fallback: int) -> int:
    """Reads one of the tester period settings from app_settings, falling back on anything
    missing or unparseable rather than raising into a request."""
    try:
        raw = get_app_setting(key, "")
        return int(raw) if str(raw).strip() else fallback
    except (TypeError, ValueError):
        logger.warning(f"[tester] app_settings['{key}'] is not an integer; using {fallback}.")
        return fallback


# Selects the profile row and its current tester grant in one indexed round trip.
# has_app_access() runs on every guarded request, so this deliberately stays a single query.
_TESTER_ACCESS_SQL = """
    SELECT p.user_uuid, p.subscription_status, p.is_tester, p.ls_ends_at,
           p.ls_renews_at, p.ls_customer_portal_url,
           t.id AS grant_id, t.granted_at, t.expires_at, t.period_days, t.revoked_at,
           t.welcome_seen_at, t.reminder_7d_seen_at, t.reminder_1d_seen_at, t.expiry_seen_at
      FROM user_profile p
      LEFT JOIN LATERAL (
           SELECT id, granted_at, expires_at, period_days, revoked_at,
                  welcome_seen_at, reminder_7d_seen_at, reminder_1d_seen_at, expiry_seen_at
             FROM tester_access
            WHERE user_uuid = p.user_uuid
            ORDER BY granted_at DESC, id DESC
            LIMIT 1
      ) t ON TRUE
     WHERE LOWER(p.username) = LOWER(%s)
     LIMIT 1;
"""


def _derive_tester_state(row) -> dict:
    """Turns a _TESTER_ACCESS_SQL row into the derived tester state. Pure, no I/O."""
    empty = {
        "state": "none", "granted_at": None, "expires_at": None, "period_days": None,
        "days_left": None, "unlimited": False, "legacy": False, "grant_id": None,
        "needs_welcome": False, "needs_reminder": None,
    }
    if not row:
        return empty

    grant_id = row.get("grant_id")

    # No grant row at all, but the flag is set: a tester from before grants were time-boxed.
    # Grandfathered on purpose so deploying this could not cut anyone off; scripts/
    # backfill_tester_access.py is what makes these explicit, as a deliberate step.
    if grant_id is None:
        if row.get("is_tester"):
            return {**empty, "state": "active", "legacy": True}
        return empty

    granted_at = _as_utc(row.get("granted_at"))
    expires_at = _as_utc(row.get("expires_at"))
    period_days = row.get("period_days")
    unlimited = expires_at is None
    days_left = _tester_days_left(expires_at)

    base = {
        "granted_at": granted_at, "expires_at": expires_at, "period_days": period_days,
        "days_left": days_left, "unlimited": unlimited, "legacy": False, "grant_id": grant_id,
        "needs_welcome": False, "needs_reminder": None,
    }

    if row.get("revoked_at") is not None:
        return {**base, "state": "revoked"}

    if not unlimited and datetime.now(timezone.utc) >= expires_at:
        return {**base, "state": "expired"}

    # Active from here down, either unlimited or still inside the period.
    state = {**base, "state": "active"}
    state["needs_welcome"] = row.get("welcome_seen_at") is None

    # Thresholds live here and nowhere else, so the modals and any future emails cannot
    # disagree about when "one week left" starts. The None check must come first: with an
    # unlimited grant days_left is None, and `None <= 7` raises in Python.
    if days_left is not None:
        if days_left <= 1 and row.get("reminder_1d_seen_at") is None:
            state["needs_reminder"] = "1d"
        elif days_left <= 7 and row.get("reminder_7d_seen_at") is None:
            state["needs_reminder"] = "7d"
    return state


def get_tester_state(username: str) -> dict:
    """Current tester standing for one account, derived from tester_access.

    Returns a dict with:
        state:        'none' | 'active' | 'expired' | 'revoked'
        expires_at:   datetime | None   (None when unlimited, or when legacy)
        granted_at:   datetime | None
        period_days:  int | None        (0 when unlimited)
        days_left:    int | None        (0 on the last day, never negative,
                                         None when unlimited or legacy)
        unlimited:    bool              (a real grant row with period_days = 0)
        legacy:       bool              (is_tester set, but no grant row exists)
        grant_id:     int | None
        needs_welcome / needs_reminder: see _derive_tester_state

    `unlimited` and `legacy` both mean "active with no end date", but they are not the same
    thing: one is a decision, the other is unmigrated history that still needs attention.
    Callers must not collapse them."""
    return _derive_tester_state(_fetch_access_row(username))


def tester_state_payload(state: dict) -> dict:
    """JSON-safe form of get_tester_state(), for API responses.

    Lives here rather than in each router so /api/billing/status and /api/settings cannot
    drift into returning different shapes for the same thing."""
    return {
        "state": state["state"],
        "granted_at": state["granted_at"].isoformat() if state["granted_at"] else None,
        "expires_at": state["expires_at"].isoformat() if state["expires_at"] else None,
        "period_days": state["period_days"],
        "days_left": state["days_left"],
        "unlimited": state["unlimited"],
        "legacy": state["legacy"],
        "needs_welcome": state["needs_welcome"],
        "needs_reminder": state["needs_reminder"],
    }


def _expire_tester_cache(user_uuid) -> None:
    """Flips user_profile.is_tester to FALSE once the grant behind it has run out.

    user_profile.is_tester is a cache of "there is a valid grant here" (app.ai reads it on a
    hot path for the per-account AI budget); tester_access is the source of truth. This is
    what keeps the two from disagreeing after an expiry, without a scheduled job.

    Writing on a read path is normally worth avoiding. It is justified here because the
    UPDATE is guarded on is_tester still being TRUE, so it touches rows exactly once per
    account per grant and is a no-op on every later call."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE user_profile SET is_tester = FALSE WHERE user_uuid = %s AND is_tester IS TRUE;",
            (user_uuid,)
        )
    except Exception as e:
        # Never let cache maintenance turn an access check into a 500. The access decision
        # itself does not depend on this having succeeded.
        logger.warning(f"[tester] Could not clear is_tester for {user_uuid}: {e}")
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def _decide_access(row) -> tuple:
    """Access decision for one _TESTER_ACCESS_SQL row. Pure, no I/O.

    Returns (has_access, cache_is_stale). The second flag says the account's is_tester
    cache outlived the grant behind it, which the caller heals; it is reported rather than
    acted on here so this stays a pure function that can be tested exhaustively."""
    if not row:
        return False, False

    grant_id = row["grant_id"]
    expires_at = _as_utc(row["expires_at"])
    revoked = row["revoked_at"] is not None
    cache_is_stale = False

    # grant_id, not expires_at, is what separates these two branches. The LEFT JOIN yields
    # expires_at = NULL both for an unlimited grant and for no grant at all, so testing
    # expires_at alone would grandfather every account that ever had the flag set and make
    # the expiry check below unreachable.
    if grant_id is not None and not revoked:
        if expires_at is None:
            return True, False                                # unlimited grant
        if datetime.now(timezone.utc) < expires_at:
            return True, False                                # still inside the period
        cache_is_stale = bool(row["is_tester"])
    elif grant_id is None and row["is_tester"]:
        return True, False                                    # legacy flag, grandfathered

    # Falls through on purpose: a tester whose grant ended may since have subscribed, and
    # must keep access through the normal path below.
    status = (row["subscription_status"] or "").lower()
    if status in _ACCESS_GRANTING_STATUSES:
        return True, cache_is_stale

    if status == "cancelled" and row["ls_ends_at"]:
        return _as_utc(row["ls_ends_at"]) > datetime.now(timezone.utc), cache_is_stale

    return False, cache_is_stale


def _fetch_access_row(username: str):
    """One indexed round trip for everything the access decision and the tester state need."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(_TESTER_ACCESS_SQL, (username,))
        return cursor.fetchone()
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def has_app_access(username: str) -> bool:
    """Whether this account may use the cloud app: a subscription in good standing, or a
    tester grant that has not run out.

    'cancelled' is handled separately and deliberately. In Lemon Squeezy it means "will not
    renew", NOT "access ends now", the customer has paid through the end of the current
    period and keeps access until ls_ends_at. Treating it as an immediate revocation would
    cut off people who have already paid for the month they are in.

    Returns False for statuses that genuinely end access ('paused', 'unpaid', 'expired',
    'inactive') and for any username with no profile row."""
    row = _fetch_access_row(username)
    has_access, cache_is_stale = _decide_access(row)
    if cache_is_stale:
        _expire_tester_cache(row["user_uuid"])
    return has_access


def get_access_snapshot(username: str) -> dict:
    """Access decision, tester state and the Lemon Squeezy display fields, in one query.

    /api/billing/status is called on every page load. Calling has_app_access() and
    get_tester_state() separately alongside the route's own profile lookup made that three
    round trips for data that all lives on one row, so the route uses this instead."""
    row = _fetch_access_row(username)
    has_access, cache_is_stale = _decide_access(row)
    if cache_is_stale:
        _expire_tester_cache(row["user_uuid"])
    return {
        "has_access": has_access,
        "tester": _derive_tester_state(row),
        "profile": row or {},
    }



def record_tester_feedback(username: str, message: str) -> bool:
    """Stores what a tester said on their way out. Returns True if it was saved.

    Attached to the grant it belongs to, so a second test period for the same person
    collects its own answer instead of being confused with the first. Trimmed and length
    capped, and an empty message is not stored at all: a blank row is worse than no row,
    because it looks like an answer when read back in a list."""
    message = (message or "").strip()
    if not message:
        return False
    message = message[:4000]

    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """INSERT INTO tester_feedback (user_uuid, username, grant_id, message)
               SELECT p.user_uuid, p.username,
                      (SELECT t.id FROM tester_access t
                        WHERE t.user_uuid = p.user_uuid
                        ORDER BY t.granted_at DESC, t.id DESC LIMIT 1),
                      %s
                 FROM user_profile p
                WHERE LOWER(p.username) = LOWER(%s)
            RETURNING id;""",
            (message, username)
        )
        return cursor.fetchone() is not None
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def mark_tester_converted(user_uuid) -> bool:
    """Stamps converted_at on a tester grant whose owner has started paying.

    Called from the Lemon Squeezy webhook. Answers the only question a test phase really
    has to answer: of the people who tried it, how many stayed.

    Only ever stamps the newest grant, only once, and only for an account that actually had
    one. `converted_at IS NULL` makes a renewal event a no-op rather than moving the date
    forward every month, which would otherwise turn "when did they convert" into "when did
    they last pay"."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """UPDATE tester_access SET converted_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM tester_access WHERE user_uuid = %s
                     ORDER BY granted_at DESC, id DESC LIMIT 1
                ) AND converted_at IS NULL
            RETURNING id;""",
            (user_uuid,)
        )
        return cursor.fetchone() is not None
    except Exception as e:
        # Conversion bookkeeping must never fail a webhook. Lemon Squeezy retries anything
        # it does not get a 200 for, and losing a subscription update to protect a
        # statistic would be the wrong trade.
        logger.warning(f"[tester] Could not stamp converted_at for {user_uuid}: {e}")
        return False
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def get_tester_conversion_stats() -> dict:
    """Headline numbers for the test programme: grants made, how many converted, and how
    many are still running. Counts grants rather than accounts, so a second period for the
    same person is a second attempt."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT COUNT(*) AS grants,
                   COUNT(*) FILTER (WHERE converted_at IS NOT NULL) AS converted,
                   COUNT(*) FILTER (WHERE revoked_at IS NULL
                                    AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP))
                       AS still_running
              FROM tester_access;
        """)
        row = dict(cursor.fetchone())
        finished = row["grants"] - row["still_running"]
        row["finished"] = finished
        # Rate over finished periods, not over every grant ever made: someone still inside
        # their two weeks has not decided anything yet, and counting them as a non-converter
        # understates the number for as long as the cohort is running.
        row["conversion_rate"] = round(row["converted"] / finished * 100, 1) if finished else None
        return row
    finally:
        if conn is not None:
            release_pooled_connection(conn)


def _resolve_user(cursor, username: str):
    """Returns (user_uuid, real_username) for a username, or (None, None)."""
    cursor.execute(
        "SELECT user_uuid, username FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
        (username,)
    )
    row = cursor.fetchone()
    return (row["user_uuid"], row["username"]) if row else (None, None)


def _clamp_period_days(days: int) -> int:
    """Validates a requested grant length.

    0 is passed through untouched: it means "no end date" and must survive. The obvious
    max(1, min(days, cap)) would turn an intentional unlimited grant into a one-day one,
    which is the opposite of what was asked for."""
    days = int(days)
    if days < 0:
        raise ValueError("Tester period cannot be negative. Use 0 for an unlimited grant.")
    if days == 0:
        return 0
    cap = get_tester_period_setting("tester_max_period_days", _TESTER_MAX_PERIOD_DAYS)
    return max(1, min(days, cap))


def _tester_write(username: str, action):
    """Runs `action(cursor, user_uuid, real_username)` as one transaction.

    Every tester write touches two tables (tester_access and the user_profile.is_tester
    cache), and a half-applied write is worse than a failed one: setting is_tester without
    inserting the grant row would produce a phantom unlimited tester via the legacy branch
    in has_app_access.

    autocommit is explicitly restored afterwards. Pooled connections are handed back with
    session state intact, so leaving one in manual-commit mode would silently swallow the
    next caller's writes."""
    conn = None
    try:
        conn = get_pooled_raw_connection()
        conn.autocommit = False
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        user_uuid, real_username = _resolve_user(cursor, username)
        if user_uuid is None:
            raise ValueError(f"No user_profile row found for username '{username}'.")
        result = action(cursor, user_uuid, real_username)
        conn.commit()
        return result
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.autocommit = True
            release_pooled_connection(conn)


def grant_tester_access(username: str, days: int = None, granted_by: str = None,
                        note: str = None) -> dict:
    """Starts a tester period for one account. `days=0` grants unlimited access.

    Any grant already on the account is superseded (revoked) in the same transaction, so
    "the newest row wins" can never be ambiguous. Returns the resulting get_tester_state()."""
    if days is None:
        days = get_tester_period_setting("tester_default_period_days", _TESTER_DEFAULT_PERIOD_DAYS)
    period_days = _clamp_period_days(days)

    def _action(cursor, user_uuid, real_username):
        cursor.execute(
            """UPDATE tester_access SET revoked_at = CURRENT_TIMESTAMP,
                      revoked_reason = 'superseded'
                WHERE user_uuid = %s AND revoked_at IS NULL;""",
            (user_uuid,)
        )
        expires_at = None if period_days == 0 else datetime.now(timezone.utc) + timedelta(days=period_days)
        cursor.execute(
            """INSERT INTO tester_access
                   (user_uuid, username, expires_at, period_days, granted_by, note)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;""",
            (user_uuid, real_username, expires_at, period_days, granted_by, note)
        )
        cursor.execute(
            "UPDATE user_profile SET is_tester = TRUE WHERE user_uuid = %s;", (user_uuid,)
        )
        return real_username

    real_username = _tester_write(username, _action)
    return get_tester_state(real_username)


def extend_tester_access(username: str, extra_days: int, extended_by: str = None) -> dict:
    """Adds days to the current grant. Returns the resulting get_tester_state().

    Refuses an unlimited grant rather than treating it as a no-op: `NULL + interval` is
    NULL, so the UPDATE would leave the row unlimited while still incrementing
    extended_count, and every admin surface would report an extension that never happened."""
    extra_days = int(extra_days)
    if extra_days <= 0:
        raise ValueError("Extension must be a positive number of days.")

    def _action(cursor, user_uuid, real_username):
        cursor.execute(
            """SELECT id, expires_at FROM tester_access
                WHERE user_uuid = %s AND revoked_at IS NULL
                ORDER BY granted_at DESC, id DESC LIMIT 1;""",
            (user_uuid,)
        )
        grant = cursor.fetchone()
        if grant is None:
            raise ValueError(f"'{real_username}' has no active tester grant to extend.")
        if grant["expires_at"] is None:
            raise ValueError(
                f"'{real_username}' has a tester grant with no end date; there is nothing to "
                "extend. Grant a new timed period instead if it should now expire."
            )
        # GREATEST, because extending an already-expired grant by 7 days must mean 7 days
        # from today, not 7 days from a date in the past (which would change nothing).
        cursor.execute(
            """UPDATE tester_access
                  SET expires_at = GREATEST(expires_at, CURRENT_TIMESTAMP) + (%s * INTERVAL '1 day'),
                      period_days = period_days + %s,
                      extended_count = extended_count + 1,
                      last_extended_at = CURRENT_TIMESTAMP
                WHERE id = %s;""",
            (extra_days, extra_days, grant["id"])
        )
        # The self-heal in has_app_access may already have cleared this if the grant had
        # lapsed, so an extension has to put it back rather than assume it is still set.
        cursor.execute(
            "UPDATE user_profile SET is_tester = TRUE WHERE user_uuid = %s;", (user_uuid,)
        )
        return real_username

    real_username = _tester_write(username, _action)
    return get_tester_state(real_username)


def end_tester_access(username: str, reason: str = None) -> dict:
    """Ends the current tester period immediately. Idempotent: ending an account that has no
    active grant is a no-op, not an error. Returns the resulting get_tester_state()."""
    def _action(cursor, user_uuid, real_username):
        cursor.execute(
            """UPDATE tester_access SET revoked_at = CURRENT_TIMESTAMP, revoked_reason = %s
                WHERE user_uuid = %s AND revoked_at IS NULL;""",
            (reason or "ended by admin", user_uuid)
        )
        cursor.execute(
            "UPDATE user_profile SET is_tester = FALSE WHERE user_uuid = %s;", (user_uuid,)
        )
        return real_username

    real_username = _tester_write(username, _action)
    return get_tester_state(real_username)


def mark_tester_notice_seen(username: str, kind: str) -> bool:
    """Records that a tester notice was shown, so it is not shown again.

    `kind` is one of 'welcome', 'reminder_7d', 'reminder_1d', 'expiry'. Returns True if a
    row was updated. Writes to the newest grant regardless of whether it has been revoked or
    has run out, because the expiry notice is shown precisely when the grant is over."""
    columns = {
        "welcome": "welcome_seen_at",
        "reminder_7d": "reminder_7d_seen_at",
        "reminder_1d": "reminder_1d_seen_at",
        "expiry": "expiry_seen_at",
    }
    column = columns.get(kind)
    if column is None:
        raise ValueError(f"Unknown tester notice kind '{kind}'.")

    conn = None
    try:
        conn = get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Column name is interpolated, never the value: it comes from the dict above, so it
        # cannot be caller-controlled text.
        cursor.execute(
            f"""UPDATE tester_access SET {column} = CURRENT_TIMESTAMP
                 WHERE id = (
                     SELECT t.id FROM tester_access t
                       JOIN user_profile p ON p.user_uuid = t.user_uuid
                      WHERE LOWER(p.username) = LOWER(%s)
                      ORDER BY t.granted_at DESC, t.id DESC LIMIT 1
                 ) AND {column} IS NULL
             RETURNING id;""",
            (username,)
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
    "tester_access",
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
