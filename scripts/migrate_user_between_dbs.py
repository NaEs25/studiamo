"""
Admin tool: migrate one user account and all associated database records between PostgreSQL databases (e.g., Prod -> Staging or Staging -> Prod).

Connection URLs are read from SOURCE_DB_URL / TARGET_DB_URL environment variables by default
(so credentials don't end up in shell history or `ps aux`). --from-url/--to-url are accepted
as an override for one-off use.

Usage:
  SOURCE_DB_URL=... TARGET_DB_URL=... python scripts/migrate_user_between_dbs.py <username> [--apply]

Examples:
  # Dry run (verify rows to migrate without writing)
  SOURCE_DB_URL="postgres://..." TARGET_DB_URL="postgres://..." python scripts/migrate_user_between_dbs.py alice

  # Apply migration (copies rows to target DB and deletes from source DB)
  SOURCE_DB_URL="postgres://..." TARGET_DB_URL="postgres://..." python scripts/migrate_user_between_dbs.py alice --apply
"""

import argparse
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Order matters for foreign key constraint dependencies. import_timings is intentionally
# excluded: it has no user_uuid column at all, it's global app analytics, not per-user data.
USER_DATA_TABLES = [
    "user_profile",
    "srs_settings",
    "goals",
    "videos",
    "quizzes",
    "quiz_attempts",
    "ai_usage_logs",
    "daily_recommendations",
    "dismissed_recommendations",
    "goal_recommendations",
    "import_tasks",
    "push_subscriptions",
    "bugs",
]


def migrate_user(username: str, source_url: str, target_url: str, apply_changes: bool = False):
    src_conn = psycopg2.connect(source_url, cursor_factory=RealDictCursor)
    tgt_conn = psycopg2.connect(target_url, cursor_factory=RealDictCursor)

    try:
        src_cur = src_conn.cursor()
        tgt_cur = tgt_conn.cursor()

        # 1. Fetch user_uuid from source user_profile
        src_cur.execute("SELECT user_uuid FROM user_profile WHERE LOWER(username) = LOWER(%s);", (username,))
        row = src_cur.fetchone()
        if not row:
            raise ValueError(f"User '{username}' not found in source database.")
        user_uuid = row["user_uuid"]

        print(f"\nFound user '{username}' (UUID: {user_uuid}) in source database.")
        print("=" * 60)

        # This tool moves an account, it does not merge one. If the UUID already exists on
        # the target, copying with ON CONFLICT DO NOTHING would silently skip rows while the
        # source delete goes ahead anyway, which is a quiet way to lose data. Refuse instead.
        tgt_cur.execute("SELECT 1 FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
        if tgt_cur.fetchone():
            raise ValueError(
                f"User '{username}' (UUID: {user_uuid}) already exists in the target database. "
                "Refusing to migrate: this tool does not merge accounts."
            )

        # 2. Collect and migrate rows for each table
        copied_counts = {}
        inserted_counts = {}

        for table in USER_DATA_TABLES:
            if table == "bugs":
                src_cur.execute("SELECT * FROM bugs WHERE LOWER(username) = LOWER(%s);", (username,))
            else:
                src_cur.execute(f"SELECT * FROM {table} WHERE user_uuid = %s;", (user_uuid,))

            rows = src_cur.fetchall()
            copied_counts[table] = len(rows)

            if apply_changes and rows:
                cols = list(rows[0].keys())
                col_names = ", ".join(cols)
                placeholders = ", ".join(["%s"] * len(cols))

                # Upsert query. Conflicts are tracked below via rowcount, not assumed away.
                insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;"

                inserted = 0
                for r in rows:
                    values = [r[c] for c in cols]
                    tgt_cur.execute(insert_sql, values)
                    inserted += tgt_cur.rowcount
                inserted_counts[table] = inserted

            mode_str = "Copied" if apply_changes else "Would copy"
            print(f"  {mode_str} {len(rows):>4} row(s) in '{table}'")

        if apply_changes:
            short_tables = [t for t in USER_DATA_TABLES if inserted_counts.get(t, 0) < copied_counts[t]]
            if short_tables:
                tgt_conn.rollback()
                print("\nAborting: some rows already existed in the target database and were skipped:")
                for t in short_tables:
                    print(f"  '{t}': fetched {copied_counts[t]}, inserted {inserted_counts.get(t, 0)}")
                print("\nNo changes were made to the target or source database. Investigate the")
                print("conflicting rows in the target before retrying.")
                return

            # Rows were inserted with explicit ids copied from the source. That doesn't
            # advance the target's SERIAL sequences, so a later ordinary insert could
            # generate an id that collides with one of these migrated rows. Advance each
            # sequence past the current max, but never move it backward (pg_get_serial_sequence
            # returns NULL for tables without a serial id column, e.g. bugs, and is skipped).
            for table in USER_DATA_TABLES:
                if copied_counts[table] == 0:
                    continue
                tgt_cur.execute("SELECT pg_get_serial_sequence(%s, 'id');", (table,))
                seq_name = tgt_cur.fetchone()["pg_get_serial_sequence"]
                if not seq_name:
                    continue
                tgt_cur.execute(
                    f"SELECT setval(%s, GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), "
                    f"(SELECT last_value FROM {seq_name})));",
                    (seq_name,),
                )

            tgt_conn.commit()
            print("\nSuccessfully written rows to target database.")

            # Delete rows from source DB in reverse dependency order
            print("\nCleaning up source database...")
            for table in reversed(USER_DATA_TABLES):
                if table == "bugs":
                    src_cur.execute("DELETE FROM bugs WHERE LOWER(username) = LOWER(%s);", (username,))
                else:
                    src_cur.execute(f"DELETE FROM {table} WHERE user_uuid = %s;", (user_uuid,))
                deleted = src_cur.rowcount
                print(f"  Deleted {deleted:>4} row(s) from '{table}'")

            src_conn.commit()
            print("\nMigration complete! User successfully transferred.")
        else:
            print("\nDry run completed. Run with --apply to execute migration.")

    finally:
        src_conn.close()
        tgt_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate a user account between Studiamo databases.")
    parser.add_argument("username", help="Username to migrate")
    parser.add_argument(
        "--from-url",
        default=os.environ.get("SOURCE_DB_URL"),
        help="Source PostgreSQL connection URL (defaults to SOURCE_DB_URL env var)",
    )
    parser.add_argument(
        "--to-url",
        default=os.environ.get("TARGET_DB_URL"),
        help="Target PostgreSQL connection URL (defaults to TARGET_DB_URL env var)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply migration changes (copies to target and deletes from source)")

    args = parser.parse_args()
    if not args.from_url or not args.to_url:
        parser.error("source and target DB URLs are required: pass --from-url/--to-url or set SOURCE_DB_URL/TARGET_DB_URL")

    migrate_user(args.username, args.from_url, args.to_url, apply_changes=args.apply)


if __name__ == "__main__":
    main()
