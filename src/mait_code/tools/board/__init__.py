"""Board tool — a manually-driven kanban board across projects.

A single SQLite board (``board.db``) of cards tagged by ``project``. The CLI
(``main``) handles create / refine / pick-up / move / complete operations, all
sitting on the presentation-agnostic :mod:`~mait_code.tools.board.service` core
that the interactive TUI shares. Columns are fixed: backlog → refined →
in_progress → done, plus a hidden archived state. ``blocked`` is a tag carried
in place, not a column.
"""

from mait_code.tools.board.cli import main
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
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
from mait_code.tools.board.export import (
    FORMATS,
    JSON,
    MARKDOWN,
    board_markdown,
    card_markdown,
    export_board,
    export_card,
)
from mait_code.tools.board.migrate import ensure_schema
from mait_code.tools.board.service import (
    CardNotFound,
    add_card,
    add_comment,
    add_tag,
    archive_card,
    block_card,
    complete_card,
    edit_card,
    get_card,
    get_comments,
    list_cards,
    list_projects,
    list_tags,
    move_card,
    next_refined,
    refine_card,
    remove_card,
    remove_tag,
    summary_counts,
    unblock_card,
)

__all__ = [
    # Columns
    "ALL_STATUSES",
    "ARCHIVED",
    "BACKLOG",
    "BLOCKED_TAG",
    "BOARD_ORDER",
    "DONE",
    "IN_PROGRESS",
    "LABELS",
    "REFINED",
    "is_valid_status",
    "label",
    # Database
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "get_project",
    # Export
    "FORMATS",
    "JSON",
    "MARKDOWN",
    "board_markdown",
    "card_markdown",
    "export_board",
    "export_card",
    # Service
    "CardNotFound",
    "add_card",
    "add_comment",
    "add_tag",
    "archive_card",
    "block_card",
    "complete_card",
    "edit_card",
    "get_card",
    "get_comments",
    "list_cards",
    "list_projects",
    "list_tags",
    "move_card",
    "next_refined",
    "refine_card",
    "remove_card",
    "remove_tag",
    "summary_counts",
    "unblock_card",
    # Entry point
    "main",
]
