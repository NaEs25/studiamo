"""
Public pre-launch landing-page email waitlist (marketing email capture on
/landing, no account, no login).

Not to be confused with the account-level waitlist status ('active' vs
'waitlist' on user_profile) used to gate real Google-SSO signups once the
registered-user cap is reached, that's a completely separate system living
in user_profile. This module only ever deals with bare email addresses
collected before launch.

Stored in the `landing_waitlist` table (see app/schema.py), in the same
Supabase Postgres database as everything else, kept separate from any
user's personal account data by table, not by database.
"""

from typing import Optional

from app.database import get_pooled_raw_connection, ConnectionWrapper


def get_waitlist_db() -> ConnectionWrapper:
    """Borrows a pooled Supabase Postgres connection for the landing_waitlist table."""
    return ConnectionWrapper(get_pooled_raw_connection())


def record_waitlist_lead(
    email: str,
    user_uuid: str,
    referrer: Optional[str] = None,
    country: Optional[str] = None,
    user_agent: Optional[str] = None,
    preference: str = "google_oauth",
) -> None:
    """Records a Google-SSO account-waitlist signup into landing_waitlist, the
    same table the pre-launch marketing form (app/routers/landing_waitlist.py)
    uses. Upserts on email so a lead who already exists (e.g. joined the
    marketing list first) is linked to their real account uuid rather than
    duplicated. Only `uuid` is overwritten on conflict, the existing row's
    email-delivery tracking columns (email_sent, *_sent_at, emails_sent_count,
    unsubscribed) are left untouched.
    """
    conn = get_waitlist_db()
    try:
        conn.execute(
            """
            INSERT INTO landing_waitlist (uuid, email, preference, referrer, country, user_agent)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (email) DO UPDATE SET uuid = EXCLUDED.uuid;
            """,
            (user_uuid, email, preference, referrer, country, user_agent),
        )
        conn.commit()
    finally:
        conn.close()


def mark_waitlist_converted(*emails: str) -> int:
    """Stamps converted_at on the lead row(s) for an account that is now off the waitlist and
    active. Returns how many rows were stamped. Idempotent: an already-stamped row keeps its
    original timestamp, so re-running a promotion never rewrites history.

    Kept separate from mark_waitlist_email_sent('spot_ready') on purpose. That one records
    that an email was delivered; this one records that the person can actually use the
    product. They come apart whenever a send fails, and it is this fact, not the delivery,
    that a later mailer has to filter on. Stamping only on successful delivery would leave a
    promoted user looking identical to someone still waiting, and mail them accordingly.

    Takes several addresses because an account can be reached at either `email` or
    `google_email`, and the lead may have been captured under either one.
    """
    candidates = [e.strip().lower() for e in emails if e and e.strip()]
    if not candidates:
        return 0
    conn = get_waitlist_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE landing_waitlist SET converted_at = NOW() "
            "WHERE LOWER(email) = ANY(?) AND converted_at IS NULL;",
            (candidates,),
        )
        stamped = cursor.rowcount
        conn.commit()
        return stamped
    finally:
        conn.close()


def mark_waitlist_email_sent(email: str, email_type: str) -> None:
    """Stamps a landing_waitlist row after an email actually sent successfully,
    so retries stay safe and delivery is auditable. `email_type` is
    'confirmation' (account-waitlist signup email) or 'spot_ready' (promotion
    email sent by scripts/promote_waitlist.py). No-op if no row matches the
    email, callers aren't required to have called record_waitlist_lead first.
    """
    conn = get_waitlist_db()
    try:
        if email_type == "confirmation":
            conn.execute(
                "UPDATE landing_waitlist SET email_sent = TRUE, confirmation_sent_at = NOW(), "
                "emails_sent_count = COALESCE(emails_sent_count, 0) + 1 WHERE email = ?;",
                (email,),
            )
        elif email_type == "spot_ready":
            conn.execute(
                "UPDATE landing_waitlist SET spot_ready_sent_at = NOW(), "
                "emails_sent_count = COALESCE(emails_sent_count, 0) + 1 WHERE email = ?;",
                (email,),
            )
        else:
            raise ValueError(f"Unknown email_type: {email_type!r}")
        conn.commit()
    finally:
        conn.close()
