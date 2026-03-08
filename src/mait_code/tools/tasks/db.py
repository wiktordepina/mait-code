"""
Shared database connection factory for tasks.

All tasks modules should import get_connection() from here
instead of creating their own connections.
"""

import os
import sqlite3
import subprocess
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
    """Return the current project identifier (basename of git root or cwd)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return Path.cwd().name


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """
    Open a tasks database connection.

    - Enables WAL mode for concurrent reads
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
    ensure_schema(conn)
    return conn
