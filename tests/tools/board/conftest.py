"""Shared test fixtures for board tool tests."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from mait_code.tools.board.db import get_connection

TEST_PROJECT = "test-project"


@pytest.fixture
def board_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp board database with schema applied."""
    db_path = tmp_path / "test_board.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def mock_conn(board_db, monkeypatch):
    """Monkeypatch connection and get_project in the cli module to use test db."""
    import mait_code.tools.board.cli as cli_mod

    @contextmanager
    def fake_connection():
        yield board_db

    monkeypatch.setattr(cli_mod, "connection", fake_connection)
    monkeypatch.setattr(cli_mod, "get_project", lambda: TEST_PROJECT)
    return board_db
