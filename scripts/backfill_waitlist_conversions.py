"""
Admin tool: stamp landing_waitlist.converted_at for leads who already have an active account.

Run: python scripts/backfill_waitlist_conversions.py           # dry run, shows what would change
     python scripts/backfill_waitlist_conversions.py --apply   # actually stamp

One-off catch-up for rows created before converted_at existed. From now on the column is set
as it happens: scripts/promote_waitlist.py stamps it on promotion, and google_callback stamps
it when a signup goes straight to active because a spot was free.

Only accounts with status = 'active' are stamped. Someone whose account is still on the
waitlist is genuinely still waiting, and marking them converted would drop them out of exactly
the mailing they are owed. Rows already carrying a converted_at keep their original timestamp.

Deliberately a script, not an HTTP endpoint : same reasoning as promote_waitlist.py and
grant_tester_access.py, there is no admin-auth concept in this codebase and this is a
low-frequency action a human runs by hand.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from psycopg2.extras import RealDictCursor

from app import database

# Matches a lead to an account on either address an account can be reached at, since the
# lead may have been captured by the marketing form under one and the Google identity under
# the other.
MATCH = """
      FROM landing_waitlist lw
      JOIN user_profile up
        ON LOWER(lw.email) = LOWER(up.email)
        OR LOWER(lw.email) = LOWER(up.google_email)
     WHERE up.status = 'active'
       AND lw.converted_at IS NULL
"""


def main():
    apply_it = "--apply" in sys.argv[1:]

    conn = database.get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(f"SELECT lw.email AS lead_email, up.username {MATCH} ORDER BY lw.id;")
        pending = cursor.fetchall()

        if not pending:
            print("Nothing to backfill: every lead with an active account is already stamped.")
            return

        print(f"{len(pending)} lead(s) with an active account and no converted_at:")
        for row in pending:
            print(f"  - {row['lead_email']}  ->  {row['username']}")

        if not apply_it:
            print("\nDry run : re-run with --apply to stamp these.")
            return

        cursor.execute(
            f"UPDATE landing_waitlist SET converted_at = NOW() "
            f"WHERE id IN (SELECT lw.id {MATCH});"
        )
        print(f"\nStamped {cursor.rowcount} row(s).")
    finally:
        database.release_pooled_connection(conn)


if __name__ == "__main__":
    main()
