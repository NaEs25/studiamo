"""
Admin tool: promote the next N waitlist users to active.

Run: python scripts/promote_waitlist.py <n> [--max-users=<new_cap>]

Promotes by queue position. To promote one specific account regardless of
its place in the queue, use the Users page in the admin cockpit, which calls
app.promotion.promote_and_notify for the same follow-through this does.

--max-users optionally bumps app_settings.max_users first (e.g. when you're
opening more capacity and promoting in the same step). Without it, the cap
is left as-is; promoting beyond the current cap is still allowed since this
is a deliberate admin action, not the automatic signup-time gate.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database, promotion


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

    # The follow-through (converted_at stamp, promotion email, spot_ready stamp) lives in
    # app.promotion, shared with the admin panel's Users page. Promotion is four steps and
    # only the first is the status change; keeping a second copy here is how the two paths
    # would drift into promoting people the other forgets to tell.
    print(f"Promoted {len(promoted)} user(s):")
    for row in promoted:
        report = promotion.notify_promoted(row)
        if report["email_sent"]:
            print(f"  - {report['username']} ({report['recipient']}): email sent")
        else:
            print(f"  - {report['username']}: {report['reason']}")


if __name__ == "__main__":
    main()
