"""
One-off migration, not part of app/schema.py because it touches an existing column's type
and adds constraints that can fail against existing data (schema.py must stay purely
additive, see its own docstring).

Does four things against a single database:
  1. user_profile.user_uuid: TEXT -> native uuid.
  2. user_profile.referred_by: TEXT -> native uuid, plus the FK -> user_profile(user_uuid)
     that app/schema.py has declared since it was added but that a database can be missing
     if the column pre-dated that line (ADD COLUMN IF NOT EXISTS is a no-op against an
     existing column, so a schema.py type change never retroactively applies). Independent
     of step 1: a database can already have user_uuid as uuid while referred_by is still
     text with no FK, which is exactly the state the new staging project was found in on
     2026-08-15 (prod already had both converted).
  3. goal_recommendations.goal_id: adds the FK -> goals(id) ON DELETE CASCADE that
     daily_recommendations already has but this table never got.
  4. quiz_attempts.video_id / quiz_id / goal_id: adds FKs -> videos(id) / quizzes(id) /
     goals(id), all ON DELETE CASCADE. app code already deletes quiz_attempts by video_id
     whenever a video is removed (routers/videos.py, routers/goals.py), this just makes
     that the database's job instead of something every future delete path has to
     remember, and it closes the one path that currently forgets: deleting a goal directly
     removes goal-only quizzes (quizzes.goal_id already cascades) but never touched the
     quiz_attempts rows pointing at them.

Safe to re-run: every step checks current state first and skips what's already done.
Dry run by default, prints exactly what it would change without writing anything.

Reads the connection URL from this worktree's .env (same variable app/database.py uses:
CLOUD_DATABASE_URL, then SUPABASE_DB_URL, then DATABASE_URL), so nothing needs to be typed
on the command line. Pass --db-url to point at a different database explicitly.

Usage:
  python scripts/migrate_uuid_type_and_fk_fixes.py           # dry run against .env's DB
  python scripts/migrate_uuid_type_and_fk_fixes.py --apply   # applies it
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


def resolve_db_url() -> str | None:
    return (
        os.getenv("SELFHOSTED_DATABASE_URL")
        or os.getenv("CLOUD_DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("DATABASE_URL")
    )


def find_fk_on_column(cur, table: str, column: str):
    """Returns (conname, condef) for a FK constraint touching `column`, or None."""
    cur.execute(
        "SELECT con.conname, pg_get_constraintdef(con.oid) FROM pg_constraint con "
        "JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey) "
        "WHERE con.conrelid = %s::regclass AND con.contype = 'f' AND att.attname = %s;",
        (table, column),
    )
    return cur.fetchone()


def migrate_uuid_type(cur, apply_changes: bool):
    print("=" * 70)
    print("1. user_profile.user_uuid: TEXT -> uuid")
    print("=" * 70)

    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'user_profile' AND column_name = 'user_uuid';"
    )
    current_type = cur.fetchone()[0]
    if current_type == "uuid":
        print("  Already uuid type. Skipping.")
        return

    cur.execute(
        "SELECT id, user_uuid FROM user_profile "
        r"WHERE user_uuid !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';"
    )
    bad_rows = cur.fetchall()
    if bad_rows:
        print(f"  ABORT: {len(bad_rows)} row(s) have a user_uuid that isn't valid UUID format:")
        for r in bad_rows[:10]:
            print(f"    id={r[0]} user_uuid={r[1]!r}")
        raise SystemExit(1)

    # user_profile.referred_by stores another user's user_uuid as plain text (a referral
    # pointer). This only matters here if user_uuid itself still needs converting (this
    # function already returned above otherwise) and referred_by already has a text-typed
    # FK pointing at it: both columns then have to convert in the same statement or Postgres
    # refuses the type change ("Key columns ... are of incompatible types"). The far more
    # common case, referred_by lagging behind an already-uuid user_uuid with no FK yet, is
    # handled separately below by fix_referred_by_uuid_and_fk().
    fk = find_fk_on_column(cur, "user_profile", "referred_by")
    if fk:
        conname, condef = fk
        print(f"  Found FK on referred_by ({conname}: {condef}), converts alongside user_uuid.")
        cur.execute(
            "SELECT id, referred_by FROM user_profile WHERE referred_by IS NOT NULL "
            r"AND referred_by !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';"
        )
        bad_referred_by = cur.fetchall()
        if bad_referred_by:
            print(f"  ABORT: {len(bad_referred_by)} row(s) have a referred_by that isn't valid UUID format:")
            for r in bad_referred_by[:10]:
                print(f"    id={r[0]} referred_by={r[1]!r}")
            raise SystemExit(1)

    print(f"  Current type: {current_type}. All values are valid UUID format.")
    if apply_changes:
        if fk:
            conname, condef = fk
            cur.execute(f"ALTER TABLE user_profile DROP CONSTRAINT {conname};")
            cur.execute(
                "ALTER TABLE user_profile "
                "ALTER COLUMN user_uuid TYPE uuid USING user_uuid::uuid, "
                "ALTER COLUMN referred_by TYPE uuid USING referred_by::uuid;"
            )
            cur.execute(f"ALTER TABLE user_profile ADD CONSTRAINT {conname} {condef};")
            print(f"  Converted user_uuid and referred_by together, constraint {conname} re-added.")
        else:
            cur.execute("ALTER TABLE user_profile ALTER COLUMN user_uuid TYPE uuid USING user_uuid::uuid;")
            print("  Converted.")
    else:
        if fk:
            conname, _ = fk
            print(f"  Would drop {conname}, convert user_uuid and referred_by together, then re-add it (dry run).")
        else:
            print("  Would convert (dry run).")


def fix_referred_by_uuid_and_fk(cur, apply_changes: bool):
    """Converts user_profile.referred_by to uuid and adds its FK, independent of whether
    user_uuid itself needed converting. Matches app/schema.py's declared type and prod's
    already-live state; a database that skips this ends up failing
    tests/test_schema_drift.py against its own definition of the column."""
    print()
    print("=" * 70)
    print("2. user_profile.referred_by: TEXT -> uuid, add FK -> user_profile(user_uuid)")
    print("=" * 70)

    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'user_profile' AND column_name = 'referred_by';"
    )
    row = cur.fetchone()
    if row is None:
        print("  Column doesn't exist. Skipping.")
        return
    current_type = row[0]

    fk = find_fk_on_column(cur, "user_profile", "referred_by")
    if current_type == "uuid" and fk:
        print("  Already uuid type with FK. Skipping.")
        return

    if current_type != "uuid":
        cur.execute(
            "SELECT id, referred_by FROM user_profile WHERE referred_by IS NOT NULL "
            r"AND referred_by !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';"
        )
        bad_rows = cur.fetchall()
        if bad_rows:
            print(f"  ABORT: {len(bad_rows)} row(s) have a referred_by that isn't valid UUID format:")
            for r in bad_rows[:10]:
                print(f"    id={r[0]} referred_by={r[1]!r}")
            raise SystemExit(1)
        print(f"  Current type: {current_type}. All values are valid UUID format.")

    if apply_changes:
        if current_type != "uuid":
            cur.execute("ALTER TABLE user_profile ALTER COLUMN referred_by TYPE uuid USING referred_by::uuid;")
            print("  Converted to uuid.")
        if not fk:
            cur.execute(
                "ALTER TABLE user_profile ADD CONSTRAINT user_profile_referred_by_fkey "
                "FOREIGN KEY (referred_by) REFERENCES user_profile(user_uuid);"
            )
            print("  FK added: user_profile_referred_by_fkey.")
    else:
        if current_type != "uuid":
            print("  Would convert to uuid (dry run).")
        if not fk:
            print("  Would add FOREIGN KEY (referred_by) REFERENCES user_profile(user_uuid) (dry run).")


def fix_goal_recommendations_fk(cur, apply_changes: bool):
    print()
    print("=" * 70)
    print("3. goal_recommendations.goal_id: add missing FK -> goals(id)")
    print("=" * 70)

    cur.execute(
        "SELECT gr.id, gr.goal_id FROM goal_recommendations gr "
        "LEFT JOIN goals g ON g.id = gr.goal_id WHERE g.id IS NULL;"
    )
    orphans = cur.fetchall()
    if orphans:
        print(f"  {len(orphans)} orphaned row(s) reference a goal_id that no longer exists:")
        for r in orphans[:10]:
            print(f"    id={r[0]} goal_id={r[1]}")
        if apply_changes:
            cur.execute(
                "DELETE FROM goal_recommendations gr "
                "WHERE NOT EXISTS (SELECT 1 FROM goals g WHERE g.id = gr.goal_id);"
            )
            print(f"  Deleted {cur.rowcount} orphaned row(s).")
        else:
            print("  Would delete these before adding the constraint (dry run).")
    else:
        print("  No orphaned rows.")

    cur.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = 'goal_recommendations_goal_id_fkey' "
        "AND conrelid = 'goal_recommendations'::regclass;"
    )
    if cur.fetchone():
        print("  Constraint already exists. Skipping.")
    elif apply_changes:
        cur.execute(
            "ALTER TABLE goal_recommendations ADD CONSTRAINT goal_recommendations_goal_id_fkey "
            "FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE;"
        )
        print("  Constraint added.")
    else:
        print("  Would add FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE (dry run).")


def fix_quiz_attempts_fks(cur, apply_changes: bool):
    print()
    print("=" * 70)
    print("4. quiz_attempts: add missing FKs -> videos(id), quizzes(id), goals(id)")
    print("=" * 70)

    fk_specs = [
        ("video_id", "videos", "quiz_attempts_video_id_fkey"),
        ("quiz_id", "quizzes", "quiz_attempts_quiz_id_fkey"),
        ("goal_id", "goals", "quiz_attempts_goal_id_fkey"),
    ]
    for col, ref_table, conname in fk_specs:
        cur.execute(
            f"SELECT qa.id FROM quiz_attempts qa "
            f"LEFT JOIN {ref_table} t ON t.id = qa.{col} "
            f"WHERE qa.{col} IS NOT NULL AND t.id IS NULL;"
        )
        orphans = [r[0] for r in cur.fetchall()]
        if orphans:
            print(f"  {col}: {len(orphans)} orphaned row(s) reference a {ref_table}.id that no longer exists.")
            if apply_changes:
                cur.execute(f"UPDATE quiz_attempts SET {col} = NULL WHERE id = ANY(%s);", (orphans,))
                print(f"    NULLed out {cur.rowcount} row(s) (attempt history kept, just unlinked).")
            else:
                print(f"    Would NULL out {col} on these rows before adding the constraint (dry run).")
        else:
            print(f"  {col}: no orphaned rows.")

        cur.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s AND conrelid = 'quiz_attempts'::regclass;",
            (conname,),
        )
        if cur.fetchone():
            print(f"  {col}: constraint already exists. Skipping.")
        elif apply_changes:
            cur.execute(
                f"ALTER TABLE quiz_attempts ADD CONSTRAINT {conname} "
                f"FOREIGN KEY ({col}) REFERENCES {ref_table}(id) ON DELETE CASCADE;"
            )
            print(f"  {col}: constraint added.")
        else:
            print(f"  {col}: would add FOREIGN KEY ({col}) REFERENCES {ref_table}(id) ON DELETE CASCADE (dry run).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--db-url",
        default=resolve_db_url(),
        help="Postgres connection URL (defaults to CLOUD_DATABASE_URL / SUPABASE_DB_URL / DATABASE_URL from .env)",
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry run)")
    args = parser.parse_args()

    if not args.db_url:
        parser.error(
            "no database URL found. Set CLOUD_DATABASE_URL, SUPABASE_DB_URL, or DATABASE_URL "
            "in .env, or pass --db-url explicitly."
        )

    conn = psycopg2.connect(args.db_url)
    cur = conn.cursor()
    try:
        migrate_uuid_type(cur, args.apply)
        fix_referred_by_uuid_and_fk(cur, args.apply)
        fix_goal_recommendations_fk(cur, args.apply)
        fix_quiz_attempts_fks(cur, args.apply)

        if args.apply:
            conn.commit()
            print("\nAll changes committed.")
        else:
            conn.rollback()
            print("\nDry run complete, no changes made. Re-run with --apply to execute.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
