"""
Web Push (VAPID) utility module for Studiamo.
Handles VAPID keypair generation/loading and Web Push notification dispatch.
Push subscriptions are stored in the push_subscriptions PostgreSQL table,
keyed by user_uuid. No config blob is used.
"""
import os
import json
import base64
import logging
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import BASE_DIR, get_user_uuid_from_db

logger = logging.getLogger("studiamo.webpush")

VAPID_FILE = BASE_DIR / "vapid_keys.json"


def ensure_vapid_keys() -> dict:
    """Ensures VAPID keypair exists in vapid_keys.json, generating a new P-256 pair if missing."""
    if VAPID_FILE.exists():
        try:
            with open(VAPID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("public_key") and data.get("private_key"):
                    return data
        except Exception as e:
            logger.error(f"Error reading {VAPID_FILE}: {e}")

    # Generate new P-256 EC Keypair
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_number = private_key.private_numbers().private_value
    private_bytes = private_number.to_bytes(32, byteorder="big")
    private_b64 = base64.urlsafe_b64encode(private_bytes).decode("ascii").rstrip("=")

    public_numbers = private_key.public_key().public_numbers()
    x_bytes = public_numbers.x.to_bytes(32, byteorder="big")
    y_bytes = public_numbers.y.to_bytes(32, byteorder="big")
    public_bytes = b"\x04" + x_bytes + y_bytes
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode("ascii").rstrip("=")

    keys = {
        "public_key": public_b64,
        "private_key": private_b64,
        "claims_email": "mailto:admin@studiamo.app"
    }

    try:
        with open(VAPID_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=2)
        logger.info(f"Generated new VAPID keypair in {VAPID_FILE}")
    except Exception as e:
        logger.error(f"Failed to save VAPID keys to {VAPID_FILE}: {e}")

    return keys


def get_vapid_public_key() -> str:
    """Returns the base64url-encoded VAPID public key for client push subscriptions."""
    keys = ensure_vapid_keys()
    return keys["public_key"]


def save_user_push_subscription(username: str, subscription_info: dict) -> bool:
    """Saves a browser PushSubscription object to the push_subscriptions table.

    @param username: The username of the subscribing user.
    @param subscription_info: The full PushSubscription JSON object from the browser.
    @returns: True if saved or already exists, False on invalid input.
    """
    if not subscription_info or not subscription_info.get("endpoint"):
        return False

    from app.database import get_db_connection
    user_uuid = get_user_uuid_from_db(username)
    if not user_uuid:
        return False

    endpoint = subscription_info["endpoint"]
    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        # Upsert: insert if not exists (idempotent on endpoint uniqueness)
        cursor.execute(
            """
            INSERT INTO push_subscriptions (user_uuid, endpoint, subscription_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (user_uuid, endpoint) DO NOTHING;
            """,
            (user_uuid, endpoint, json.dumps(subscription_info))
        )
        conn.commit()
        logger.info(f"Saved push subscription for user {username}")
        return True
    except Exception as e:
        logger.error(f"Error saving push subscription for {username}: {e}")
        return False
    finally:
        conn.close()


def remove_user_push_subscription(username: str, endpoint: str) -> bool:
    """Removes a push subscription by endpoint from the push_subscriptions table.

    @param username: The username of the user.
    @param endpoint: The push subscription endpoint URL to remove.
    @returns: True if the deletion executed without error.
    """
    from app.database import get_db_connection
    user_uuid = get_user_uuid_from_db(username)
    if not user_uuid:
        return False

    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM push_subscriptions WHERE user_uuid = %s AND endpoint = %s;",
            (user_uuid, endpoint)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error removing push subscription for {username}: {e}")
        return False
    finally:
        conn.close()


def send_web_push(subscription_info: dict, payload_data: dict) -> bool:
    """Delivers a Web Push notification to a single PushSubscription.

    @param subscription_info: The PushSubscription JSON object.
    @param payload_data: The notification payload dict (title, body, url).
    @returns: True if delivered successfully.
    """
    keys = ensure_vapid_keys()
    vapid_private_key = keys["private_key"]
    vapid_claims = {"sub": keys.get("claims_email", "mailto:admin@studiamo.app")}

    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload_data),
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims
        )
        return True
    except ImportError:
        logger.warning("pywebpush not installed. Web Push notification could not be sent.")
        return False
    except Exception as e:
        logger.warning(f"Web Push delivery failed: {e}")
        return False


def send_user_web_push(username: str, payload_data: dict) -> int:
    """Dispatches a Web Push notification to all active subscriptions of a user.

    Reads subscriptions from the push_subscriptions table keyed by user_uuid.
    Removes stale subscriptions on delivery failure (HTTP 410 Gone).

    @param username: The username to notify.
    @param payload_data: The notification payload dict (title, body, url).
    @returns: Number of successfully delivered notifications.
    """
    from app.database import get_db_connection
    user_uuid = get_user_uuid_from_db(username)
    if not user_uuid:
        return 0

    conn = get_db_connection(username)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT endpoint, subscription_json FROM push_subscriptions WHERE user_uuid = %s;",
            (user_uuid,)
        )
        rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching push subscriptions for {username}: {e}")
        return 0
    finally:
        conn.close()

    if not rows:
        return 0

    sent_count = 0
    stale_endpoints = []

    for row in rows:
        endpoint = row["endpoint"]
        sub_json = row["subscription_json"]
        if isinstance(sub_json, str):
            try:
                sub_json = json.loads(sub_json)
            except Exception:
                continue
        if not isinstance(sub_json, dict) or not sub_json.get("endpoint"):
            continue

        success = send_web_push(sub_json, payload_data)
        if success:
            sent_count += 1
        else:
            # Mark for cleanup , stale subscriptions accumulate without this
            stale_endpoints.append(endpoint)

    # Clean up stale subscriptions
    if stale_endpoints:
        try:
            conn2 = get_db_connection(username)
            cur2 = conn2.cursor()
            for ep in stale_endpoints:
                cur2.execute(
                    "DELETE FROM push_subscriptions WHERE user_uuid = %s AND endpoint = %s;",
                    (user_uuid, ep)
                )
            conn2.commit()
            conn2.close()
        except Exception as e:
            logger.warning(f"Error cleaning stale push subscriptions for {username}: {e}")

    return sent_count
