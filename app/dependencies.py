import os
import hmac
import logging
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import Request, HTTPException
from itsdangerous import URLSafeSerializer, BadSignature

from slowapi import Limiter
from slowapi.util import get_remote_address

from app import config, database, local_days

logger = logging.getLogger("studiamo")


def get_client_ip(request: Request) -> str:
    """Rate-limit key: the real visitor IP, not the tunnel connector's address.

    The app is only reachable through the Cloudflare tunnel (bound to 127.0.0.1,
    UFW blocks everything else), so request.client.host is always cloudflared's
    loopback address, the same for every visitor, and CF-Connecting-IP is safe to
    trust: it's set by Cloudflare's edge from the real connection, and there is no
    way to reach the origin directly to forge it. Falls back to get_remote_address
    for requests that don't come through the tunnel (local/dev, tests).
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    return cf_ip.strip() if cf_ip else get_remote_address(request)


# Rate limiter setup
limiter = Limiter(key_func=get_client_ip, default_limits=["600/minute"])


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


_INTERNAL_REFERRER_DOMAINS = ("studiamo.cloud", "localhost")


def _is_internal_referrer_host(host: str) -> bool:
    """Exact domain or subdomain match. A substring test would also drop unrelated sites
    whose names merely contain one of these, e.g. an Italian site with "studiamo" in its
    domain."""
    if host == "127.0.0.1":
        return True
    if host.startswith("accounts.google."):
        return True
    return any(host == d or host.endswith("." + d) for d in _INTERNAL_REFERRER_DOMAINS)


def clean_external_referrer(url: Optional[str], request_host: Optional[str] = None) -> Optional[str]:
    """Returns an external referrer URL, or None if the URL is internal, empty, or an auth service.

    Internal origins (studiamo.cloud and its subdomains, localhost, 127.0.0.1, or matching the
    current Host header) and auth providers (accounts.google.*) are navigation steps, not
    acquisition channels. A URL carrying credentials is dropped: browsers never send one as a
    referrer, so it can only be a hand-crafted value.
    """
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    if raw.lower().startswith("utm:"):
        return raw[:500]
    try:
        from urllib.parse import urlparse
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        if not host or "@" in parsed.netloc:
            return None
        if _is_internal_referrer_host(host):
            return None
        if request_host and host == request_host.lower().split(":")[0]:
            return None
        return raw[:500]
    except Exception:
        return None


def safe_local_path(value) -> str:
    """Returns `value` if it is a same-site absolute path, otherwise "/".

    A leading "/" alone is not enough: "//host" is a protocol-relative URL and browsers
    treat "/\\host" the same way, and tabs or newlines inside a URL are stripped before
    parsing, so "/<tab>/host" collapses to "//host". Every post-login redirect target goes
    through this before it is signed or followed."""
    path = str(value or "").strip()
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return "/"
    return path


def _sign_oauth_state(dest_path: str, ref_code: str, require_existing: bool, referrer: str = "",
                      link_intent: bool = False) -> str:
    """Returns a signed, tamper-proof state string for Google OAuth 2.0 requests.

    `referrer` carries the page that sent the visitor into the OAuth flow (captured at
    /auth/google, the last hop where the browser's Referer header still points at our own
    site, not Google's consent screen) so the callback, which only ever sees Google as its
    Referer, can still attribute the signup to where it actually started.

    `link_intent` records that the flow was started by the "Link Google Account" button in
    Settings rather than by a login button. It rides in the signed state, not in a cookie or
    a query param on the callback, because it decides whether the callback is allowed to
    overwrite an account's Google identity, see google_callback. Inferring that intent from
    "a session cookie happens to be present" instead is what let a stray second callback
    rebind a live account to an unrelated Google account.
    """
    import time
    payload = {
        "d": dest_path or "/",
        "r": ref_code or "",
        "e": 1 if require_existing else 0,
        "t": int(time.time()),
        "rf": (referrer or "")[:500],
        "l": 1 if link_intent else 0,
    }
    return _oauth_state_signer.dumps(payload)


def _decode_oauth_state(state_str: Optional[str]) -> tuple[str, str, bool, str, bool]:
    """Decodes and validates a signed OAuth state token, rejecting expired (>15 min) or forged states.

    Returns (dest_path, ref_code, require_existing, referrer, link_intent). Every failure path
    returns the defaults, link_intent False included: an unreadable state must never be the
    thing that authorizes rebinding an account's Google identity."""
    import time
    if not state_str:
        return "/", "", False, "", False
    try:
        data = _oauth_state_signer.loads(state_str)
        issued_at = data.get("t", 0)
        if time.time() - issued_at > 900:
            logger.warning("[google_oauth] OAuth state parameter expired (>15 minutes old).")
            return "/", "", False, "", False
        dest_path = safe_local_path(data.get("d", "/"))
        ref_code = str(data.get("r", "")).strip()
        require_existing = bool(data.get("e", 0))
        referrer = str(data.get("rf", "")).strip()
        link_intent = bool(data.get("l", 0))
        return dest_path, ref_code, require_existing, referrer, link_intent
    except Exception:
        logger.warning(f"[google_oauth] Invalid or tampered OAuth state parameter: {state_str[:100]!r}")
        return "/", "", False, "", False



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


def require_dev_tools_enabled() -> None:
    """Dependency guard: blocks the /api/test/* SRS helpers in cloud mode.

    These exist to put a local account into a given review state while working on the
    scheduler. They have no UI, and they rewrite every quiz's next_review_at for the
    caller, so on cloud the only thing finding one can do is destroy your own schedule.
    Self-hosted keeps them, since there the operator and the user are the same person.
    """
    if config.IS_CLOUD:
        raise HTTPException(status_code=404, detail="Not found")


# --- Bug tracker admin gate ---
# A separate signed cookie, not the yb_session/_signer above: this gates a single
# shared secret (see scripts/set_admin_password.py), not a per-user account, so it
# deliberately can't be confused with or decoded as a real user session token.
#
# The salt keeps its original value. Rotating it would invalidate every live admin cookie
# while changing nothing about the strength of the signature, which is derived from
# SECRET_KEY; there is no benefit to pay a forced re-login for.
_admin_signer = URLSafeSerializer(SECRET_KEY, salt="bugs-admin-v1")
ADMIN_COOKIE_NAME = "studiamo_admin"

# app_settings key holding the shared admin password (bcrypt, set via scripts/set_admin_password.py).
ADMIN_PASSWORD_SETTING_KEY = "admin_password_hash"


def make_admin_token() -> str:
    """Returns a signed token proving the shared admin password was entered."""
    return _admin_signer.dumps("bugs-admin")


def is_admin(request: Request) -> bool:
    """Non-raising check for the admin cookie. Used by the public bug-list endpoint to
    decide whether to include usernames and captured context in the response.

    This gate is no longer only about bug reports: the same password opens the Users page
    in the private admin cockpit, which lists accounts by email."""
    token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not token:
        return False
    try:
        return _admin_signer.loads(token) == "bugs-admin"
    except BadSignature:
        return False


def require_admin_auth(request: Request) -> None:
    """Dependency guard: blocks admin-only endpoints unless a valid admin cookie is
    present."""
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Admin login required.")


def get_srs_multipliers(username: str) -> dict:
    """Returns this user's per-importance SRS review-interval multipliers from srs_settings,
    defaulting fields that are NULL (never customized) or the row itself (no srs_settings row
    yet). Opens its own connection rather than taking a cursor: some callers (e.g.
    import_manager, ahead of the AI call) need this before they have a cursor of their own."""
    from app.config import DEFAULT_SRS_MULTIPLIERS
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT srs_multiplier_1, srs_multiplier_2, srs_multiplier_3, srs_multiplier_4, srs_multiplier_5
                 FROM srs_settings WHERE user_uuid = %s;""",
            (conn.user_uuid,)
        )
        row = cursor.fetchone() or {}
    finally:
        conn.close()

    def val(key, default):
        v = row.get(key)
        return float(v) if v is not None else default

    return {
        1: val("srs_multiplier_1", DEFAULT_SRS_MULTIPLIERS[0]),
        2: val("srs_multiplier_2", DEFAULT_SRS_MULTIPLIERS[1]),
        3: val("srs_multiplier_3", DEFAULT_SRS_MULTIPLIERS[2]),
        4: val("srs_multiplier_4", DEFAULT_SRS_MULTIPLIERS[3]),
        5: val("srs_multiplier_5", DEFAULT_SRS_MULTIPLIERS[4]),
    }


def get_question_counts(username: str) -> dict:
    """Returns this user's per-importance quiz question counts from srs_settings, strictly
    capped at 15 max per rating level. Same self-contained-connection rationale as
    get_srs_multipliers."""
    from app.config import DEFAULT_QUESTION_COUNTS
    conn = database.get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT question_count_1, question_count_2, question_count_3, question_count_4, question_count_5
                 FROM srs_settings WHERE user_uuid = %s;""",
            (conn.user_uuid,)
        )
        row = cursor.fetchone() or {}
    finally:
        conn.close()

    def val(key, default):
        v = row.get(key)
        return int(v) if v is not None else default

    raw = {
        1: val("question_count_1", DEFAULT_QUESTION_COUNTS[0]),
        2: val("question_count_2", DEFAULT_QUESTION_COUNTS[1]),
        3: val("question_count_3", DEFAULT_QUESTION_COUNTS[2]),
        4: val("question_count_4", DEFAULT_QUESTION_COUNTS[3]),
        5: val("question_count_5", DEFAULT_QUESTION_COUNTS[4]),
    }
    return {k: min(15, max(1, v)) for k, v in raw.items()}


STAGE_KEYS = ["stage_0", "stage_1", "stage_2", "stage_3", "stage_4"]


def _stage_of(item: dict) -> int:
    """Reads an item's stage index defensively, since it round-trips through JSONB."""
    try:
        return max(0, min(int(item.get("stage", 0)), len(STAGE_KEYS) - 1))
    except (TypeError, ValueError):
        return 0


def build_concept_pool(analysis: dict) -> list:
    """Flattens an AI analysis result's five per-stage quiz sets into one flat pool.

    Each item keeps the fields the model produced and gains an integer `stage`. This is the
    shape `quizzes.concept_pool` holds: one flat array rather than the nested `stages` object,
    so a topic selection can filter across stages in a single pass.

    Every caller used to drop everything but stage 0 on the floor here, because the only
    persisted field was `questions_json` and it holds a flat list.
    """
    if not isinstance(analysis, dict):
        return []

    # ai._normalise_analysis already flattens the model's response and tags each item with its
    # stage, so a fresh analysis arrives with this filled in. The reconstruction below is the
    # fallback for payloads that predate it, or that came from somewhere other than an AI call.
    prebuilt = analysis.get("concept_pool")
    if isinstance(prebuilt, list) and prebuilt:
        return [dict(item) for item in prebuilt if isinstance(item, dict) and item.get("question")]

    pool = []
    stages = analysis.get("stages") or {}
    if isinstance(stages, dict):
        for stage_index, key in enumerate(STAGE_KEYS):
            for item in (stages.get(key) or []):
                if isinstance(item, dict) and item.get("question"):
                    entry = dict(item)
                    entry["stage"] = stage_index
                    pool.append(entry)

    # generate_topic_quiz's fallback path and any older analysis return only a flat `quiz`
    # list, which is the stage-0 set. Without this the pool would be empty for them and every
    # stage would fall through to questions_json, which is the behaviour this column replaces.
    if not pool:
        for item in (analysis.get("quiz") or []):
            if isinstance(item, dict) and item.get("question"):
                entry = dict(item)
                entry["stage"] = 0
                pool.append(entry)

    return pool


def select_stage_questions(concept_pool, srs_stage, focus_topics=None, limit=None) -> list:
    """Picks the active questions for one SRS stage out of a concept pool.

    Applies the user's saved topic selection for that stage when there is one, then takes the
    first `limit` items. The slice must stay a *prefix*: POST /api/quiz/verify-guess and
    quiz_attempts.question_index both address questions by position in the stored list, so a
    random sample would grade an answer against a different question than the one displayed.
    """
    if not isinstance(concept_pool, list) or not concept_pool:
        return []

    try:
        stage = max(0, min(int(srs_stage or 0), len(STAGE_KEYS) - 1))
    except (TypeError, ValueError):
        stage = 0

    items = [q for q in concept_pool if isinstance(q, dict) and _stage_of(q) == stage]

    # A stage the model returned nothing for falls back to the nearest lower stage that has
    # questions, rather than opening an empty quiz.
    if not items:
        for fallback in range(stage - 1, -1, -1):
            items = [q for q in concept_pool if isinstance(q, dict) and _stage_of(q) == fallback]
            if items:
                break

    selected = focus_topics.get(STAGE_KEYS[stage]) if isinstance(focus_topics, dict) else None
    if selected:
        filtered = [q for q in items if q.get("topic") in selected]
        # An empty result means the saved topics no longer match the pool, for example after a
        # re-import produced different topic names. Serving the unfiltered stage beats handing
        # the user an empty quiz.
        if filtered:
            # A saved selection is an explicit instruction, so it is honoured exactly, even
            # when it yields fewer questions than the star rating asks for. The overlay warns
            # about that before saving; silently topping it back up would undo the choice.
            return filtered[:limit] if limit else filtered

    # No saved selection means "use what the AI recommended", which is what the focus overlay
    # shows pre-ticked. Ordering by that flag rather than filtering on it keeps two properties
    # at once: the recommended questions come first, and the session still reaches the
    # configured length when the model marked fewer than that (a stage with 4 recommended
    # questions and a 5-question setting yields those 4 plus the next best one). Sorting is
    # stable, so the model's own ordering survives within each group.
    ordered = sorted(items, key=lambda q: not q.get("ai_recommended"))
    return ordered[:limit] if limit else ordered


MAX_POOL_CARDS = 300
MAX_TOPIC_LEN = 60
MAX_QUESTION_LEN = 500
MAX_ANSWER_LEN = 1000


class CardEditError(ValueError):
    """A card add/remove the caller should be told about. `status` is the HTTP code to use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def topic_of(item: dict) -> str:
    """The topic name an item is grouped under, matching how the focus overlay groups them."""
    return (item.get("topic") or "Ungrouped").strip() or "Ungrouped"


def card_id_of(item: dict) -> str:
    """Stable identifier for a pool item.

    Items the user adds carry a stored `card_id`. AI-generated ones have none, so theirs is
    derived from what identifies them (stage, topic, question text) rather than written back
    to every existing row. Identical question text in the same stage and topic would share an
    id, which is why add_card_to_pool rejects duplicates.
    """
    stored = item.get("card_id")
    if isinstance(stored, str) and stored:
        return stored
    key = f"{_stage_of(item)}|{topic_of(item)}|{(item.get('question') or '').strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def add_card_to_pool(pool: list, stage, topic, question, answer) -> tuple:
    """Returns (new_pool, new_card) with a user-written recall card added.

    The card is a plain question and answer: no options, so it is answered by typing or by
    flipping in every stage (the quiz falls back from choice mode when options are absent).
    It is marked ai_recommended so the default ordering does not bury it behind generated
    cards, and it is placed ahead of the existing cards of its stage and topic, because the
    served list is a prefix of the pool and a card at the end could be cut off by the
    per-session question count.
    """
    try:
        stage = int(stage)
    except (TypeError, ValueError):
        raise CardEditError("Pick a stage between 0 and 4.")
    if not 0 <= stage < len(STAGE_KEYS):
        raise CardEditError("Pick a stage between 0 and 4.")

    topic = (topic or "").strip()
    question = (question or "").strip()
    answer = (answer or "").strip()
    if not topic:
        raise CardEditError("Give the question a topic.")
    if not question or not answer:
        raise CardEditError("A card needs both a question and an answer.")
    if len(topic) > MAX_TOPIC_LEN:
        raise CardEditError(f"Topic names are limited to {MAX_TOPIC_LEN} characters.")
    if len(question) > MAX_QUESTION_LEN:
        raise CardEditError(f"Questions are limited to {MAX_QUESTION_LEN} characters.")
    if len(answer) > MAX_ANSWER_LEN:
        raise CardEditError(f"Answers are limited to {MAX_ANSWER_LEN} characters.")

    pool = [item for item in (pool or []) if isinstance(item, dict)]
    if len(pool) >= MAX_POOL_CARDS:
        raise CardEditError(f"A material can hold at most {MAX_POOL_CARDS} questions.", 409)

    # Match an existing topic case-insensitively so "algorithms" joins "Algorithms" instead
    # of appearing as a second topic in the overlay.
    for item in pool:
        if topic_of(item).lower() == topic.lower():
            topic = topic_of(item)
            break

    for item in pool:
        if (_stage_of(item) == stage and topic_of(item) == topic
                and (item.get("question") or "").strip().lower() == question.lower()):
            raise CardEditError("That question already exists in this topic.", 409)

    card = {
        "topic": topic,
        "question": question,
        "answer": answer,
        "explanation": "",
        "timestamp_seconds": 0,
        "ai_recommended": True,
        "stage": stage,
        "origin": "human",
        "card_id": uuid.uuid4().hex[:12],
    }

    insert_at = len(pool)
    for index, item in enumerate(pool):
        if _stage_of(item) == stage and topic_of(item) == topic:
            insert_at = index
            break
    return pool[:insert_at] + [card] + pool[insert_at:], card


def remove_card_from_pool(pool: list, card_id: str) -> tuple:
    """Returns (new_pool, removed_card). Refuses to empty the pool.

    An empty pool makes GET /api/quiz treat the quiz as broken and regenerate it with a paid
    AI call, which would bring back exactly what was just removed.
    """
    pool = [item for item in (pool or []) if isinstance(item, dict)]
    for index, item in enumerate(pool):
        if card_id_of(item) == card_id:
            if len(pool) == 1:
                raise CardEditError("A material needs at least one question.", 409)
            return pool[:index] + pool[index + 1:], item
    raise CardEditError("That question no longer exists.", 404)


def _clean_topic(topic) -> str:
    topic = (topic or "").strip()
    if not topic:
        raise CardEditError("Give the question a topic.")
    if len(topic) > MAX_TOPIC_LEN:
        raise CardEditError(f"Topic names are limited to {MAX_TOPIC_LEN} characters.")
    return topic


def _existing_topic_name(pool: list, topic: str) -> str:
    """The pool's own spelling of `topic` if it has one, matched case-insensitively."""
    for item in pool:
        if topic_of(item).lower() == topic.lower():
            return topic_of(item)
    return topic


def edit_card_in_pool(pool: list, card_id: str, topic=None, question=None, answer=None) -> tuple:
    """Returns (new_pool, edited_card). A field left as None is unchanged.

    The card keeps its identity: an AI card's id is derived from its stage, topic and question,
    all of which this can change, so the id is frozen into `card_id` before anything moves.
    `edited_at` is stamped only when something actually changed. `origin` is left alone, so a
    modified AI card still reads as AI-made and modified.

    A card that changes topic is placed ahead of that topic's other cards, as add does; a card
    edited in place keeps its position, so the served order does not shift under a session.
    """
    pool = [item for item in (pool or []) if isinstance(item, dict)]
    index = next((i for i, item in enumerate(pool) if card_id_of(item) == card_id), None)
    if index is None:
        raise CardEditError("That question no longer exists.", 404)

    original = pool[index]
    card = dict(original)
    card["card_id"] = card_id

    if question is not None:
        question = question.strip()
        if not question:
            raise CardEditError("A card needs a question.")
        if len(question) > MAX_QUESTION_LEN:
            raise CardEditError(f"Questions are limited to {MAX_QUESTION_LEN} characters.")
        card["question"] = question
    if answer is not None:
        answer = answer.strip()
        if not answer:
            raise CardEditError("A card needs an answer.")
        if len(answer) > MAX_ANSWER_LEN:
            raise CardEditError(f"Answers are limited to {MAX_ANSWER_LEN} characters.")
        card["answer"] = answer
    if topic is not None:
        others = pool[:index] + pool[index + 1:]
        card["topic"] = _existing_topic_name(others, _clean_topic(topic))

    stage = _stage_of(card)
    for i, item in enumerate(pool):
        if (i != index and _stage_of(item) == stage and topic_of(item) == topic_of(card)
                and (item.get("question") or "").strip().lower() == (card.get("question") or "").strip().lower()):
            raise CardEditError("That question already exists in this topic.", 409)

    changed = any(card.get(k) != original.get(k) for k in ("topic", "question", "answer"))
    if not changed:
        return pool, original
    card["edited_at"] = datetime.now(timezone.utc).isoformat()

    others = pool[:index] + pool[index + 1:]
    if topic_of(card) == topic_of(original):
        return pool[:index] + [card] + pool[index + 1:], card

    insert_at = len(others)
    for i, item in enumerate(others):
        if _stage_of(item) == stage and topic_of(item) == topic_of(card):
            insert_at = i
            break
    return others[:insert_at] + [card] + others[insert_at:], card


def rename_topic_in_pool(pool: list, old: str, new: str) -> tuple:
    """Returns (new_pool, renamed_count). Renames a topic in every stage it appears in.

    Topic strings are shared across stages on purpose (the generation prompt asks for the same
    string verbatim, and the overlay groups by it), so a rename that touched one stage would
    split a topic in two. Renaming onto a different existing topic is refused rather than
    merged: merging can create two identical questions in one topic, and moving individual
    cards already covers the case where someone wants that.
    """
    pool = [item for item in (pool or []) if isinstance(item, dict)]
    old = (old or "").strip()
    new = _clean_topic(new)

    if not any(topic_of(item) == old for item in pool):
        raise CardEditError("That topic no longer exists.", 404)
    if new == old:
        return pool, 0
    for item in pool:
        name = topic_of(item)
        if name != old and name.lower() == new.lower():
            raise CardEditError("A topic with that name already exists.", 409)

    stamp = datetime.now(timezone.utc).isoformat()
    renamed = []
    count = 0
    for item in pool:
        if topic_of(item) == old:
            card = dict(item)
            card["card_id"] = card_id_of(item)
            card["topic"] = new
            card["edited_at"] = stamp
            renamed.append(card)
            count += 1
        else:
            renamed.append(item)
    return renamed, count


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


def get_srs_caps_and_repetition(cursor, user_uuid: Optional[str] = None) -> dict:
    """Fetches this user's importance-based stage-cap and stage-5-repetition settings from
    srs_settings, defaulting fields that are NULL (never customized) or the row itself
    (no srs_settings row yet). Both features live in the same table as the stage day
    intervals (see get_srs_intervals) but are read separately since most callers need only
    one or the other."""
    from app.config import (DEFAULT_SRS_CAPS, DEFAULT_ENABLE_STAGE_5_REPETITION,
                             DEFAULT_STAGE_5_REPEAT_INTERVAL)
    row = {}
    if user_uuid:
        cursor.execute(
            """SELECT cap_stages_by_importance, srs_cap_1, srs_cap_2, srs_cap_3, srs_cap_4, srs_cap_5,
                      enable_stage_5_repetition, stage_5_repeat_interval
                 FROM srs_settings WHERE user_uuid = %s;""",
            (user_uuid,)
        )
        row = cursor.fetchone() or {}

    def val(key, default):
        v = row.get(key)
        return v if v is not None else default

    return {
        "cap_by_importance": bool(val("cap_stages_by_importance", False)),
        "caps": {
            1: val("srs_cap_1", DEFAULT_SRS_CAPS[0]),
            2: val("srs_cap_2", DEFAULT_SRS_CAPS[1]),
            3: val("srs_cap_3", DEFAULT_SRS_CAPS[2]),
            4: val("srs_cap_4", DEFAULT_SRS_CAPS[3]),
            5: val("srs_cap_5", DEFAULT_SRS_CAPS[4]),
        },
        "enable_stage_5_repetition": bool(val("enable_stage_5_repetition", DEFAULT_ENABLE_STAGE_5_REPETITION)),
        "stage_5_repeat_interval": val("stage_5_repeat_interval", DEFAULT_STAGE_5_REPEAT_INTERVAL),
    }


def compute_max_stages(cap_by_importance: bool, caps: dict, importance: int, num_stages: int) -> int:
    """Highest SRS stage a quiz with this importance rating can reach for this user:
    num_stages normally, or the user's configured per-importance cap when stage capping
    is enabled. `caps` is keyed 1-5 (importance_rating), as returned by
    get_srs_caps_and_repetition()["caps"]."""
    if not cap_by_importance:
        return num_stages
    imp = importance if importance in caps else 3
    return max(1, min(caps.get(imp, num_stages), num_stages))


def get_user_timezone(cursor, user_uuid: Optional[str] = None):
    """Returns the tzinfo for the user's stored time zone, UTC when unset or invalid.

    Best-effort by design, like the preferred-hour lookup it replaced: a failed lookup must
    not block scheduling a review, so it logs once and falls back to UTC rather than raising.
    """
    if not user_uuid:
        return local_days.resolve_timezone(None)
    try:
        cursor.execute("SELECT timezone FROM user_profile WHERE user_uuid = %s LIMIT 1;", (user_uuid,))
        row = cursor.fetchone()
        return local_days.resolve_timezone(row.get("timezone") if row else None)
    except Exception as e:
        logger.warning(f"[get_user_timezone] lookup failed for user_uuid={user_uuid}: {e}")
        return local_days.resolve_timezone(None)


def effective_reminder_hour(reminder_hour, legacy_preferred_hour, tz) -> int:
    """Returns the local hour (0-23) the daily reminder goes out at.

    reminder_hour is the user's own choice in local time. Accounts that only ever set the
    older preferred_hour have a UTC hour stored, which is converted to local time here instead
    of being migrated, so the column can stay untouched. -1 meant "any time" there and falls
    through to the default, since reminders now go out once a day at a set hour.
    """
    from app.config import DEFAULT_REMINDER_HOUR
    for raw, is_utc in ((reminder_hour, False), (legacy_preferred_hour, True)):
        try:
            hour = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23:
            if not is_utc:
                return hour
            today = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
            return today.astimezone(tz or timezone.utc).hour
    return DEFAULT_REMINDER_HOUR



