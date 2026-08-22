"""
Promoting a waitlist account to active, and everything that has to happen with it.

Promotion is not one UPDATE. It is four steps, and three of them are about telling people:

  1. user_profile.status -> 'active', which is what lets the account sign in at all.
  2. landing_waitlist.converted_at, so a later mailer stops treating them as a prospect.
  3. The "your spot is ready" email, without which the person is never told and simply
     waits for something that already happened.
  4. landing_waitlist, spot_ready stamp, so the send is auditable and retries stay safe.

Doing only the first produces an account that is active but silent: the person keeps
waiting, and the marketing list keeps counting them as someone still to convert. That is
the failure this module exists to make impossible, by being the one place both the CLI
(scripts/promote_waitlist.py) and the admin panel call.

Step 2 runs BEFORE the send and regardless of whether it succeeds. The account is already
active at that point, so a lead row still reading "waiting" is wrong the moment the UPDATE
committed, and a failed email must not be what decides whether someone counts as converted.
"""
import logging

from app import database, email_utils, landing_waitlist_db

logger = logging.getLogger("studiamo")


def notify_promoted(row: dict, send_email: bool = True) -> dict:
    """Steps 2 to 4 for an account that has just been promoted.

    Takes the row returned by either promotion query, so the bulk path
    (promote_next_n_users, used by the CLI) and the single-account path
    (promote_user_to_active, used by the admin panel) run identical follow-through rather
    than each keeping its own copy that can fall behind.

    Returns the same report shape as promote_and_notify."""
    username = row["username"]

    # google_email first, matching every other address decision in the app. It is the
    # address tied to the identity the account signs in with; `email` is a copy that can
    # hold a hand-seeded value with nothing behind it, so preferring it can mail an inbox
    # nobody reads.
    recipient = row.get("google_email") or row.get("email")

    # Before the send, and independent of it. See the module docstring.
    try:
        landing_waitlist_db.mark_waitlist_converted(row.get("google_email"), row.get("email"))
    except Exception as e:
        # The account is active either way; a lead-table stamp must not undo that or raise
        # into the caller as though the promotion failed.
        logger.warning(f"[promotion] converted_at stamp failed for {username}: {e}")

    report = {"promoted": True, "username": username, "recipient": recipient,
              "email_sent": False, "reason": None}

    if not send_email:
        report["reason"] = "Promoted without sending the email, as requested."
        return report

    if not recipient:
        report["reason"] = "No email address on file, so nothing was sent."
        logger.warning(f"[promotion] {username} promoted with no address on file.")
        return report

    try:
        sent = email_utils.send_promotion_email(recipient)
    except Exception as e:
        logger.error(f"[promotion] Promotion email raised for {username}: {e}")
        report["reason"] = "Promoted, but the email could not be sent. See the logs."
        return report

    report["email_sent"] = bool(sent)
    if sent:
        try:
            landing_waitlist_db.mark_waitlist_email_sent(recipient, "spot_ready")
        except Exception as e:
            logger.warning(f"[promotion] spot_ready stamp failed for {username}: {e}")
    else:
        report["reason"] = "Promoted, but the email could not be sent. See the logs."

    return report


def promote_and_notify(user_uuid: str, send_email: bool = True) -> dict:
    """Promotes one specific waitlist account and runs the full follow-through.

    Returns a report of what actually happened rather than a bare success flag, because
    "promoted" and "the person knows" are different facts and the caller has to be able to
    tell the operator which ones are true:

        {"promoted": bool, "username": str|None, "recipient": str|None,
         "email_sent": bool, "reason": str|None}

    `reason` is set whenever something did not happen: the account was not on the waitlist,
    there was no address on file, or the send failed. It is meant to be shown, not logged
    and swallowed."""
    row = database.promote_user_to_active(user_uuid)
    if not row:
        # Already active, or no such account. Deliberately not an error: a double click
        # should be a no-op, not a second email to someone promoted a week ago.
        return {"promoted": False, "username": None, "recipient": None,
                "email_sent": False, "reason": "Account was not on the waitlist."}
    return notify_promoted(row, send_email=send_email)
