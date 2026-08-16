"""
Admin tool: reconcile a Lemon Squeezy subscription onto a user account by hand.

Run:
    python scripts/sync_lemonsqueezy_subscription.py --list
    python scripts/sync_lemonsqueezy_subscription.py --subscription-id 123456 --username alice

This is the recovery path for when a webhook does not arrive or is not applied : a wrong
signing secret, an endpoint that was still 404ing at the moment of purchase, a deploy
mid-checkout. Without it, a customer who has genuinely paid stays locked out and there is
no way to fix it short of editing the database directly.

Deliberately a script, not an HTTP endpoint : same reasoning as grant_tester_access.py:
there is no admin-auth concept in this codebase, and this is a rare action a human runs
knowingly.

The target account is passed explicitly and never inferred. The Lemon Squeezy subscription
object carries `user_email` (the card-holder's), which is frequently not the account email;
guessing from it would silently attach a payment to the wrong account. --list prints the
email alongside each subscription so a human can make that judgement instead.

Accepts either --username or --user-uuid:

  --username   the normal case. The confirmation prompt asks you to retype it, and that
               check only means something for a value a human can recognise : retyping a
               UUID proves nothing, since you would paste the same possibly-wrong string
               twice. Safe as a key because uq_user_profile_username_lower makes
               lower(username) unique.
  --user-uuid  for when a failed webhook is being cleaned up: those errors log
               `user_uuid=...`, so that is the identifier actually in hand.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import httpx
from psycopg2.extras import RealDictCursor

from app import config, database

LS_API = "https://api.lemonsqueezy.com/v1"


def _headers() -> dict:
    ls = config.get_lemonsqueezy_config()
    return {
        "Authorization": f"Bearer {ls['api_key']}",
        "Accept": "application/vnd.api+json",
    }


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def list_subscriptions() -> None:
    """Prints recent subscriptions so a human can identify the right id."""
    ls = config.get_lemonsqueezy_config()
    resp = httpx.get(
        f"{LS_API}/subscriptions",
        headers=_headers(),
        params={"filter[store_id]": ls["store_id"]},
        timeout=20.0,
    )
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    if not rows:
        print("No subscriptions found in this store.")
        return

    print(f"{'id':<12} {'status':<12} {'test':<6} {'email':<32} renews_at")
    print("-" * 86)
    for row in rows:
        a = row["attributes"]
        print(
            f"{row['id']:<12} {a.get('status', ''):<12} "
            f"{str(bool(a.get('test_mode'))):<6} {str(a.get('user_email'))[:31]:<32} "
            f"{a.get('renews_at') or '-'}"
        )
    print("\nAttach one with: --subscription-id <id> --username <account>")


def _resolve_target(username: str = "", user_uuid: str = ""):
    """Returns (user_uuid, username, confirm_token) for the account to write to.

    confirm_token is what the operator must retype. For --username that is the name itself.
    For --user-uuid it is the username the UUID resolved to: retyping the UUID would only
    re-copy the same string, whereas seeing which account it belongs to is a real check."""
    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if user_uuid:
            cursor.execute(
                "SELECT user_uuid, username FROM user_profile WHERE user_uuid = %s LIMIT 1;",
                (user_uuid,)
            )
        else:
            cursor.execute(
                "SELECT user_uuid, username FROM user_profile WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
                (username,)
            )
        row = cursor.fetchone()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    if not row:
        return None, None, None
    return row["user_uuid"], row["username"], row["username"]


def sync(subscription_id: str, username: str = "", user_uuid: str = "", dry_run: bool = False) -> int:
    resp = httpx.get(f"{LS_API}/subscriptions/{subscription_id}", headers=_headers(), timeout=20.0)
    if resp.status_code == 404:
        print(f"Lemon Squeezy has no subscription {subscription_id}.")
        return 1
    resp.raise_for_status()
    attrs = resp.json()["data"]["attributes"]

    user_uuid, username, confirm_token = _resolve_target(username=username, user_uuid=user_uuid)
    if not user_uuid:
        print("No matching user_profile row.")
        return 1

    urls = attrs.get("urls") or {}
    values = {
        "subscription_status": (attrs.get("status") or "").lower(),
        "ls_subscription_id": str(subscription_id),
        "ls_customer_id": str(attrs["customer_id"]) if attrs.get("customer_id") else None,
        "ls_variant_id": str(attrs["variant_id"]) if attrs.get("variant_id") else None,
        "ls_renews_at": _parse_ts(attrs.get("renews_at")),
        "ls_ends_at": _parse_ts(attrs.get("ends_at")),
        "ls_customer_portal_url": urls.get("customer_portal") or None,
    }

    print(f"Subscription {subscription_id} (Lemon Squeezy):")
    print(f"  status        {values['subscription_status']}")
    print(f"  card email    {attrs.get('user_email')}")
    print(f"  test mode     {bool(attrs.get('test_mode'))}")
    print(f"  renews_at     {values['ls_renews_at']}")
    print(f"  ends_at       {values['ls_ends_at']}")
    print(f"\nWould attach to '{username}' (user_uuid {user_uuid}).")

    if attrs.get("test_mode"):
        print("\n  NOTE: this is a TEST MODE subscription. Attaching it grants real access.")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    confirm = input(f"\nType the username ('{confirm_token}') to confirm: ").strip()
    if confirm != confirm_token:
        print("Mismatch : aborted, nothing written.")
        return 1

    conn = None
    try:
        conn = database.get_pooled_raw_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """UPDATE user_profile
                  SET subscription_status = %s,
                      ls_subscription_id = %s,
                      ls_customer_id = COALESCE(%s, ls_customer_id),
                      ls_variant_id = COALESCE(%s, ls_variant_id),
                      ls_renews_at = COALESCE(%s, ls_renews_at),
                      ls_ends_at = COALESCE(%s, ls_ends_at),
                      ls_customer_portal_url = COALESCE(%s, ls_customer_portal_url)
                WHERE user_uuid = %s
            RETURNING username, subscription_status;""",
            (
                values["subscription_status"], values["ls_subscription_id"],
                values["ls_customer_id"], values["ls_variant_id"],
                values["ls_renews_at"], values["ls_ends_at"],
                values["ls_customer_portal_url"], user_uuid,
            ),
        )
        row = cursor.fetchone()
        if not getattr(conn, "autocommit", False):
            conn.commit()
    finally:
        if conn is not None:
            database.release_pooled_connection(conn)

    if not row:
        print("Update matched no row : nothing written.")
        return 1

    print(f"\nDone: {row['username']} -> {row['subscription_status']}")
    print(f"has_app_access: {database.has_app_access(username)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="List subscriptions in the store")
    parser.add_argument("--subscription-id", help="Lemon Squeezy subscription id to attach")
    parser.add_argument("--username", help="Account to attach it to")
    parser.add_argument("--user-uuid", help="Account to attach it to, by user_uuid (as logged by failed webhooks)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change, write nothing")
    args = parser.parse_args()

    if args.list:
        list_subscriptions()
        return

    if not args.subscription_id or not (args.username or args.user_uuid):
        parser.print_help()
        sys.exit(1)
    if args.username and args.user_uuid:
        print("Pass either --username or --user-uuid, not both.")
        sys.exit(1)

    sys.exit(sync(
        args.subscription_id,
        username=args.username or "",
        user_uuid=args.user_uuid or "",
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
