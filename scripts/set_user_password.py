"""
Admin CLI tool: Set or reset a local user's password in self-hosted mode.

Usage:
  python scripts/set_user_password.py <username> [password]

If password is not provided on the command line, prompts interactively.
"""
import sys
import hashlib
from getpass import getpass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database, config


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/set_user_password.py <username> [password]")
        sys.exit(1)

    raw_username = sys.argv[1].strip()
    sanitized = "".join(c for c in raw_username if c.isalnum() or c in ("-", "_")).strip().lower()

    users = database.get_all_users()
    matched = [u for u in users if u.lower() == sanitized]
    if not matched:
        print(f"User '{raw_username}' not found in database. Existing users: {users}")
        sys.exit(1)

    username = matched[0]

    if len(sys.argv) >= 3:
        password = sys.argv[2]
    else:
        password = getpass(f"New password for '{username}': ")
        if not password.strip():
            print("Password cannot be empty.")
            sys.exit(1)
        confirm = getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.")
            sys.exit(1)

    password_hash = hashlib.sha256(password.strip().encode("utf-8")).hexdigest()
    config.write_user_config(username, {"PASSWORD_HASH": password_hash})
    print(f"Password updated successfully for user '{username}'.")


if __name__ == "__main__":
    main()
