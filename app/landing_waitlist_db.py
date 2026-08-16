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

from app.database import get_pooled_raw_connection, ConnectionWrapper


def get_waitlist_db() -> ConnectionWrapper:
    """Borrows a pooled Supabase Postgres connection for the landing_waitlist table."""
    return ConnectionWrapper(get_pooled_raw_connection())
