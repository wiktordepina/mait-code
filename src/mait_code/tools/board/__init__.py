"""Board tool — a manually-driven kanban board across projects.

A single SQLite board (``board.db``) of cards tagged by ``project``. The CLI
(``main``) handles create / refine / pick-up / move / complete operations.
Columns are fixed: backlog → refined → in_progress → blocked → done, plus a
hidden archived state.
"""

from mait_code.tools.board.cli import main
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    ARCHIVED,
    BACKLOG,
    BLOCKED,
    BOARD_ORDER,
    DONE,
    IN_PROGRESS,
    LABELS,
    REFINED,
    is_valid_status,
    label,
)
from mait_code.tools.board.db import (
    connection,
    get_connection,
    get_data_dir,
    get_db_path,
    get_project,
)
from mait_code.tools.board.migrate import ensure_schema

__all__ = [
    "ALL_STATUSES",
    "ARCHIVED",
    "BACKLOG",
    "BLOCKED",
    "BOARD_ORDER",
    "DONE",
    "IN_PROGRESS",
    "LABELS",
    "REFINED",
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "get_project",
    "is_valid_status",
    "label",
    "main",
]
