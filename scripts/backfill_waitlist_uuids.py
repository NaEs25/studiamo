"""
Admin tool: make landing_waitlist.uuid mean one thing, the account that owns the address.

Run: python scripts/backfill_waitlist_uuids.py           # dry run, shows what would change
     python scripts/backfill_waitlist_uuids.py --apply   # actually write

The column used to hold two different kinds of value. record_waitlist_lead writes the real
user_uuid, but the landing form minted a throwaway UUIDv4 for a visitor who had no account,
and a lead who later signed up while a spot was free kept that throwaway forever. Nothing
reads the id back, so the mismatch was invisible until you tried to join on it.

Afterwards the rule is: uuid = the user_uuid of the account owning this email, or NULL when
no account exists. Two passes, both idempotent:

  link    a lead whose email matches an account gets that account's user_uuid
  clear   a lead with no account loses its throwaway id

Collisions are reported, not forced. uuid is UNIQUE, so if one account holds two captured
addresses only the first row can carry the id; the email match that every real query uses
still finds both.

Deliberately a script, not an HTTP endpoint : same reasoning as promote_waitlist.py.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from psycopg2.extras import RealDictCursor

from app import database


def main():
    apply_it = "--apply" in sys.argv[1:]

    conn = database.get_pooled_raw_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Pass 1: rows that should carry an account's uuid but do not.
        # Ordered so that when one account captured two addresses, the google_email row is
        # the one that gets the id. That address is tied to the identity the account signs
        # in with; `email` is a copy that can diverge. Same precedence the app uses for
        # billing, notifications and the promotion email.
        cursor.execute("""
            SELECT lw.id, lw.email, lw.uuid AS current_uuid,
                   up.user_uuid::text AS account_uuid, up.username,
                   (LOWER(lw.email) = LOWER(up.google_email)) AS is_google_address
              FROM landing_waitlist lw
              JOIN user_profile up
                ON LOWER(lw.email) = LOWER(up.email)
                OR LOWER(lw.email) = LOWER(up.google_email)
             WHERE lw.uuid IS DISTINCT FROM up.user_uuid::text
             ORDER BY (LOWER(lw.email) = LOWER(up.google_email)) DESC, lw.id;
        """)
        to_link = cursor.fetchall()

        # A uuid can sit on only one row. Two ways that bites, and both have to be caught or
        # the UPDATE below dies on the unique index: another row may already hold this
        # account's id from an earlier run, or two rows in this same batch may claim it.
        cursor.execute("SELECT uuid, id FROM landing_waitlist WHERE uuid IS NOT NULL;")
        held = {r["uuid"]: r["id"] for r in cursor.fetchall()}

        seen, linkable, collisions = set(), [], []
        for row in to_link:
            taken_by = held.get(row["account_uuid"])
            if row["account_uuid"] in seen or (taken_by is not None and taken_by != row["id"]):
                collisions.append(row)
            else:
                linkable.append(row)
                seen.add(row["account_uuid"])

        # Pass 2: throwaway ids on rows that have no account at all.
        cursor.execute("""
            SELECT lw.id, lw.email, lw.uuid
              FROM landing_waitlist lw
         LEFT JOIN user_profile up
                ON LOWER(lw.email) = LOWER(up.email)
                OR LOWER(lw.email) = LOWER(up.google_email)
             WHERE up.user_uuid IS NULL AND lw.uuid IS NOT NULL
             ORDER BY lw.id;
        """)
        to_clear = cursor.fetchall()

        if not linkable and not to_clear and not collisions:
            print("Nothing to do: every uuid already names its account, or is NULL.")
            return

        if linkable:
            print(f"LINK, {len(linkable)} row(s) get their account's user_uuid:")
            for r in linkable:
                was = r["current_uuid"] or "NULL"
                print(f"  id {r['id']:<4} {r['email']:34} {was[:8]}… -> {r['account_uuid'][:8]}…  ({r['username']})")
            print()

        if to_clear:
            print(f"CLEAR, {len(to_clear)} row(s) have no account and lose a throwaway id:")
            for r in to_clear:
                print(f"  id {r['id']:<4} {r['email']:34} {r['uuid'][:8]}… -> NULL")
            print()

        if collisions:
            print(f"SKIPPED, {len(collisions)} row(s) whose account is already claimed by an earlier row:")
            for r in collisions:
                why = "google address already linked" if not r["is_google_address"] else "another row holds this id"
                print(f"  id {r['id']:<4} {r['email']:34} ({r['username']}) : {why}, matched by email instead")
            print()

        if not linkable and not to_clear:
            print("Nothing to write: the rows above are all resolved by email instead.")
            return

        if not apply_it:
            print("Dry run : re-run with --apply to write these.")
            return

        for r in linkable:
            cursor.execute("UPDATE landing_waitlist SET uuid = %s WHERE id = %s;",
                           (r["account_uuid"], r["id"]))
        if to_clear:
            cursor.execute("UPDATE landing_waitlist SET uuid = NULL WHERE id = ANY(%s);",
                           ([r["id"] for r in to_clear],))

        print(f"Linked {len(linkable)} row(s), cleared {len(to_clear)}.")
    finally:
        database.release_pooled_connection(conn)


if __name__ == "__main__":
    main()
