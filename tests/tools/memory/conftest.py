"""Shared test fixtures for memory tool tests."""

import sqlite3
from pathlib import Path

import pytest

from mait_code.tools.memory.db import get_connection


@pytest.fixture
def memory_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp database with full schema applied."""
    db_path = tmp_path / "test_memory.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def populated_db(memory_db: sqlite3.Connection) -> sqlite3.Connection:
    """Database with sample entries for search/scoring tests."""
    entries = [
        ("User prefers dark mode in all editors", "preference", 8, "semantic"),
        ("Completed migration to PostgreSQL", "event", 6, "episodic"),
        ("Always run tests before committing", "insight", 7, "semantic"),
        ("Met with team to discuss API design", "event", 5, "episodic"),
        ("User uses pytest with -x flag", "preference", 6, "semantic"),
        ("Kubernetes cluster upgraded to 1.28", "fact", 7, "semantic"),
        ("Deploy pipeline broken due to flaky test", "task", 4, "episodic"),
    ]
    for content, entry_type, importance, memory_class in entries:
        memory_db.execute(
            """INSERT INTO memory_entries (content, entry_type, importance, memory_class)
               VALUES (?, ?, ?, ?)""",
            (content, entry_type, importance, memory_class),
        )
    memory_db.commit()
    return memory_db
