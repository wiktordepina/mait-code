"""Shared test fixtures for tasks tool tests."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from mait_code.tools.tasks.db import get_connection


TEST_PROJECT = "test-project"


@pytest.fixture
def tasks_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp tasks database with schema applied."""
    db_path = tmp_path / "test_tasks.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mock_conn(tasks_db, monkeypatch):
    """Monkeypatch connection and get_project in cli module to use test db."""
    import mait_code.tools.tasks.cli as cli_mod

    @contextmanager
    def fake_connection():
        yield tasks_db

    monkeypatch.setattr(cli_mod, "connection", fake_connection)
    monkeypatch.setattr(cli_mod, "get_project", lambda: TEST_PROJECT)
    return tasks_db
