"""
Admin tool: permanently delete one account and all of its data.

Run: python scripts/delete_user.py <username>          # dry run, shows what would go
     python scripts/delete_user.py <username> --apply  # actually delete

Removes every per-user table row, the user_profile row, and the
users/<user_uuid>/ directory, as one transaction (see
database.delete_user_account). Anyone this user referred keeps their account;
only their referred_by pointer is cleared.

Deliberately a script, not an HTTP endpoint : same reasoning as
grant_tester_access.py and promote_waitlist.py: there is no admin-auth concept
in this codebase. A self-service "delete my account" route for users is a
separate thing and does not exist yet.

Note: this does not touch the pre-launch landing-page email list
(the landing_waitlist table, see app/landing_waitlist_db.py). That is a
separate marketing capture with no account linkage; clear an address from
it with landing_waitlist_db directly if a deletion request covers it too.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    username = args[0]
    apply_it = "--apply" in sys.argv[1:]

    try:
        result = database.delete_user_account(username, dry_run=not apply_it)
    except ValueError as e:
        print(e)
        sys.exit(1)

    mode = "DELETED" if apply_it else "would delete"
    print(f"\n{result['username']}  ({result['user_uuid']})\n")
    for table, n in result["counts"].items():
        if not n:
            continue
        if table == "referrals_orphaned":
            print(f"  {n} referred user(s) keep their account, referred_by cleared")
        else:
            print(f"  {mode}: {n:>4} row(s) in {table}")
    if result["dir_removed"]:
        print(f"  {mode}: users/{result['user_uuid']}/")

    if not apply_it:
        print("\nDry run : re-run with --apply to delete for real.")
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
