"""
Shared database connection factory for reminders.

All reminders modules should import get_connection() from here
instead of creating their own connections.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from mait_code.tools.reminders.migrate import ensure_schema


def get_data_dir() -> Path:
    """Return the mait-code data directory, creating it if needed."""
    data_dir = Path(
        os.environ.get("MAIT_CODE_DATA_DIR", Path.home() / ".claude" / "mait-code-data")
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Return the reminders database path."""
    return get_data_dir() / "reminders.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """
    Open a reminders database connection.

    - Enables WAL mode for concurrent reads
    - Runs schema migrations to ensure current schema

    Args:
        db_path: Override path (defaults to {data_dir}/reminders.db).

    Returns:
        sqlite3.Connection ready for use. Caller must close it.
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)
    return conn


@contextmanager
def connection(db_path: Path | None = None):
    """Context manager that opens and closes a reminders database connection."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
