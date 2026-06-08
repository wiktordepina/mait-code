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
from mait_code.tools.reminders.service import (
    active_reminders,
    dismissed_reminders,
    overdue_reminders,
)

__all__ = [
    # CLI
    "main",
    # Storage
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    # Queries
    "active_reminders",
    "dismissed_reminders",
    "overdue_reminders",
]
