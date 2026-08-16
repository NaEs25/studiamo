import os
import hmac
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeSerializer, BadSignature

from slowapi import Limiter
from slowapi.util import get_remote_address

from app import config, database

logger = logging.getLogger("studiamo")

# Rate limiter setup
limiter = Limiter(key_func=get_remote_address, default_limits=["600/minute"])


def hash_password(password: str) -> str:
    """Bcrypt-hashes a password for storage in PASSWORD_HASH. Bcrypt ignores
    bytes past 72, so truncate first rather than let it silently drop the tail."""
    password_bytes = password.strip().encode("utf-8")[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> tuple[bool, Optional[str]]:
    """Checks `password` against `stored_hash`, returning (is_valid, upgraded_hash).

    Accepts both current bcrypt hashes and legacy unsalted-SHA-256 hashes from
    before this was bcrypt (identifiable by bcrypt's `$2` prefix vs. a bare hex
    digest). On a successful legacy match, upgraded_hash is a freshly bcrypt-hashed
    replacement the caller should persist over PASSWORD_HASH so the account stops
    depending on the weaker scheme after its next login."""
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        password_bytes = password.strip().encode("utf-8")[:72]
        try:
            is_valid = bcrypt.checkpw(password_bytes, stored_hash.encode("utf-8"))
        except ValueError:
            is_valid = False
        return is_valid, None

    legacy_hash = hashlib.sha256(password.strip().encode("utf-8")).hexdigest()
    if hmac.compare_digest(legacy_hash, stored_hash):
        return True, hash_password(password)
    return False, None

# --- HMAC & Session Security Setup ---
SECRET_KEY = os.environ.get("YB_SECRET_KEY")
if not SECRET_KEY:
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        try:
            with open(_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("YB_SECRET_KEY="):
                        SECRET_KEY = line.split("=", 1)[1].strip().strip("'\"")
                        break
        except Exception as e:
            logger.warning(f"[dependencies] Failed to manually parse .env for YB_SECRET_KEY: {e}")
if not SECRET_KEY:
    if config.IS_CLOUD:
        # A per-process random key would silently invalidate every session on
        # restart, and a multi-worker deployment without a shared key would have
        # workers signing with different keys, causing random auth failures.
        raise RuntimeError(
            "YB_SECRET_KEY must be set when APP_MODE=cloud. A random per-process "
            "key is never correct in a production/multi-worker deployment."
        )
    import secrets
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("⚠️ YB_SECRET_KEY environment variable is not set. Generated a temporary process key.")

_signer = URLSafeSerializer(SECRET_KEY, salt="yb-session-v1")


def _make_session_token(user_uuid: str) -> str:
    """Returns a signed session token naming the given user_uuid.

    The token deliberately carries the immutable user_uuid, not the (mutable)
    username: a signed token can't be edited in place, so anchoring it to
    something that can be renamed (see routers/settings.py's username-change
    path) means the token silently stops resolving to anyone the moment a
    rename happens. Every caller must pass a real user_uuid here, resolving
    one first (e.g. via config.get_user_uuid_from_db()) if it isn't already
    on hand."""
    return _signer.dumps(user_uuid)


def _decode_session_token(token: str) -> Optional[str]:
    """Decodes and verifies a signed session token. Returns the user_uuid it
    names, or None."""
    try:
        return _signer.loads(token)
    except BadSignature:
        return None


_oauth_state_signer = URLSafeSerializer(SECRET_KEY, salt="yb-oauth-state-v1")


def _sign_oauth_state(dest_path: str, ref_code: str, require_existing: bool) -> str:
    """Returns a signed, tamper-proof state string for Google OAuth 2.0 requests."""
    import time
    payload = {
        "d": dest_path or "/",
        "r": ref_code or "",
        "e": 1 if require_existing else 0,
        "t": int(time.time()),
    }
    return _oauth_state_signer.dumps(payload)


def _decode_oauth_state(state_str: Optional[str]) -> tuple[str, str, bool]:
    """Decodes and validates a signed OAuth state token, rejecting expired (>15 min) or forged states.
    Falls back gracefully to legacy plain string format if needed for backward compatibility."""
    import time
    if not state_str:
        return "/", "", False
    try:
        data = _oauth_state_signer.loads(state_str)
        issued_at = data.get("t", 0)
        if time.time() - issued_at > 900:
            logger.warning("[google_oauth] OAuth state parameter expired (>15 minutes old).")
            return "/", "", False
        dest_path = str(data.get("d", "/")).strip()
        dest_path = dest_path if dest_path.startswith("/") else "/"
        ref_code = str(data.get("r", "")).strip()
        require_existing = bool(data.get("e", 0))
        return dest_path, ref_code, require_existing
    except (BadSignature, Exception):
        if "|" in state_str:
            raw_dest, _, raw_rest = state_str.partition("|")
            raw_ref, _, raw_require_existing = raw_rest.partition("|")
            dest_path = raw_dest.strip() if raw_dest.strip().startswith("/") else "/"
            ref_code = raw_ref.strip()
            require_existing = raw_require_existing.strip() == "1"
            return dest_path, ref_code, require_existing
        logger.warning(f"[google_oauth] Invalid or tampered OAuth state parameter: {state_str}")
        return "/", "", False



def get_authenticated_username(request: Request) -> Optional[str]:
    """Validates the HMAC-signed session token (yb_session) and returns the
    CURRENT username for the identity it names, or None.

    The token names a user_uuid (see _make_session_token), so this resolves
    the display username fresh on every request instead of trusting a copy
    embedded at mint time, that resolution is what makes a username change
    safe to make while already logged in."""
    raw_token = request.cookies.get("yb_session")

    user_uuid: Optional[str] = None
    if raw_token:
        user_uuid = _decode_session_token(raw_token)

    if not user_uuid or not config.looks_like_uuid(user_uuid):
        return None

    username = config.get_username_from_uuid(user_uuid)

    if not username or username == "default_user":
        return None

    return username


def get_active_username(request: Request) -> str:
    """Dependency resolver: validates the HMAC-signed session token (yb_session)
    and returns the verified username. Raises 401 if unauthenticated.

    Does NOT check user_profile.status here on every request, a waitlist
    account never gets a session cookie in the first place (see
    google_callback in routers/auth.py), so a valid signed token already
    implies status was 'active' at session-issuance time. There's no
    demotion path today, so that guarantee can't go stale."""
    username = get_authenticated_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in.")

    database.ensure_user_initialized(username)
    return username


def require_app_access(request: Request) -> str:
    """Dependency guard: the paid-access gate for cloud mode.

    Returns the verified username, so routes can depend on this *instead of*
    get_active_username rather than in addition to it.

    Raises 402 Payment Required, deliberately not 403, so the frontend can tell "you need
    to pay" apart from "you need to log in" (401) and act accordingly. The paywall modal in
    billing.js is only the explanation; this is the actual enforcement, because a modal is
    a DOM node any user can delete.

    No-op outside cloud mode: self-hosted users bring their own Gemini key and pay Google
    directly, so there is nothing to charge them for. Accounts with user_profile.is_tester
    bypass it (see database.has_app_access)."""
    username = get_active_username(request)
    if not config.IS_CLOUD:
        return username
    if not database.has_app_access(username):
        raise HTTPException(
            status_code=402,
            detail="An active Studiamo Cloud subscription is required to use this feature.",
        )
    return username


def require_local_auth_enabled() -> None:
    """Dependency guard: blocks local username+password signup/login endpoints
    when running in cloud mode, where Google SSO is the only supported login.
    Self-hosted deployments are unaffected."""
    if config.IS_CLOUD:
        raise HTTPException(
            status_code=403,
            detail="Local username/password login is disabled for this deployment. Please sign in with Google.",
        )


# --- Bug tracker admin gate ---
# A separate signed cookie, not the yb_session/_signer above: this gates a single
# shared secret (see scripts/set_admin_bug_password.py), not a per-user account, so
# it deliberately can't be confused with or decoded as a real user session token.
_admin_signer = URLSafeSerializer(SECRET_KEY, salt="bugs-admin-v1")
ADMIN_COOKIE_NAME = "bugs_admin"


def make_admin_token() -> str:
    """Returns a signed token proving the bug-tracker admin password was entered."""
    return _admin_signer.dumps("bugs-admin")


def is_bugs_admin(request: Request) -> bool:
    """Non-raising check for the bugs_admin cookie. Used by the public bug-list
    endpoint to decide whether to include usernames/context in the response."""
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not token:
        return False
    try:
        return _admin_signer.loads(token) == "bugs-admin"
    except BadSignature:
        return False


def require_admin_auth(request: Request) -> None:
    """Dependency guard: blocks bug-tracker edit/delete endpoints unless the
    bugs_admin cookie is present and valid."""
    if not is_bugs_admin(request):
        raise HTTPException(status_code=403, detail="Admin login required.")


def get_srs_multipliers(username: str) -> dict:
    """Returns SRS interval multipliers based on user configuration."""
    user_config = config.load_user_config(username)
    return {
        5: float(user_config.get("SRS_MULTIPLIER_5") if user_config.get("SRS_MULTIPLIER_5") is not None else user_config.get("srs_mult_5", 0.7)),
        4: float(user_config.get("SRS_MULTIPLIER_4") if user_config.get("SRS_MULTIPLIER_4") is not None else user_config.get("srs_mult_4", 1.0)),
        3: float(user_config.get("SRS_MULTIPLIER_3") if user_config.get("SRS_MULTIPLIER_3") is not None else user_config.get("srs_mult_3", 1.5)),
        2: float(user_config.get("SRS_MULTIPLIER_2") if user_config.get("SRS_MULTIPLIER_2") is not None else user_config.get("srs_mult_2", 2.5)),
        1: float(user_config.get("SRS_MULTIPLIER_1") if user_config.get("SRS_MULTIPLIER_1") is not None else user_config.get("srs_mult_1", 4.0))
    }


def adjust_next_review(next_review: datetime, pref_hour: int) -> datetime:
    """Adjusts next review datetime to user's preferred review hour."""
    if pref_hour == -1:
        return next_review
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    now_local = datetime.now()
    utc_offset = now_local - now_utc
    next_review_local = next_review + utc_offset
    adjusted_local = next_review_local.replace(hour=pref_hour, minute=0, second=0, microsecond=0)
    if adjusted_local <= now_local:
        adjusted_local += timedelta(days=1)
    return adjusted_local - utc_offset


def get_question_counts(user_config: dict) -> dict:
    """Returns question counts per importance rating, strictly capped at 15 max per rating level."""
    raw = {
        1: int(user_config.get("QUESTION_COUNT_1") if user_config.get("QUESTION_COUNT_1") is not None else user_config.get("question_count_1", 2)),
        2: int(user_config.get("QUESTION_COUNT_2") if user_config.get("QUESTION_COUNT_2") is not None else user_config.get("question_count_2", 3)),
        3: int(user_config.get("QUESTION_COUNT_3") if user_config.get("QUESTION_COUNT_3") is not None else user_config.get("question_count_3", 5)),
        4: int(user_config.get("QUESTION_COUNT_4") if user_config.get("QUESTION_COUNT_4") is not None else user_config.get("question_count_4", 8)),
        5: int(user_config.get("QUESTION_COUNT_5") if user_config.get("QUESTION_COUNT_5") is not None else user_config.get("question_count_5", 12))
    }
    return {k: min(15, max(1, v)) for k, v in raw.items()}


def get_srs_intervals(cursor, user_uuid: Optional[str] = None) -> list:
    """Fetches SRS stage day intervals from database for user or defaults."""
    from app.config import DEFAULT_SRS_INTERVALS
    if user_uuid:
        cursor.execute("SELECT stage_1_days, stage_2_days, stage_3_days, stage_4_days, stage_5_days FROM srs_settings WHERE user_uuid = %s;", (user_uuid,))
        row = cursor.fetchone()
        if row:
            if isinstance(row, dict):
                return [
                    row.get("stage_1_days", DEFAULT_SRS_INTERVALS[0]),
                    row.get("stage_2_days", DEFAULT_SRS_INTERVALS[1]),
                    row.get("stage_3_days", DEFAULT_SRS_INTERVALS[2]),
                    row.get("stage_4_days", DEFAULT_SRS_INTERVALS[3]),
                    row.get("stage_5_days", DEFAULT_SRS_INTERVALS[4]),
                ]
            return [row[0], row[1], row[2], row[3], row[4]]
    return DEFAULT_SRS_INTERVALS


def get_preferred_hour(cursor, user_uuid: Optional[str] = None) -> int:
    """Fetches the user's preferred review-reminder hour (0-23), or -1 if unset.

    Was duplicated seven times across import_manager.py, routers/videos.py and
    routers/goals.py, each copy silently swallowing lookup failures with a bare
    `except: pass`, a broken lookup for one user was invisible everywhere it
    happened. Consolidated here so a failure is logged exactly once, in one
    place, no matter which caller triggered it.

    Best-effort by design: any failure here should not block scheduling a
    review, so it falls back to -1 (no preferred-hour adjustment) rather than
    raising."""
    if not user_uuid:
        return -1
    try:
        cursor.execute("SELECT preferred_hour FROM user_profile WHERE user_uuid = %s LIMIT 1;", (user_uuid,))
        row = cursor.fetchone()
        return int(row.get("preferred_hour") or -1) if row else -1
    except Exception as e:
        logger.warning(f"[get_preferred_hour] lookup failed for user_uuid={user_uuid}: {e}")
        return -1


def parse_bool(val) -> bool:
    """Safely converts various truthy representations into boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.lower() in ("true", "1", "t", "yes", "on")
    return False



