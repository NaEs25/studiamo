"""
Admin tool: manage the tester period for one account.

Run:
    python scripts/grant_tester_access.py <username>                 # grant the default period
    python scripts/grant_tester_access.py <username> --days 30       # grant a specific length
    python scripts/grant_tester_access.py <username> --unlimited     # grant with no end date
    python scripts/grant_tester_access.py <username> --extend 7      # add days to the current grant
    python scripts/grant_tester_access.py <username> --end           # end the period now
    python scripts/grant_tester_access.py <username> --status        # print state, write nothing
    python scripts/grant_tester_access.py <username> --no-email      # grant without telling them

Tester access lets an account use the cloud app without a subscription
(database.has_app_access(), enforced by the require_app_access dependency).
Grants are time-boxed: see the tester_access table in app/schema.py.

An unlimited grant is only ever created by the explicit --unlimited flag.
`--days 0` is rejected: 0 and 1 mean very different things, and a stray
keystroke between them should not silently grant access forever.

A grant emails the account holder by default, through app/tester_notify.py,
which the admin panel uses too. --no-email is for your own accounts: skipping
it otherwise leaves someone with a test period they were never told about.
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import database, tester_notify


def _describe(username: str, state: dict) -> str:
    """One-line summary of a tester state, always naming the end date when there is one."""
    kind = state["state"]
    if kind == "none":
        return f"{username}: not a tester."
    if state["legacy"]:
        return (f"{username}: tester (legacy flag, no grant row, no end date). "
                f"Run scripts/backfill_tester_access.py to make this explicit.")
    if kind == "active" and state["unlimited"]:
        return f"{username}: tester with no end date."
    if kind == "active":
        return (f"{username}: tester until {state['expires_at']:%Y-%m-%d %H:%M UTC} "
                f"({state['days_left']} day(s) left).")
    if kind == "expired":
        return f"{username}: tester period ended on {state['expires_at']:%Y-%m-%d %H:%M UTC}."
    if kind == "revoked":
        return f"{username}: tester access was ended by an admin."
    return f"{username}: {kind}."


def main():
    parser = argparse.ArgumentParser(
        description="Grant, extend, or end tester access for one account.",
        epilog="Use --unlimited for a grant with no end date; --days 0 is rejected.",
    )
    parser.add_argument("username")
    parser.add_argument("--days", type=int, help="Length of the grant in days.")
    parser.add_argument("--unlimited", action="store_true", help="Grant with no end date.")
    parser.add_argument("--extend", type=int, metavar="N", help="Add N days to the current grant.")
    parser.add_argument("--end", action="store_true", help="End the tester period now.")
    parser.add_argument("--status", action="store_true", help="Print state and exit.")
    parser.add_argument("--note", help="Internal note stored with the grant.")
    parser.add_argument("--no-email", action="store_true",
                        help="Grant without emailing the account holder.")
    args = parser.parse_args()

    if args.days is not None and args.days == 0:
        parser.error("--days 0 is not accepted. Use --unlimited to grant access with no end date.")
    if args.days is not None and args.unlimited:
        parser.error("--days and --unlimited are mutually exclusive.")

    actions = [bool(args.extend), args.end, args.status,
               args.unlimited or args.days is not None]
    if sum(actions) > 1:
        parser.error("Choose one action at a time.")

    report = None
    try:
        if args.status:
            state = database.get_tester_state(args.username)
        elif args.end:
            state = database.end_tester_access(args.username, reason="ended via CLI")
        elif args.extend:
            state = database.extend_tester_access(args.username, args.extend, extended_by="cli")
        else:
            days = 0 if args.unlimited else args.days
            report = tester_notify.grant_and_notify(
                args.username, days=days, granted_by="cli", note=args.note,
                send_email=not args.no_email,
            )
            state = report["state"]
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if args.status and state["state"] == "none":
        print(f"No tester access for '{args.username}' (or no such account).")
        sys.exit(0 if args.status else 1)

    print(_describe(args.username, state))
    # Printed after the state, and only for a grant: whether the person was told is a second
    # fact about the same action, and a silent grant is the failure worth noticing here.
    if report is not None:
        if report["email_sent"]:
            print(f"Emailed {report['recipient']}.")
        else:
            print(report["reason"] or "No email was sent.")


if __name__ == "__main__":
    main()
