"""Shared test fixtures for inbox tool tests."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from mait_code.tools.inbox.db import get_connection

TEST_PROJECT = "test-project"


@pytest.fixture
def inbox_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp inbox database with schema applied."""
    db_path = tmp_path / "test_inbox.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mock_conn(inbox_db, monkeypatch):
    """Monkeypatch connection and get_project in the cli module to use test db."""
    import mait_code.tools.inbox.cli as cli_mod

    @contextmanager
    def fake_connection():
        yield inbox_db

    monkeypatch.setattr(cli_mod, "connection", fake_connection)
    monkeypatch.setattr(cli_mod, "get_project", lambda: TEST_PROJECT)
    return inbox_db
