"""Which plan an account is on, and the one AI generation an account without a plan may spend.

Plans: "paid" (a subscription in good standing), "tester" (an unexpired tester grant, with no
paying subscription behind it) and "free" (everything else, including any account whose standing
cannot be read). Outside cloud mode there is nothing to meter, so every account counts as paid.

An account on the free plan may spend one AI generation, once, on one material. The claim lives
in free_video_claims (one row per account, so the primary key makes claiming atomic). The AI
chokepoint (ai.enforce_usage_limits) refuses every other AI call on a free account; the code that
processes the claimed material opens generation_scope() around its AI calls to let those through.
Anything that does not open a scope stays refused, which is the fail-closed direction.

Thresholds live in app_settings with tight in-code defaults, so a key missing from one database
blocks rather than permits. The address hash needs FREE_VIDEO_IP_SALT in the environment: without
it no claim can be made, because an unsalted hash of an address is just the address.
"""
import contextvars
import hashlib
import hmac
import logging
import os
from contextlib import contextmanager
from typing import Optional

from psycopg2.extras import RealDictCursor

from app import database
from app.config import IS_CLOUD, get_user_uuid_from_db

logger = logging.getLogger("studiamo")

PLAN_FREE = "free"
PLAN_PAID = "paid"
PLAN_TESTER = "tester"

CLAIM_OK = "claimed"
CLAIM_USED = "already_used"
CLAIM_IP_LIMIT = "ip_limit"
CLAIM_UNAVAILABLE = "unavailable"

# Deliberately tight: one claim per address in the window and no releases beyond the first.
# The real values are set in app_settings; these only apply where a key is missing.
_FALLBACK_IP_MAX = 1
_FALLBACK_IP_WINDOW_DAYS = 30
_FALLBACK_MAX_RELEASES = 1
# Free-plan storage, in MB. Tight on purpose; the real limits are set in app_settings.
_FALLBACK_FREE_QUOTA_MB = 25
_FALLBACK_FREE_MAX_FILE_MB = 5
_FALLBACK_FREE_MAX_LINKS = 50


def _setting_int(key: str, default: int) -> int:
    raw = database.get_app_setting(key, "")
    try:
        value = int(raw) if str(raw).strip() else default
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def get_plan(username: str) -> str:
    """The account's plan. Fails closed to "free" when the standing cannot be read."""
    if not IS_CLOUD:
        return PLAN_PAID
    try:
        row = database._fetch_access_row(username)
        has_access, _ = database._decide_access(row)
    except Exception as e:
        logger.warning(f"[plans] Could not read plan for '{username}', treating as free: {e}")
        return PLAN_FREE
    if not has_access:
        return PLAN_FREE
    subscribed = (row.get("subscription_status") or "").lower() in database._ACCESS_GRANTING_STATUSES
    tester = database._derive_tester_state(row)["state"] == "active"
    return PLAN_TESTER if (tester and not subscribed) else PLAN_PAID


def storage_limits(username: str) -> tuple:
    """(total bytes, per-file bytes) this account may store. Accounts on a plan get the normal
    limits from config; the free plan gets its own, from app_settings, with tight fallbacks.
    Existing data above a limit is never removed: the limit only refuses new uploads."""
    from app import config
    if get_plan(username) != PLAN_FREE:
        return config.get_user_storage_quota_bytes(), config.get_max_file_upload_bytes()
    mb = 1024 * 1024
    return (
        _setting_int("free_storage_quota_mb", _FALLBACK_FREE_QUOTA_MB) * mb,
        _setting_int("free_storage_max_file_mb", _FALLBACK_FREE_MAX_FILE_MB) * mb,
    )


def max_links(username: str) -> int:
    """How many link materials the account may keep. 0 means no limit, which is what an account
    on a plan gets. Existing links above a limit are kept; the limit only refuses new ones."""
    if get_plan(username) != PLAN_FREE:
        return 0
    return _setting_int("free_max_links", _FALLBACK_FREE_MAX_LINKS)


def hash_client_ip(ip: Optional[str]) -> Optional[str]:
    """Salted hash of a visitor address, or None when no hash can be made (no salt configured,
    or no address). Callers treat None as "no free generation", never as a match."""
    salt = os.getenv("FREE_VIDEO_IP_SALT", "")
    if not salt or not ip or not ip.strip():
        return None
    return hmac.new(salt.encode("utf-8"), ip.strip().encode("utf-8"), hashlib.sha256).hexdigest()


def _connect():
    return database.get_pooled_raw_connection()


def claim_free_video(user_uuid: str, ip_hash: Optional[str]) -> str:
    """Tries to spend the account's one free generation. Returns a CLAIM_* constant.

    CLAIM_UNAVAILABLE covers every case where the answer is unknown (no address hash, database
    error): the generation is not spent and nothing runs. The per-address count is checked
    before the insert and is not locked against a second parallel claim from the same address,
    which can overshoot the threshold by one. That is accepted: the threshold is a soft
    brake on mass signups, while the one-per-account rule below is exact."""
    if not ip_hash:
        return CLAIM_UNAVAILABLE
    max_per_ip = _setting_int("free_video_ip_max", _FALLBACK_IP_MAX)
    window_days = _setting_int("free_video_ip_window_days", _FALLBACK_IP_WINDOW_DAYS)
    max_releases = _setting_int("free_video_max_releases", _FALLBACK_MAX_RELEASES)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT COUNT(*) AS c FROM free_video_claims
                WHERE ip_hash = %s AND user_uuid <> %s
                  AND claimed_at > CURRENT_TIMESTAMP - make_interval(days => %s);""",
            (ip_hash, user_uuid, window_days),
        )
        if (cur.fetchone() or {}).get("c", 0) >= max_per_ip:
            return CLAIM_IP_LIMIT
        cur.execute(
            """INSERT INTO free_video_claims (user_uuid, ip_hash) VALUES (%s, %s)
               ON CONFLICT (user_uuid) DO UPDATE
                  SET active = TRUE, video_id = NULL, ip_hash = EXCLUDED.ip_hash,
                      claimed_at = CURRENT_TIMESTAMP
                WHERE free_video_claims.active = FALSE AND free_video_claims.releases <= %s
               RETURNING user_uuid;""",
            (user_uuid, ip_hash, max_releases),
        )
        return CLAIM_OK if cur.fetchone() else CLAIM_USED
    except Exception as e:
        logger.warning(f"[plans] Free generation claim failed for {user_uuid}: {e}")
        return CLAIM_UNAVAILABLE
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


def attach_free_video(user_uuid: str, video_id: int) -> None:
    """Records which material an active, still-unattached claim was spent on. A no-op for an
    account with no such claim (every account on a plan), so callers need not check the plan."""
    conn = None
    try:
        conn = _connect()
        conn.cursor().execute(
            "UPDATE free_video_claims SET video_id = %s WHERE user_uuid = %s AND active IS TRUE AND video_id IS NULL;",
            (video_id, user_uuid),
        )
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


def release_free_video(user_uuid: str, video_id: int) -> bool:
    """Gives the claim back after the import it was spent on failed, at most max_releases times.
    Returns whether it was released. A release beyond the cap leaves the claim spent."""
    max_releases = _setting_int("free_video_max_releases", _FALLBACK_MAX_RELEASES)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        # Not once the AI has already run: the generation was spent even if the import failed
        # afterwards (or the material was deleted while it was still processing). Only a failure
        # before any successful AI call since the claim, which cost nothing, gives it back.
        cur.execute(
            """UPDATE free_video_claims c
                  SET active = FALSE, video_id = NULL, releases = releases + 1
                WHERE c.user_uuid = %s AND c.active IS TRUE AND c.video_id = %s AND c.releases < %s
                  AND NOT EXISTS (
                      SELECT 1 FROM ai_usage_logs l
                       WHERE l.user_uuid = c.user_uuid::text AND l.status = 'success'
                         AND l.timestamp >= c.claimed_at
                  );""",
            (user_uuid, video_id, max_releases),
        )
        return cur.rowcount > 0
    except Exception as e:
        logger.warning(f"[plans] Could not release free generation for {user_uuid}: {e}")
        return False
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


def release_unattached_claim(user_uuid: str) -> bool:
    """Gives back a claim made for a request that ended without enqueuing an import (a duplicate,
    a validation error). Counts as a release, so it cannot be used to probe past the cap."""
    max_releases = _setting_int("free_video_max_releases", _FALLBACK_MAX_RELEASES)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """UPDATE free_video_claims SET active = FALSE, releases = releases + 1
                WHERE user_uuid = %s AND active IS TRUE AND video_id IS NULL AND releases < %s;""",
            (user_uuid, max_releases),
        )
        return cur.rowcount > 0
    except Exception as e:
        logger.warning(f"[plans] Could not release unattached claim for {user_uuid}: {e}")
        return False
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


def get_free_video_state(user_uuid: str) -> dict:
    """{"state": "available" | "used", "video_id": int | None} for the status endpoint."""
    max_releases = _setting_int("free_video_max_releases", _FALLBACK_MAX_RELEASES)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT video_id, active, releases FROM free_video_claims WHERE user_uuid = %s;",
            (user_uuid,),
        )
        row = cur.fetchone()
    except Exception as e:
        logger.warning(f"[plans] Could not read free generation state for {user_uuid}: {e}")
        return {"state": "used", "video_id": None}
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)
    if row is None:
        return {"state": "available", "video_id": None}
    if row["active"]:
        return {"state": "used", "video_id": row["video_id"]}
    return {"state": "available" if row["releases"] <= max_releases else "used", "video_id": None}


def prune_ip_hashes() -> int:
    """Clears address hashes older than the window. The claim itself stays for a live account (it
    is what marks the generation as spent); only the hash goes. Returns the number cleared."""
    window_days = _setting_int("free_video_ip_window_days", _FALLBACK_IP_WINDOW_DAYS)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """UPDATE free_video_claims SET ip_hash = NULL
                WHERE ip_hash IS NOT NULL
                  AND claimed_at < CURRENT_TIMESTAMP - make_interval(days => %s);""",
            (window_days,),
        )
        cleared = cur.rowcount
        # A claim kept from a deleted account (see database.delete_user_account) has nothing left
        # to say once its address hash is gone.
        cur.execute(
            """DELETE FROM free_video_claims c
                WHERE c.ip_hash IS NULL
                  AND NOT EXISTS (SELECT 1 FROM user_profile p WHERE p.user_uuid = c.user_uuid);"""
        )
        return cleared
    except Exception as e:
        logger.warning(f"[plans] Address hash pruning failed: {e}")
        return 0
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


# The account whose claimed material is being processed on this thread, if any.
_scope_user: contextvars.ContextVar = contextvars.ContextVar("free_generation_user", default=None)


def _reclaim_for_retry(user_uuid: str, video_id: int) -> bool:
    """Re-opens a released claim for a retry of an import. The address was checked when the claim
    was first made and releases are capped, so a retry needs no second address check. Only an
    account that already has a (released) claim row can do this; one that never claimed cannot."""
    max_releases = _setting_int("free_video_max_releases", _FALLBACK_MAX_RELEASES)
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """UPDATE free_video_claims
                  SET active = TRUE, video_id = %s, claimed_at = CURRENT_TIMESTAMP
                WHERE user_uuid = %s AND active IS FALSE AND releases <= %s;""",
            (video_id, user_uuid, max_releases),
        )
        return cur.rowcount > 0
    except Exception as e:
        logger.warning(f"[plans] Could not re-open free generation for {user_uuid}: {e}")
        return False
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


def _claim_matches(user_uuid: str, video_id: int) -> bool:
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM free_video_claims WHERE user_uuid = %s AND active IS TRUE AND video_id = %s;",
            (user_uuid, video_id),
        )
        return cur.fetchone() is not None
    except Exception as e:
        logger.warning(f"[plans] Could not verify free generation scope: {e}")
        return False
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)


@contextmanager
def generation_scope(username: str, video_id: Optional[int]):
    """Lets AI calls through the chokepoint for a free account, but only while it processes the
    material its free generation was claimed for. Yields whether the scope is open. For accounts
    on a plan it is a no-op: they pass the chokepoint anyway. A free account retrying an import
    whose claim was released gets the claim back here (see _reclaim_for_retry)."""
    user_uuid = get_user_uuid_from_db(username) if (IS_CLOUD and video_id is not None) else None
    allowed = bool(user_uuid) and (
        _claim_matches(str(user_uuid), int(video_id))
        or (get_plan(username) == PLAN_FREE and _reclaim_for_retry(str(user_uuid), int(video_id)))
    )
    token = _scope_user.set(str(user_uuid) if allowed else None)
    try:
        yield allowed
    finally:
        _scope_user.reset(token)


def scope_allows(username: str) -> bool:
    """Whether a generation_scope for this account is open on the current thread."""
    scoped = _scope_user.get()
    return bool(scoped) and scoped == str(get_user_uuid_from_db(username))


def may_generate_for(username: str, video_id: int) -> bool:
    """Whether an AI call for this material would get through the chokepoint, decided without
    changing anything: true for an account on a plan, or for a free account whose free generation
    is on this material (or released and available again). Routes use it to refuse before they
    write anything, instead of leaving a half-made row behind when the chokepoint says no."""
    if get_plan(username) != PLAN_FREE:
        return True
    user_uuid = get_user_uuid_from_db(username)
    if not user_uuid:
        return False
    if _claim_matches(str(user_uuid), int(video_id)):
        return True
    return get_free_video_state(str(user_uuid))["state"] == "available" and _has_released_row(str(user_uuid))


def _has_released_row(user_uuid: str) -> bool:
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM free_video_claims WHERE user_uuid = %s AND active IS FALSE;", (user_uuid,))
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)
