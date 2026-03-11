"""
Shared database connection factory for tasks.

All tasks modules should import get_connection() from here
instead of creating their own connections.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from mait_code.tools.tasks.migrate import ensure_schema


def get_data_dir() -> Path:
    """Return the mait-code data directory, creating it if needed."""
    data_dir = Path(
        os.environ.get("MAIT_CODE_DATA_DIR", Path.home() / ".claude" / "mait-code-data")
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Return the tasks database path."""
    return get_data_dir() / "tasks.db"


def get_project() -> str:
    """Return the current project identifier (basename of git root or cwd).

    Delegates to mait_code.context.get_project() — kept here for backward compat.
    """
    from mait_code.context import get_project as _get_project

    return _get_project() or Path.cwd().name


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """
    Open a tasks database connection.

    - Enables WAL mode for concurrent reads
    - Enables foreign key enforcement
    - Runs schema migrations to ensure current schema

    Args:
        db_path: Override path (defaults to {data_dir}/tasks.db).

    Returns:
        sqlite3.Connection ready for use. Caller must close it.
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    return conn


@contextmanager
def connection(db_path: Path | None = None):
    """Context manager that opens and closes a tasks database connection."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
