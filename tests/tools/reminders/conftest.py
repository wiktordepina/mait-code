"""Shared test fixtures for reminders tool tests."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from mait_code.tools.reminders.db import get_connection


@pytest.fixture
def reminders_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp reminders database with schema applied."""
    db_path = tmp_path / "test_reminders.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mock_conn(reminders_db, monkeypatch):
    """Monkeypatch connection in cli module to return the test db."""
    import mait_code.tools.reminders.cli as cli_mod

    @contextmanager
    def fake_connection():
        yield reminders_db

    monkeypatch.setattr(cli_mod, "connection", fake_connection)
    return reminders_db
