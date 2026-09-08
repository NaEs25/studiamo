"""
Telling someone that they have tester access, and recording that they were told.

Granting is one INSERT. Being a tester is not, because access nobody knows about is access
nobody uses:

  1. The tester_access row plus the user_profile.is_tester cache, which is what actually
     lets the account into the app. Written by the caller, not here.
  2. The "you're in the test group" email, which is the only thing that reaches a person
     who has no reason to open the app today.
  3. tester_access.notified_at, so the send is auditable and a second grant on the same
     account can be told apart from a repeat of the first.

Step 1 alone produces a silent grant: the person keeps not using Studiamo, the test period
runs down anyway, and the expiry survey asks for an opinion about something they never
opened. The in-app welcome (tester_access.welcome_seen_at, see database._derive_tester_state)
only fires for someone already in the app, so it cannot cover this.

This module exists because three places grant tester access: app/database.py's
grant_tester_access (via scripts/grant_tester_access.py), and the admin cockpit's Users page,
which deliberately keeps its own copy of the SQL. Without one shared follow-through, one of
them mails people and the others quietly do not.

Every function takes an optional `conn` for the same reason app/promotion.py does: the admin
cockpit administers production from inside a staging process, so the stamp has to land on the
database the grant landed on rather than on whichever one this process is wired to. The email
is the only step with no database behind it, which is what makes that possible.

The send happens after the grant is committed, never inside its transaction. An email about
a grant that then rolled back cannot be recalled, whereas a grant with no email is visible as
notified_at IS NULL and can simply be sent again.
"""
import logging

from app import database, email_utils

logger = logging.getLogger("studiamo")


def notify_granted(row: dict, send_email: bool = True, conn=None) -> dict:
    """Steps 2 and 3 for an account that has just been granted tester access.

    `row` carries what the grant produced, whichever path produced it:
        username, google_email, email, grant_id, expires_at (None when unlimited)

    Returns what actually happened rather than a bare success flag, because "granted" and
    "the person knows" are different facts and the caller has to be able to tell the operator
    which ones are true:

        {"username": str, "recipient": str|None, "email_sent": bool,
         "email_skipped": bool, "reason": str|None}

    `reason` is set whenever the email did not go out: not wanted, no address on file, or the
    send failed. It is meant to be shown, not logged and swallowed.

    `email_skipped` separates the one of those the operator already knows about from the two
    they do not. Without it a surface has only the reason text to go on, and either shows
    "as requested" as though something had gone wrong or matches on a sentence."""
    username = row.get("username")

    # google_email first, matching every other address decision in the app. It is the address
    # tied to the identity the account signs in with; `email` is a copy that can hold a
    # hand-seeded value with nothing behind it, so preferring it can mail an inbox nobody reads.
    recipient = row.get("google_email") or row.get("email")

    report = {"username": username, "recipient": recipient, "email_sent": False,
              "email_skipped": False, "reason": None}

    if not send_email:
        report["email_skipped"] = True
        report["reason"] = "Granted without sending the email, as requested."
        return report

    if not recipient:
        report["reason"] = "No email address on file, so nothing was sent."
        logger.warning(f"[tester_notify] {username} granted tester access with no address on file.")
        return report

    try:
        sent = email_utils.send_tester_access_email(recipient, expires_at=row.get("expires_at"))
    except Exception as e:
        # The grant is already committed at this point. A failed send must not raise into the
        # caller as though the access itself had failed.
        logger.error(f"[tester_notify] Tester access email raised for {username}: {e}")
        report["reason"] = "Granted, but the email could not be sent. See the logs."
        return report

    report["email_sent"] = bool(sent)
    if sent:
        try:
            database.mark_tester_notified(row.get("grant_id"), conn=conn)
        except Exception as e:
            logger.warning(f"[tester_notify] notified_at stamp failed for {username}: {e}")
    else:
        report["reason"] = "Granted, but the email could not be sent. See the logs."

    return report


def grant_and_notify(username: str, days: int = None, granted_by: str = None,
                     note: str = None, send_email: bool = True) -> dict:
    """Grants tester access through app.database and runs the full follow-through.

    The path for anything inside the main app process (currently
    scripts/grant_tester_access.py). The admin cockpit calls notify_granted directly, because
    it writes the grant with its own SQL on its own connection.

    Returns the notify_granted report with the resulting tester state under "state", so the
    caller can report the period and whether the person was told from one value."""
    state = database.grant_tester_access(username, days=days, granted_by=granted_by, note=note)

    contact = database.get_account_contact(username) or {"username": username}
    report = notify_granted(
        {**contact,
         "grant_id": state.get("grant_id"),
         "expires_at": state.get("expires_at")},
        send_email=send_email,
    )
    report["state"] = state
    return report
