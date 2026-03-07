"""Shared test fixtures for reminders tool tests."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

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
    """Monkeypatch get_connection in cli module to return the test db."""
    import mait_code.tools.reminders.cli as cli_mod

    wrapper = MagicMock(wraps=reminders_db)
    wrapper.close = MagicMock()
    monkeypatch.setattr(cli_mod, "get_connection", lambda: wrapper)
    return reminders_db
