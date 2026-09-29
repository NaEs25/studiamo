"""
ConnectionWrapper.close() must hand a connection back to the pool exactly once.

Route handlers close early on their error paths and again in a `finally`. Releasing the same
connection twice would put it into the pool twice, and two later borrowers would share it.
"""
from app import database


def test_close_releases_only_once(monkeypatch):
    released = []
    monkeypatch.setattr(database, "release_pooled_connection", lambda raw: released.append(raw))

    raw = object()
    conn = database.ConnectionWrapper(raw)
    conn.close()
    conn.close()

    assert released == [raw]


def test_context_manager_releases_once_after_early_close(monkeypatch):
    released = []
    monkeypatch.setattr(database, "release_pooled_connection", lambda raw: released.append(raw))

    class _Raw:
        autocommit = True

    raw = _Raw()
    with database.ConnectionWrapper(raw) as conn:
        conn.close()

    assert released == [raw]
