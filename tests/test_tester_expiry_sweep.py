"""
Coverage for database.check_and_expire_testers(), the hourly sweep that flips
user_profile.is_tester back to FALSE for accounts whose tester grant lapsed without the
account ever making a request (which would have self-healed via _expire_tester_cache on
the has_app_access/get_tester_state read path instead).

check_and_expire_testers() opens its own pooled connection with autocommit=True, so
calling it directly would commit a real UPDATE against the shared staging database. To
test the actual function without that, get_pooled_raw_connection/release_pooled_connection
are monkeypatched to hand it a connection this test controls (autocommit off), so the
UPDATE runs for real but stays inside a transaction this test always rolls back. This
mirrors the existing "invariants the database holds" tests in test_tester_access.py,
just wired through the real function instead of a copy of its SQL.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import database

pytest.importorskip("psycopg2")
import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402


@pytest.fixture
def sweep_in_rolled_back_txn(monkeypatch):
    """Runs database.check_and_expire_testers() against a real, uncommitted transaction.

    Yields a cursor for setting up fixture rows and reading back results; whatever the
    test (and the function itself) writes through it is rolled back on teardown."""
    try:
        conn = psycopg2.connect(database.get_supabase_db_url(), cursor_factory=RealDictCursor)
    except Exception as exc:
        pytest.skip(f"no database connection available: {exc}")
    conn.autocommit = False
    monkeypatch.setattr(database, "get_pooled_raw_connection", lambda: conn)
    monkeypatch.setattr(database, "release_pooled_connection", lambda c: None)
    try:
        yield conn.cursor()
    finally:
        conn.rollback()
        conn.close()


def _insert_profile_and_grant(cursor, is_tester: bool, expires_at, revoked_at=None):
    # period_days/expires_at encode one fact and a check constraint enforces it (see
    # test_check_constraint_rejects_disagreeing_columns in test_tester_access.py):
    # unlimited (expires_at NULL) must carry period_days = 0, a timed grant must not.
    period_days = 0 if expires_at is None else 14
    user_uuid = str(uuid.uuid4())
    cursor.execute(
        """INSERT INTO user_profile (user_uuid, username, is_tester)
           VALUES (%s, %s, %s);""",
        (user_uuid, f"sweep_test_{user_uuid[:8]}", is_tester),
    )
    cursor.execute(
        """INSERT INTO tester_access (user_uuid, period_days, expires_at, revoked_at)
           VALUES (%s, %s, %s, %s);""",
        (user_uuid, period_days, expires_at, revoked_at),
    )
    return user_uuid


NOW = datetime.now(timezone.utc)


def test_flips_is_tester_false_for_an_expired_unrevoked_grant(sweep_in_rolled_back_txn):
    cursor = sweep_in_rolled_back_txn
    user_uuid = _insert_profile_and_grant(cursor, is_tester=True, expires_at=NOW - timedelta(days=1))

    flipped = database.check_and_expire_testers()

    cursor.execute("SELECT is_tester FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    assert cursor.fetchone()["is_tester"] is False
    assert flipped >= 1


def test_leaves_a_still_active_grant_alone(sweep_in_rolled_back_txn):
    cursor = sweep_in_rolled_back_txn
    user_uuid = _insert_profile_and_grant(cursor, is_tester=True, expires_at=NOW + timedelta(days=7))

    database.check_and_expire_testers()

    cursor.execute("SELECT is_tester FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    assert cursor.fetchone()["is_tester"] is True


def test_leaves_a_revoked_grant_alone(sweep_in_rolled_back_txn):
    """Revocation already has its own path to turning off access; the sweep is only for
    grants that ran out on their own, so it must not double up on an already-revoked one."""
    cursor = sweep_in_rolled_back_txn
    user_uuid = _insert_profile_and_grant(
        cursor, is_tester=True, expires_at=NOW - timedelta(days=1), revoked_at=NOW - timedelta(hours=1)
    )

    database.check_and_expire_testers()

    cursor.execute("SELECT is_tester FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    assert cursor.fetchone()["is_tester"] is True


def test_leaves_an_unlimited_grant_alone(sweep_in_rolled_back_txn):
    """expires_at IS NULL means unlimited (see the check constraint tested in
    test_tester_access.py), not 'already expired'."""
    cursor = sweep_in_rolled_back_txn
    user_uuid = _insert_profile_and_grant(cursor, is_tester=True, expires_at=None)

    database.check_and_expire_testers()

    cursor.execute("SELECT is_tester FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    assert cursor.fetchone()["is_tester"] is True


def test_only_considers_each_account_s_newest_grant(sweep_in_rolled_back_txn):
    """An old expired grant must not flip is_tester off if a newer grant on the same
    account is still running, mirroring _decide_access's DISTINCT ON (user_uuid) ordering."""
    cursor = sweep_in_rolled_back_txn
    user_uuid = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO user_profile (user_uuid, username, is_tester) VALUES (%s, %s, TRUE);",
        (user_uuid, f"sweep_test_{user_uuid[:8]}"),
    )
    cursor.execute(
        """INSERT INTO tester_access (user_uuid, period_days, expires_at, granted_at)
           VALUES (%s, 14, %s, %s);""",
        (user_uuid, NOW - timedelta(days=20), NOW - timedelta(days=34)),
    )
    cursor.execute(
        """INSERT INTO tester_access (user_uuid, period_days, expires_at, granted_at)
           VALUES (%s, 14, %s, %s);""",
        (user_uuid, NOW + timedelta(days=7), NOW - timedelta(days=7)),
    )

    database.check_and_expire_testers()

    cursor.execute("SELECT is_tester FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    assert cursor.fetchone()["is_tester"] is True
