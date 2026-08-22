"""
Admin tool: promote the next N waitlist users to active.

Run: python scripts/promote_waitlist.py <n> [--max-users=<new_cap>]

Deliberately a script, not an HTTP endpoint : there's no admin-auth concept
in this codebase, and this is a low-frequency action a human runs by hand.

--max-users optionally bumps app_settings.max_users first (e.g. when you're
opening more capacity and promoting in the same step). Without it, the cap
is left as-is; promoting beyond the current cap is still allowed since this
is a deliberate admin action, not the automatic signup-time gate.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database, email_utils, landing_waitlist_db


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args or not args[0].isdigit():
        print(__doc__)
        sys.exit(1)
    n = int(args[0])

    new_cap = None
    for a in sys.argv[1:]:
        if a.startswith("--max-users="):
            new_cap = a.split("=", 1)[1]

    if new_cap is not None:
        conn = database.get_pooled_raw_connection()
        try:
            conn.cursor().execute(
                "INSERT INTO app_settings (key, value) VALUES ('max_users', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;",
                (new_cap,)
            )
            print(f"max_users set to {new_cap}")
        finally:
            database.release_pooled_connection(conn)

    promoted = database.promote_next_n_users(n)
    if not promoted:
        print("No waitlist users to promote.")
        return

    print(f"Promoted {len(promoted)} user(s):")
    for row in promoted:
        username = row["username"]
        # google_email first, matching every other address decision in the app (billing
        # checkout, notification settings, the test-email route). It is the address tied to
        # the identity the account actually signs in with; `email` is a copy that can go
        # stale if the two ever diverge, so preferring it here could mail the wrong inbox.
        recipient = row.get("google_email") or row.get("email")

        # Stamped before the send and independently of whether it succeeds. The account is
        # already active at this point, so a lead row still reading as "waiting" is wrong the
        # moment the UPDATE above committed, and a failed email must not be what decides
        # whether a later mailer treats this person as a prospect.
        landing_waitlist_db.mark_waitlist_converted(row.get("google_email"), row.get("email"))

        if not recipient:
            print(f"  - {username}: no email on file, skipping promotion email")
            continue
        sent = email_utils.send_promotion_email(recipient)
        status = "email sent" if sent else "email NOT sent (see logs)"
        if sent:
            try:
                landing_waitlist_db.mark_waitlist_email_sent(recipient, "spot_ready")
            except Exception as e:
                status += f" (landing_waitlist stamp failed: {e})"
        print(f"  - {username} ({recipient}): {status}")


if __name__ == "__main__":
    main()
