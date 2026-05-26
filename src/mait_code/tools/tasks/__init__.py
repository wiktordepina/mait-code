"""Tasks tool — lightweight per-project task tracking.

A flat per-project task list stored in SQLite. The CLI (``main``) handles
add / list / done / remove / check operations and a cross-project
``list_all`` overview.
"""

from mait_code.tools.tasks.cli import main
from mait_code.tools.tasks.db import (
    connection,
    get_connection,
    get_data_dir,
    get_db_path,
    get_project,
)
from mait_code.tools.tasks.migrate import ensure_schema

__all__ = [
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "get_project",
    "main",
]
