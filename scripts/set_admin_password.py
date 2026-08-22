"""
Admin tool: set (or change) the shared admin password.

That password now gates two things, which is why it is no longer named after
the first of them:
  * the bug tracker's admin controls (/dev/bugs) -- real usernames, captured
    diagnostic context, and editing or deleting reports;
  * the Users page in the private admin cockpit, which searches every account
    by email and can grant or end tester access.

Run: python scripts/set_admin_password.py

Stores a bcrypt hash in app_settings (key "admin_password_hash"), the same
key/value table database.get_max_users() already reads from. Deliberately not
an env var: changing the password later just means re-running this script, no
redeploy or restart required. Deliberately not tied to a user_profile account
either -- this is a single shared secret independent of the per-user login
system, checked by app.dependencies.require_admin_auth.

The previous version of this script stored an unsalted SHA-256 digest under
"admin_bug_password_hash". Both are still accepted at login and a legacy hash
is rewritten as bcrypt on the next successful login, so running this is a
tidy-up rather than a migration you have to perform.
"""
import sys
from getpass import getpass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database
from app.dependencies import hash_password, ADMIN_PASSWORD_SETTING_KEY


def main():
    password = getpass("New admin password: ")
    if not password.strip():
        print("Password cannot be empty.")
        sys.exit(1)

    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.")
        sys.exit(1)

    database.set_app_setting(ADMIN_PASSWORD_SETTING_KEY, hash_password(password))
    print(f"Admin password updated (bcrypt, app_settings.{ADMIN_PASSWORD_SETTING_KEY}).")
    print("It gates both /dev/bugs admin controls and the cockpit Users page.")


if __name__ == "__main__":
    main()
