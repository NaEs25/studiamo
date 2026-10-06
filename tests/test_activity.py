"""
Activity tracking (app/activity.py) and push click counting (notifications.mark_clicked), run
against the shared staging database as the test accounts. Every row and profile value a test
touches is put back afterwards.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import activity, database, notifications

TEMPLATE_ID = "test-click-template"


def _request(method, path="/api/goals/{id}"):
    return SimpleNamespace(method=method, scope={"route": SimpleNamespace(path=path)})


@pytest.fixture
def account(test_username):
    """Connection plus a restore of the activity columns and today's day row."""
    activity._last_write.pop(test_username, None)
    conn = database.get_db_connection(test_username)
    cursor = conn.cursor()
    user_uuid = conn.user_uuid
    cursor.execute("SELECT last_active_at, last_action FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    before = dict(cursor.fetchone())
    today = datetime.now(timezone.utc).date()
    cursor.execute("SELECT 1 FROM user_activity_days WHERE user_uuid = %s AND day = %s;", (user_uuid, today))
    had_day_row = cursor.fetchone() is not None
    yield conn, user_uuid, today
    cursor.execute("UPDATE user_profile SET last_active_at = %s, last_action = %s WHERE user_uuid = %s;",
                   (before["last_active_at"], before["last_action"], user_uuid))
    if not had_day_row:
        cursor.execute("DELETE FROM user_activity_days WHERE user_uuid = %s AND day = %s;", (user_uuid, today))
    conn.commit()
    conn.close()
    activity._last_write.pop(test_username, None)


def _profile(conn, user_uuid):
    cursor = conn.cursor()
    cursor.execute("SELECT last_active_at, last_action FROM user_profile WHERE user_uuid = %s;", (user_uuid,))
    return dict(cursor.fetchone())


def test_reads_do_not_count_as_activity(account, test_username):
    conn, user_uuid, today = account
    cursor = conn.cursor()
    cursor.execute("UPDATE user_profile SET last_active_at = NULL, last_action = NULL WHERE user_uuid = %s;", (user_uuid,))
    activity.note_activity(_request("GET"), test_username)
    assert _profile(conn, user_uuid) == {"last_active_at": None, "last_action": None}


def test_a_write_records_the_route_template_and_the_day(account, test_username):
    conn, user_uuid, today = account
    activity.note_activity(_request("DELETE", "/api/goals/{id}"), test_username)
    profile = _profile(conn, user_uuid)
    assert profile["last_action"] == "DELETE /api/goals/{id}"
    assert profile["last_active_at"] is not None
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM user_activity_days WHERE user_uuid = %s AND day = %s;", (user_uuid, today))
    assert cursor.fetchone() is not None


def test_writes_inside_the_interval_are_skipped(account, test_username):
    conn, user_uuid, _ = account
    activity.note_activity(_request("POST", "/api/first"), test_username)
    activity.note_activity(_request("POST", "/api/second"), test_username)
    assert _profile(conn, user_uuid)["last_action"] == "POST /api/first"


def test_a_failed_write_does_not_raise_and_retries_next_time(account, test_username, monkeypatch):
    def broken(_username):
        raise RuntimeError("database down")
    monkeypatch.setattr(database, "get_db_connection", broken)
    activity.note_activity(_request("POST"), test_username)
    assert test_username not in activity._last_write


@pytest.fixture
def push_log(test_username, other_test_username):
    """A push reminder row for the test account and a stats row for its template."""
    conn = database.get_db_connection(test_username)
    cursor = conn.cursor()
    user_uuid = conn.user_uuid
    cursor.execute(
        """INSERT INTO notification_log (user_uuid, kind, template_id, channels, local_day)
           VALUES (%s, 'daily', %s, 'push', CURRENT_DATE) RETURNING id;""",
        (user_uuid, TEMPLATE_ID),
    )
    log_id = cursor.fetchone()["id"]
    cursor.execute("INSERT INTO notification_template_stats (template_id, sent) VALUES (%s, 1) ON CONFLICT DO NOTHING;",
                   (TEMPLATE_ID,))
    conn.commit()
    yield conn, user_uuid, log_id
    cursor.execute("DELETE FROM notification_log WHERE id = %s;", (log_id,))
    cursor.execute("DELETE FROM notification_template_stats WHERE template_id = %s;", (TEMPLATE_ID,))
    conn.commit()
    conn.close()


def _clicked_count(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT clicked FROM notification_template_stats WHERE template_id = %s;", (TEMPLATE_ID,))
    return cursor.fetchone()["clicked"]


def test_a_click_is_counted_once(push_log):
    conn, user_uuid, log_id = push_log
    assert notifications.mark_clicked(user_uuid, log_id) is True
    assert notifications.mark_clicked(user_uuid, log_id) is False
    assert _clicked_count(conn) == 1


def test_another_account_cannot_count_a_click(push_log, other_test_username):
    conn, _, log_id = push_log
    other_uuid = database.get_db_connection(other_test_username).user_uuid
    assert notifications.mark_clicked(other_uuid, log_id) is False
    assert _clicked_count(conn) == 0
