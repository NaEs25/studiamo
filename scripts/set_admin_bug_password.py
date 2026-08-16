"""
Admin tool: set (or change) the password that gates admin controls on the
public bug tracker (/dev/bugs) -- viewing real usernames, viewing captured
diagnostic context, and editing/resolving/deleting reports.

Run: python scripts/set_admin_bug_password.py

Stores a sha256 hash in app_settings (key "admin_bug_password_hash"), the
same key/value table database.get_max_users() already reads from. Deliberately
not an env var: changing the password later just means re-running this script,
no redeploy/restart required. Deliberately not tied to a user_profile account
either -- this is a single shared secret independent of the per-user login
system, checked by app.dependencies.require_admin_auth.
"""
import sys
import hashlib
from getpass import getpass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database


def main():
    password = getpass("New admin password: ")
    if not password.strip():
        print("Password cannot be empty.")
        sys.exit(1)

    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.")
        sys.exit(1)

    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    database.set_app_setting("admin_bug_password_hash", password_hash)
    print("Admin bug-tracker password updated.")


if __name__ == "__main__":
    main()
