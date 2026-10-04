"""
Previews expire after 24 hours, notes or not. Dismissing a recommended video also removes the temporary preview that playing or queueing it
left among the account's materials, unless the preview holds notes (then it asks first). A
video imported for real is never removed. Runs against the first test account's own rows,
which are removed again afterwards.
"""
import pytest

from app import database

YT = "zzDismiss01"


@pytest.fixture
def tester(client_as, test_username):
    conn = database.get_db_connection(test_username)
    cursor = conn.cursor()
    def clean():
        cursor.execute("DELETE FROM videos WHERE user_uuid = %s AND youtube_id = %s;", (conn.user_uuid, YT))
        cursor.execute("DELETE FROM dismissed_recommendations WHERE user_uuid = %s AND youtube_id = %s;",
                       (conn.user_uuid, YT))

    clean()
    try:
        yield client_as(test_username), cursor, conn.user_uuid
    finally:
        clean()
        conn.close()


def _insert(cursor, user_uuid, temporary, notes=""):
    cursor.execute(
        """INSERT INTO videos (user_uuid, youtube_id, title, category, importance_rating, status,
                               is_temporary, is_watchlist, custom_notes)
           VALUES (%s, %s, 'Dismiss test', 'Test', 3, 'ready', %s, 1, %s) RETURNING id;""",
        (user_uuid, YT, temporary, notes),
    )
    return cursor.fetchone()["id"]


def _exists(cursor, user_uuid):
    cursor.execute("SELECT COUNT(*) AS n FROM videos WHERE user_uuid = %s AND youtube_id = %s;", (user_uuid, YT))
    return cursor.fetchone()["n"] == 1


def test_a_preview_without_notes_goes_with_the_recommendation(tester):
    client, cursor, user_uuid = tester
    _insert(cursor, user_uuid, temporary=1)
    res = client.post("/api/daily-recommendations/dismiss", data={"youtube_id": YT}).json()
    assert res == {"status": "success", "preview_removed": True}
    assert not _exists(cursor, user_uuid)


def test_a_preview_with_notes_asks_first(tester):
    client, cursor, user_uuid = tester
    _insert(cursor, user_uuid, temporary=1, notes="my notes")
    res = client.post("/api/daily-recommendations/dismiss", data={"youtube_id": YT}).json()
    assert res == {"status": "confirm", "has_notes": True}
    assert _exists(cursor, user_uuid)

    res = client.post("/api/daily-recommendations/dismiss", data={"youtube_id": YT, "delete_notes": "true"}).json()
    assert res["preview_removed"] is True
    assert not _exists(cursor, user_uuid)


def test_an_imported_video_stays(tester):
    client, cursor, user_uuid = tester
    _insert(cursor, user_uuid, temporary=0, notes="my notes")
    res = client.post("/api/daily-recommendations/dismiss", data={"youtube_id": YT}).json()
    assert res == {"status": "success", "preview_removed": False}
    assert _exists(cursor, user_uuid)


def test_a_preview_goes_when_its_24_hours_are_up_notes_or_not(tester):
    _, cursor, user_uuid = tester
    expired = _insert(cursor, user_uuid, temporary=1, notes="my notes")
    cursor.execute("UPDATE videos SET expires_at = (NOW() - INTERVAL '1 minute')::text WHERE id = %s;", (expired,))
    assert database.delete_expired_previews() >= 1
    assert not _exists(cursor, user_uuid)

    _insert(cursor, user_uuid, temporary=1, notes="my notes")
    cursor.execute("UPDATE videos SET expires_at = (NOW() + INTERVAL '1 hour')::text WHERE youtube_id = %s;", (YT,))
    database.delete_expired_previews()
    assert _exists(cursor, user_uuid)
