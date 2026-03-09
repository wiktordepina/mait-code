"""Shared test fixtures for tasks tool tests."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mait_code.tools.tasks.db import get_connection


TEST_PROJECT = "test-project"


@pytest.fixture
def tasks_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp tasks database with schema applied."""
    db_path = tmp_path / "test_tasks.db"
    conn = get_connection(db_path)
    # Pre-register the test project so FK constraints are satisfied
    conn.execute(
        "INSERT OR IGNORE INTO projects (name, path) VALUES (?, ?)",
        (TEST_PROJECT, str(tmp_path)),
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def mock_conn(tasks_db, monkeypatch):
    """Monkeypatch get_connection and get_project in cli module to use test db."""
    import mait_code.tools.tasks.cli as cli_mod

    wrapper = MagicMock(wraps=tasks_db)
    wrapper.close = MagicMock()
    monkeypatch.setattr(cli_mod, "get_connection", lambda: wrapper)
    monkeypatch.setattr(cli_mod, "get_project", lambda: TEST_PROJECT)
    # No-op ensure_project since test project is already registered
    monkeypatch.setattr(cli_mod, "ensure_project", lambda conn, name: None)
    return tasks_db
