"""
One-off migration: give every legacy tester an explicit, time-boxed grant.

Run:
    python scripts/backfill_tester_access.py --dry-run          # always do this first
    python scripts/backfill_tester_access.py                    # 14 days from today
    python scripts/backfill_tester_access.py --days 30
    python scripts/backfill_tester_access.py --only <username>

Before grants were time-boxed, tester access was a single boolean on
user_profile. Accounts still in that state (is_tester TRUE, no tester_access
row) are grandfathered by database.has_app_access(), so they keep working
indefinitely and nothing is broken by leaving them alone. This script is what
converts them into real grants with an end date.

The clock starts the day this runs, NOT at signup. Backdating to created_at
would expire long-standing testers the instant the script finished, which is
the one outcome the grandfather path exists to prevent. There is deliberately
no flag to backdate.

Anyone who should keep access indefinitely should be granted --unlimited via
scripts/grant_tester_access.py BEFORE this runs: accounts that already have a
grant row are skipped, so an unlimited grant made first wins.

DO NOT RUN THIS until existing testers have been told their access is now
time-boxed. There is no rush: the grandfather path means nobody is cut off
while you wait.
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from psycopg2.extras import RealDictCursor

from app import database


def _find_legacy_testers(cursor, only=None):
    """Accounts with the flag set but no grant row of any kind."""
    sql = """
        SELECT p.username, p.user_uuid, p.created_at
          FROM user_profile p
         WHERE p.is_tester IS TRUE
           AND NOT EXISTS (SELECT 1 FROM tester_access t WHERE t.user_uuid = p.user_uuid)
    """
    params = []
    if only:
        sql += " AND LOWER(p.username) = LOWER(%s)"
        params.append(only)
    sql += " ORDER BY p.created_at;"
    cursor.execute(sql, params)
    return cursor.fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=None,
                        help="Grant length in days (default: app_settings tester_default_period_days).")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change; write nothing.")
    parser.add_argument("--only", metavar="USERNAME", help="Backfill a single account.")
    args = parser.parse_args()

    days = args.days
    if days is None:
        days = database.get_tester_period_setting(
            "tester_default_period_days", database._TESTER_DEFAULT_PERIOD_DAYS
        )
    if days <= 0:
        parser.error("--days must be positive. This script does not create unlimited grants; "
                     "use scripts/grant_tester_access.py --unlimited for those.")

    conn = database.get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        rows = _find_legacy_testers(cursor, args.only)
    finally:
        database.release_pooled_connection(conn)

    if not rows:
        print("No legacy testers found. Nothing to do.")
        return

    print(f"{len(rows)} legacy tester(s) found. Each would receive {days} day(s) from today.\n")
    for row in rows:
        print(f"  {row['username']:<30} tester since {row['created_at']:%Y-%m-%d}")

    if args.dry_run:
        print("\nDry run: nothing was written. Re-run without --dry-run to apply.")
        return

    print()
    confirm = input(f"Grant {days} days to {len(rows)} account(s)? Type 'yes' to proceed: ")
    if confirm.strip().lower() != "yes":
        print("Aborted. Nothing was written.")
        return

    failures = []
    for row in rows:
        try:
            state = database.grant_tester_access(
                row["username"], days=days, granted_by="backfill",
                note="Backfilled from legacy is_tester flag",
            )
            print(f"  {row['username']:<30} -> until {state['expires_at']:%Y-%m-%d}")
        except Exception as e:
            failures.append((row["username"], e))
            print(f"  {row['username']:<30} -> FAILED: {e}")

    print(f"\nDone. {len(rows) - len(failures)} granted, {len(failures)} failed.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
