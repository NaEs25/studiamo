"""
Admin tool: grant or revoke free tester access for one account.

Run: python scripts/grant_tester_access.py <username> [--revoke]

Deliberately a script, not an HTTP endpoint : same reasoning as
promote_waitlist.py: no admin-auth concept in this codebase, and this is a
low-frequency action a human runs by hand.

Tester access lets an account use the app without an active subscription
(database.has_app_access()). Not enforced on any route yet.
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
    grant = "--revoke" not in sys.argv[1:]

    updated = database.set_tester_access(username, grant)
    if not updated:
        print(f"No user_profile row found for '{username}'.")
        sys.exit(1)

    print(f"{username}: tester access {'granted' if grant else 'revoked'}.")


if __name__ == "__main__":
    main()
