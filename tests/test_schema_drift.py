"""
Guards against the schema in the database drifting away from `app/schema.py`.

`app/schema.py` is meant to be the source of truth for the database's shape, and
`ensure_schema_up_to_date()` runs on every app start. But nothing forced the file to stay
honest: columns were added straight to Supabase by hand over months and never written back,
until the file was 11 columns, a load-bearing unique index and a CHECK constraint out of
date. Nothing surfaced it, because the live database was fine. Only the file describing it
was wrong, while cheerfully logging "Schema verified up to date" on every boot.

The check: build the schema from `app/schema.py` into a throwaway namespace inside the same
database, then diff that against the real one. Anything present live but absent from the
rebuild is drift, and means a rebuilt database would not match production.

Why a temporary namespace rather than a scratch container: it needs no Docker, so it runs
anywhere the app itself can reach its database, including CI. Nothing is written to the
real tables at any point: a new schema is created, built into, compared, and dropped.

If this fails, do NOT fix it by applying the change to the database. Add the missing
statement to `app/schema.py`, which is the whole point (see CLAUDE.md).
"""
import uuid

import pytest

pytest.importorskip("psycopg2")
import psycopg2
from psycopg2.extras import RealDictCursor

from app import database, schema


def _normalise_default(value, namespace=None):
    """Makes two column defaults comparable across schema namespaces.

    Strips Postgres' type annotations, so 'inactive'::text equals 'inactive'. Also strips
    the namespace from SERIAL sequence defaults: the same column reads
    nextval('goals_id_seq') in public but nextval('drift_check_ab12.goals_id_seq') in the
    throwaway namespace, which is the same definition wearing a different address.
    """
    text = (value or "").split("::")[0].strip().strip("'").lower()
    if namespace:
        text = text.replace(f"{namespace.lower()}.", "")
    return text


def _snapshot(cursor, namespace, strip_namespace=None):
    """Returns (columns, indexes, constraints) for one schema namespace."""
    cursor.execute(
        """SELECT table_name, column_name, data_type, column_default, is_nullable
             FROM information_schema.columns WHERE table_schema = %s;""",
        (namespace,),
    )
    columns = {
        (r["table_name"], r["column_name"]): (
            r["data_type"], _normalise_default(r["column_default"], strip_namespace), r["is_nullable"]
        )
        for r in cursor.fetchall()
    }

    cursor.execute(
        "SELECT tablename, indexname FROM pg_indexes WHERE schemaname = %s;", (namespace,)
    )
    indexes = {(r["tablename"], r["indexname"]) for r in cursor.fetchall()}

    cursor.execute(
        """SELECT c.relname AS tbl, con.conname
             FROM pg_constraint con
             JOIN pg_class c ON c.oid = con.conrelid
             JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND con.contype IN ('c', 'u', 'p');""",
        (namespace,),
    )
    constraints = {(r["tbl"], r["conname"]) for r in cursor.fetchall()}

    return columns, indexes, constraints


@pytest.fixture(scope="module")
def schema_comparison():
    """Builds app/schema.py into a throwaway namespace and snapshots it beside the real one.

    Uses a dedicated connection rather than the shared pool on purpose: this sets
    `search_path`, and psycopg2 pools hand connections back out with session state intact,
    so a pooled connection would carry the altered search_path into unrelated application
    queries.
    """
    try:
        conn = psycopg2.connect(database.get_supabase_db_url())
    except Exception as exc:  # no database configured locally
        pytest.skip(f"no database connection available: {exc}")

    conn.autocommit = True
    namespace = f"drift_check_{uuid.uuid4().hex[:8]}"
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute(f'CREATE SCHEMA "{namespace}";')
        # search_path deliberately excludes public: with it present, every
        # CREATE TABLE IF NOT EXISTS would find the real table and skip, building nothing.
        cursor.execute(f'SET search_path TO "{namespace}";')
        applied_first = schema.ensure_schema_up_to_date(conn)
        applied_again = schema.ensure_schema_up_to_date(conn)

        cursor.execute("SET search_path TO public;")
        live = _snapshot(cursor, "public")
        built = _snapshot(cursor, namespace, strip_namespace=namespace)

        yield {
            "live": live,
            "built": built,
            "applied_first": applied_first,
            "applied_again": applied_again,
        }
    finally:
        try:
            cursor.execute("SET search_path TO public;")
            cursor.execute(f'DROP SCHEMA IF EXISTS "{namespace}" CASCADE;')
        finally:
            conn.close()


def test_no_columns_missing_from_schema_module(schema_comparison):
    """Every column in the live database must be declared in app/schema.py."""
    live_cols, _, _ = schema_comparison["live"]
    built_cols, _, _ = schema_comparison["built"]

    missing = sorted(set(live_cols) - set(built_cols))
    assert not missing, (
        "These columns exist in the database but app/schema.py does not create them, so a "
        "rebuilt database would be missing them:\n"
        + "\n".join(f"  {table}.{column}" for table, column in missing)
        + "\n\nAdd an `ALTER TABLE <table> ADD COLUMN IF NOT EXISTS ...` to app/schema.py. "
        "Read the live default first (information_schema.columns) rather than guessing it."
    )


def test_no_column_definition_mismatches(schema_comparison):
    """Shared columns must agree on type, default and nullability."""
    live_cols, _, _ = schema_comparison["live"]
    built_cols, _, _ = schema_comparison["built"]

    mismatched = [
        (key, live_cols[key], built_cols[key])
        for key in sorted(set(live_cols) & set(built_cols))
        if live_cols[key] != built_cols[key]
    ]
    assert not mismatched, (
        "These columns exist in both but are defined differently "
        "(type, default, nullable):\n"
        + "\n".join(
            f"  {t}.{c}\n      live  = {live}\n      built = {built}"
            for (t, c), live, built in mismatched
        )
    )


def test_no_indexes_missing_from_schema_module(schema_comparison):
    """Indexes are not all optimisations. uq_user_profile_username_lower is what stops two
    accounts sharing a username, which every `LOWER(username) = ... LIMIT 1` lookup relies
    on, including the one deciding whose account a subscription attaches to."""
    _, live_idx, _ = schema_comparison["live"]
    _, built_idx, _ = schema_comparison["built"]

    missing = sorted(set(live_idx) - set(built_idx))
    assert not missing, (
        "These indexes exist in the database but not in app/schema.py:\n"
        + "\n".join(f"  {table}.{index}" for table, index in missing)
        + "\n\nAdd a `CREATE INDEX IF NOT EXISTS ...` to INDEXES_SQL in app/schema.py."
    )


def test_no_constraints_missing_from_schema_module(schema_comparison):
    """CHECK, UNIQUE and PRIMARY KEY constraints must be reproducible too. A missing CHECK
    is silent: writes that should have been rejected simply succeed."""
    _, _, live_con = schema_comparison["live"]
    _, _, built_con = schema_comparison["built"]

    missing = sorted(set(live_con) - set(built_con))
    assert not missing, (
        "These constraints exist in the database but not in app/schema.py:\n"
        + "\n".join(f"  {table}.{constraint}" for table, constraint in missing)
        + "\n\nADD CONSTRAINT has no IF NOT EXISTS form, so guard it with a "
        "`DO $$ ... IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = ...) $$` "
        "block, as app/schema.py already does for user_profile_referral_code_key."
    )


def test_schema_module_is_idempotent(schema_comparison):
    """ensure_schema_up_to_date() runs on every app start, so applying an already-current
    schema must be a clean no-op rather than an error."""
    assert schema_comparison["applied_first"] == schema_comparison["applied_again"], (
        "Applying app/schema.py twice did not execute the same number of statements, "
        "which means something in it is not idempotent."
    )
