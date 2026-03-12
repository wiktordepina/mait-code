"""Shared test fixtures for decisions tool tests."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from mait_code.tools.decisions.db import get_connection


TEST_PROJECT = "test-project"


@pytest.fixture
def decisions_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp decisions database with schema applied."""
    db_path = tmp_path / "test_decisions.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mock_conn(decisions_db, monkeypatch):
    """Monkeypatch connection and get_project in cli module to use test db."""
    import mait_code.tools.decisions.cli as cli_mod

    @contextmanager
    def fake_connection():
        yield decisions_db

    monkeypatch.setattr(cli_mod, "connection", fake_connection)
    monkeypatch.setattr(cli_mod, "get_project", lambda: TEST_PROJECT)
    monkeypatch.setattr(cli_mod, "write_decisions_md", lambda conn: None)
    return decisions_db
