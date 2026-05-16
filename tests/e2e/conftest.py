"""
tests/e2e/conftest.py

Playwright fixtures for the Brew Crew e2e suite.

Two things to notice:

1. DATABASE_URL is set BEFORE `from app import ...`. The Flask app creates its
   SQLModel engine at module-import time, so if we don't set the env var first,
   the test would silently use the production database URL.

2. The live_server fixture starts the real Flask app on a real port. Playwright
   drives a real browser against that port. The test will make real network
   calls to Nominatim (nominatim.openstreetmap.org) — no mocking. That's the
   point: this is the automated version of the Week 6 manual e2e walk.
"""

import os
import tempfile
import threading
import time

# MUST come before importing `app`. The engine is created at import time.
_TEST_DB = os.path.join(tempfile.gettempdir(), "brewcrew_e2e_test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-only-not-for-prod")

import pytest
from werkzeug.serving import make_server
from sqlmodel import SQLModel, Session

from app import app, engine, Cafe  # noqa: E402


class _ServerThread(threading.Thread):
    """Runs the Flask app in a background thread so Playwright can hit it."""

    def __init__(self, flask_app, host: str, port: int):
        super().__init__(daemon=True)
        self.srv = make_server(host, port, flask_app)

    def run(self):
        self.srv.serve_forever()

    def shutdown(self):
        self.srv.shutdown()


@pytest.fixture(scope="session")
def live_server():
    """Session-scoped: start the Flask server once, tear down at the end."""
    app.config["TESTING"] = True
    SQLModel.metadata.create_all(engine)

    server = _ServerThread(app, "127.0.0.1", 5555)
    server.start()
    time.sleep(0.3)  # give werkzeug a moment to bind

    yield type("LiveServer", (), {"url": "http://127.0.0.1:5555"})()

    server.shutdown()


@pytest.fixture(autouse=True)
def reset_db(live_server):
    """Wipe cafes and ratings before every test so results don't accumulate.

    Unlike the browse-and-detail test, this one doesn't pre-seed any cafes —
    the cafes come from Nominatim via the search route under test.
    """
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield
