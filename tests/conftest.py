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
    """In-process client for the real app, deliberately without its lifespan.

    Entering TestClient as a context manager would run app.main.lifespan, which starts the
    Telegram pollers and the notification scheduler and resumes every pending import task
    in the shared staging database, all alongside the running staging service. That means
    Telegram getUpdates conflicts, possible duplicate notifications, and imports processed
    twice. None of it is needed to serve a request, and the schema it would verify is the
    one the staging service already applies on boot."""
    from app.main import app
    yield TestClient(app, follow_redirects=False)
