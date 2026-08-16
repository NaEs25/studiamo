"""
Shared pytest fixtures.

These tests run against the shared staging Supabase database. That constraint shapes what test_smoke_routes.py is allowed
to do: hit real endpoints, but never in a way that creates, modifies, or
deletes real data. See the module docstring there for exactly how each
route is handled.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c
