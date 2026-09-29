"""
_WaitingConnectionPool: a borrow from an empty pool waits for a return instead of failing.

psycopg2.connect is replaced with a fake, so nothing here opens a real connection.
"""
import threading
import time
from types import SimpleNamespace

import psycopg2
import psycopg2.extensions
import psycopg2.pool
import pytest

from app.database import _WaitingConnectionPool


class _FakeConn:
    def __init__(self):
        self.closed = False
        self.info = SimpleNamespace(transaction_status=psycopg2.extensions.TRANSACTION_STATUS_IDLE)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_connect(monkeypatch):
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: _FakeConn())


def test_borrow_waits_for_a_returned_connection():
    pool = _WaitingConnectionPool(1, 2, "dsn")
    held = [pool.getconn(), pool.getconn()]

    threading.Timer(0.2, lambda: pool.putconn(held[0])).start()
    started = time.monotonic()
    conn = pool.getconn(timeout=5)

    assert conn is not None
    assert 0.1 < time.monotonic() - started < 4


def test_borrow_gives_up_after_the_timeout():
    pool = _WaitingConnectionPool(1, 1, "dsn")
    pool.getconn()

    started = time.monotonic()
    with pytest.raises(psycopg2.pool.PoolError, match="exhausted"):
        pool.getconn(timeout=0.2)
    assert time.monotonic() - started >= 0.2


def test_returned_connections_are_kept_up_to_the_minimum():
    pool = _WaitingConnectionPool(2, 5, "dsn")
    borrowed = [pool.getconn() for _ in range(4)]
    for conn in borrowed:
        pool.putconn(conn)

    kept = [c for c in borrowed if not c.closed]
    assert len(kept) == 2
    assert pool.getconn() in kept


def test_many_threads_share_a_small_pool_without_errors():
    pool = _WaitingConnectionPool(1, 3, "dsn")
    errors = []

    def worker():
        try:
            for _ in range(20):
                conn = pool.getconn(timeout=5)
                time.sleep(0.001)
                pool.putconn(conn)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
