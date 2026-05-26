"""Reminders tool — project-scoped one-shot reminders surfaced at session start.

A small SQLite-backed reminder list per project. The CLI (``main``) handles
add / list / dismiss / check operations; the session-start hook reads the
overdue set and surfaces it in the greeting.
"""

from mait_code.tools.reminders.cli import main
from mait_code.tools.reminders.db import (
    connection,
    get_connection,
    get_data_dir,
    get_db_path,
)
from mait_code.tools.reminders.migrate import ensure_schema

__all__ = [
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "main",
]
