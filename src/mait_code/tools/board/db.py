"""Shared database connection factory for the board tool.

All board modules should import ``get_connection()`` / ``connection()`` from
here instead of creating their own connections.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from mait_code.config import data_dir as _data_dir
from mait_code.tools.board.migrate import ensure_schema


def get_data_dir() -> Path:
    """Return the mait-code data directory, creating it if needed."""
    path = _data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """Return the board database path."""
    return get_data_dir() / "board.db"


def get_project() -> str:
    """Return the current project identifier (basename of git root or cwd).

    Delegates to ``mait_code.context.get_project()``, falling back to the
    current directory name.
    """
    from mait_code.context import get_project as _get_project

    return _get_project() or Path.cwd().name


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a board database connection.

    The connection has WAL journal mode enabled (for concurrent reads),
    foreign-key enforcement enabled (so ``card_comments`` cascade-delete on
    ``ON DELETE CASCADE``), and the current schema applied via migrations.

    Args:
        db_path: Override the database path (defaults to
            ``{data_dir}/board.db``).

    Returns:
        A ``sqlite3.Connection`` ready for use. The caller must close it.
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
    """Context manager that opens and closes a board database connection."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
