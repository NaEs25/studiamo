"""Lemon Squeezy subscription billing for cloud mode.

Lemon Squeezy is Merchant of Record: it owns checkout, tax and invoicing, and reports
state back here over webhooks. This module therefore holds no payment logic of its own, it builds checkout URLs, verifies and applies incoming webhooks, and exposes the resulting
subscription state to the frontend.

Self-hosted deployments have no billing at all (users bring their own Gemini key and pay
Google directly), so every route here refuses to run outside cloud mode.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app import config, database
from app.dependencies import get_active_username, limiter

logger = logging.getLogger("studiamo")

router = APIRouter(tags=["Billing"])

_LS_API_BASE = "https://api.lemonsqueezy.com/v1"


def _require_cloud() -> None:
    """Billing routes exist only in cloud mode. 404 rather than 403: on a self-hosted
    install these endpoints are not 'forbidden', they are genuinely not part of the app."""
    if not config.IS_CLOUD:
        raise HTTPException(status_code=404, detail="Not found.")


def _parse_ls_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parses a Lemon Squeezy ISO-8601 timestamp into an aware UTC datetime.

    LS sends a trailing 'Z', which datetime.fromisoformat only accepts from Python 3.11.
    Returns None for null/unparseable values rather than raising: a webhook must never be
    rejected over a date field, or LS will retry it forever and the subscription state
    behind it will never land."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.warning(f"Lemon Squeezy: could not parse timestamp {value!r}")
        return None


# --------------------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------------------

def build_checkout_url(user_uuid: str, email: str = "") -> str:
    """Builds the hosted Lemon Squeezy checkout URL for one user.

    user_uuid travels in checkout[custom][user_uuid] and comes back on every subscription
    webhook as meta.custom_data.user_uuid. That is the ONLY identity link between a payment
    and an account: the email captured at checkout is the card-holder's and frequently
    differs from the account email, so matching on it would attach subscriptions to the
    wrong user or to no user at all.

    email is prefilled purely as a convenience and is never used to resolve identity.

    The promotional code is deliberately NOT pre-applied here. Lemon Squeezy renders an
    auto-applied discount as a line item near the bottom of the checkout, below the pay
    button, so the headline price a customer reads on the way in is the full one and the
    reduction only becomes visible if they scroll. Telling them the code in our own UI and
    letting them enter it means the offer is stated where the decision is made, in wording
    we control, instead of being discovered late in someone else's layout."""
    ls = config.get_lemonsqueezy_config()
    params = {"checkout[custom][user_uuid]": user_uuid}
    if email:
        params["checkout[email]"] = email
    # safe="[]" keeps Lemon Squeezy's bracket syntax literal in the query string.
    return f"{ls['buy_url']}?{urlencode(params, safe='[]')}"


@router.get("/api/billing/checkout")
@limiter.limit("20/minute")
async def create_checkout(
    request: Request,
    username: str = Depends(get_active_username),
):
    """Returns the checkout URL for the signed-in user.

    JSON rather than a redirect so the paywall modal can surface a real error instead of
    navigating the user to a broken page if billing is misconfigured.

    There is one checkout URL, not a standard one and a discounted one. The promotional
    code is shown in our own UI and typed in at checkout (see build_checkout_url)."""
    _require_cloud()
    user_uuid = config.get_user_uuid_from_db(username)
    if not user_uuid:
        raise HTTPException(status_code=404, detail="Account not found.")

    user_cfg = config.load_user_config(username)
    email = user_cfg.get("GOOGLE_EMAIL") or user_cfg.get("EMAIL") or ""

    try:
        url = build_checkout_url(user_uuid, email=email)
    except RuntimeError as e:
        # require_env_for_cloud raises when a Lemon Squeezy value is missing.
        logger.error(f"Lemon Squeezy is not configured: {e}")
        raise HTTPException(status_code=503, detail="Checkout is temporarily unavailable.")

    return {"checkout_url": url}


# --------------------------------------------------------------------------------------
# Subscription state
# --------------------------------------------------------------------------------------

@router.get("/api/billing/status")
async def get_billing_status(username: str = Depends(get_active_username)):
    """Current access + subscription state for the signed-in user.

    Drives the paywall modal and the post-checkout poll, so it is deliberately cheap:
    one indexed lookup, no Lemon Squeezy API call. get_access_snapshot() is what keeps it
    to one: the access decision, the tester state and the fields below all live on the same
    row, and fetching them separately made this three round trips on every page load."""
    _require_cloud()
    snapshot = database.get_access_snapshot(username)
    row = snapshot["profile"]

    return {
        "has_access": snapshot["has_access"],
        "status": row.get("subscription_status") or "inactive",
        # Kept for backward compatibility with clients still reading the flat flag. New code
        # should read `tester` below, which is the one that knows about end dates.
        "is_tester": bool(row.get("is_tester")),
        "tester": database.tester_state_payload(snapshot["tester"]),
        "renews_at": row["ls_renews_at"].isoformat() if row.get("ls_renews_at") else None,
        "ends_at": row["ls_ends_at"].isoformat() if row.get("ls_ends_at") else None,
        "has_portal": bool(row.get("ls_customer_portal_url")),
        # Shown in the UI for the customer to type in at checkout, rather than pre-applied
        # to the URL. Served from here and not /api/config because that route is public and
        # unauthenticated; this one at least requires a session. Empty string when no code
        # is configured, which the frontend treats as "say nothing about a discount".
        "beta_discount_code": config.LEMONSQUEEZY_BETA_DISCOUNT_CODE or "",
    }


@router.post("/api/billing/tester/ack")
async def acknowledge_tester_notice(
    kind: str = Form(...),
    username: str = Depends(get_active_username),
):
    """Records that a tester notice (welcome, expiry reminder, expiry screen) was shown.

    Depends on get_active_username rather than require_app_access on purpose: the 'expiry'
    notice is shown to someone whose access has just ended, so gating this on having access
    would make the one acknowledgement that matters most impossible to record."""
    _require_cloud()
    try:
        updated = database.mark_tester_notice_seen(username, kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "updated": updated}


@router.get("/api/billing/portal")
async def get_billing_portal(username: str = Depends(get_active_username)):
    """Returns the Lemon Squeezy customer portal URL, where the user updates their card,
    cancels, or resumes. Cancellation must always be reachable from inside the app.

    The URL is captured from webhooks; the API fallback covers a subscription that was
    created while a webhook was failing."""
    _require_cloud()
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """SELECT ls_customer_portal_url, ls_subscription_id
               FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;""",
            (username,)
        )
        row = cursor.fetchone() or {}
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    portal_url = row.get("ls_customer_portal_url")
    if portal_url:
        return {"portal_url": portal_url}

    subscription_id = row.get("ls_subscription_id")
    if not subscription_id:
        raise HTTPException(status_code=404, detail="No subscription found for this account.")

    ls = config.get_lemonsqueezy_config()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_LS_API_BASE}/subscriptions/{subscription_id}",
                headers={
                    "Authorization": f"Bearer {ls['api_key']}",
                    "Accept": "application/vnd.api+json",
                },
            )
        resp.raise_for_status()
        urls = resp.json()["data"]["attributes"].get("urls") or {}
        portal_url = urls.get("customer_portal")
    except Exception as e:
        logger.error(f"Lemon Squeezy portal lookup failed for {username}: {e}")
        raise HTTPException(status_code=502, detail="Could not reach the billing portal.")

    if not portal_url:
        raise HTTPException(status_code=404, detail="No billing portal available for this subscription.")
    return {"portal_url": portal_url}


# --------------------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------------------

# Events that carry a subscription object we care about. Anything else (orders, licences,
# one-off payments) is acknowledged and ignored, see the handler for why acknowledging
# matters more than handling.
_SUBSCRIPTION_EVENTS = {
    "subscription_created",
    "subscription_updated",
    "subscription_cancelled",
    "subscription_resumed",
    "subscription_expired",
    "subscription_paused",
    "subscription_unpaused",
    "subscription_payment_success",
    "subscription_payment_failed",
    "subscription_payment_recovered",
}


def _verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verifies the X-Signature header against an HMAC-SHA256 of the raw request body.

    This is the only thing standing between the webhook endpoint and anyone on the internet
    granting themselves a subscription, so it runs before the body is parsed and uses
    compare_digest to avoid leaking the expected digest through timing."""
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _apply_subscription_event(event_name: str, payload: dict) -> bool:
    """Writes one Lemon Squeezy subscription event onto the owning user_profile row.

    Returns True if a row was updated. Resolution order is user_uuid from custom_data
    first, then the subscription id, the latter covers any event that arrives without
    custom_data, since after subscription_created we already know which row owns that id."""
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    meta = payload.get("meta") or {}
    custom = meta.get("custom_data") or {}

    subscription_id = str(data.get("id") or "")
    user_uuid = str(custom.get("user_uuid") or "")

    status = (attrs.get("status") or "").lower()
    if not status:
        logger.warning(f"Lemon Squeezy {event_name}: payload has no status, ignoring.")
        return False

    urls = attrs.get("urls") or {}
    values = {
        "subscription_status": status,
        "ls_subscription_id": subscription_id or None,
        "ls_customer_id": str(attrs["customer_id"]) if attrs.get("customer_id") else None,
        "ls_variant_id": str(attrs["variant_id"]) if attrs.get("variant_id") else None,
        "ls_renews_at": _parse_ls_timestamp(attrs.get("renews_at")),
        "ls_ends_at": _parse_ls_timestamp(attrs.get("ends_at")),
        "ls_customer_portal_url": urls.get("customer_portal") or None,
    }

    # COALESCE(%s, col) keeps a previously stored value when this particular payload omits
    # the field, so a partial event can never blank out the customer portal URL or the
    # ends_at date that has_app_access() depends on. subscription_status is set
    # unconditionally, it is the whole point of the event.
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        params = [
            values["subscription_status"],
            values["ls_subscription_id"],
            values["ls_customer_id"],
            values["ls_variant_id"],
            values["ls_renews_at"],
            values["ls_ends_at"],
            values["ls_customer_portal_url"],
        ]
        set_clause = """
            SET subscription_status = %s,
                ls_subscription_id = COALESCE(%s, ls_subscription_id),
                ls_customer_id = COALESCE(%s, ls_customer_id),
                ls_variant_id = COALESCE(%s, ls_variant_id),
                ls_renews_at = COALESCE(%s, ls_renews_at),
                ls_ends_at = COALESCE(%s, ls_ends_at),
                ls_customer_portal_url = COALESCE(%s, ls_customer_portal_url)
        """
        if user_uuid:
            cursor.execute(
                f"UPDATE user_profile {set_clause} WHERE user_uuid = %s RETURNING username;",
                params + [user_uuid],
            )
        elif subscription_id:
            cursor.execute(
                f"UPDATE user_profile {set_clause} WHERE ls_subscription_id = %s RETURNING username;",
                params + [subscription_id],
            )
        else:
            logger.error(f"Lemon Squeezy {event_name}: no user_uuid and no subscription id, cannot apply.")
            return False

        row = cursor.fetchone()
        if not getattr(conn, "autocommit", False):
            conn.commit()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    if not row:
        logger.error(
            f"Lemon Squeezy {event_name}: no user_profile matched "
            f"(user_uuid={user_uuid or 'none'}, subscription_id={subscription_id or 'none'}). "
            f"A payment may be unattributed, check the Lemon Squeezy dashboard."
        )
        return False

    logger.info(
        f"Lemon Squeezy {event_name}: {row['username']} -> status={status} "
        f"subscription={subscription_id}"
    )
    return True


@router.post("/webhooks/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    """Receives subscription state changes from Lemon Squeezy.

    Unauthenticated by necessity, the caller is Lemon Squeezy, not a logged-in user, so
    the HMAC signature check IS the authentication and runs before anything else.

    Always answers 200 once the signature verifies, even for events this app ignores or
    cannot attribute. Lemon Squeezy retries non-2xx responses, and a handler that 500s on
    an unrecognised event turns one bad payload into a retry loop that buries the events
    that do matter. Failures are logged loudly instead."""
    _require_cloud()
    ls = config.get_lemonsqueezy_config()

    # Read the raw body BEFORE parsing: the signature covers the exact bytes sent, and
    # re-serialising parsed JSON would not reproduce them.
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_signature(raw_body, signature, ls["webhook_secret"]):
        logger.warning("Lemon Squeezy webhook rejected: invalid or missing X-Signature.")
        raise HTTPException(status_code=401, detail="Invalid signature.")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Lemon Squeezy webhook: signature valid but body is not JSON.")
        return {"received": True, "handled": False}

    event_name = ((payload.get("meta") or {}).get("event_name") or "").lower()
    if payload.get("meta", {}).get("test_mode"):
        logger.info(f"Lemon Squeezy webhook (TEST MODE): {event_name}")

    if event_name not in _SUBSCRIPTION_EVENTS:
        logger.info(f"Lemon Squeezy webhook: ignoring event {event_name!r}")
        return {"received": True, "handled": False}

    try:
        handled = _apply_subscription_event(event_name, payload)
    except Exception as e:
        # Still 200, see the docstring. The alternative is an infinite retry storm.
        logger.error(f"Lemon Squeezy webhook {event_name} failed to apply: {e}", exc_info=True)
        return {"received": True, "handled": False}

    return {"received": True, "handled": handled}
