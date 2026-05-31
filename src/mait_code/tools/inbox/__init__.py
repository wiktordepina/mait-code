"""Quick-capture inbox tool — a frictionless capture-now, sort-later holding pen.

A single global SQLite store (``inbox.db``) of captured items. The CLI
(``main``) handles capture / list / remove, sitting on the
presentation-agnostic :mod:`~mait_code.tools.inbox.service` core. The
``/triage`` skill drains items out to the board, tasks, decisions, or memory,
so the inbox stays near-empty.
"""

from mait_code.tools.inbox.cli import main
from mait_code.tools.inbox.db import (
    connection,
    get_connection,
    get_data_dir,
    get_db_path,
    get_project,
)
from mait_code.tools.inbox.migrate import ensure_schema
from mait_code.tools.inbox.service import (
    ItemNotFound,
    add_item,
    count_items,
    get_item,
    list_items,
    remove_item,
)

__all__ = [
    # Database
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "get_project",
    # Service
    "ItemNotFound",
    "add_item",
    "count_items",
    "get_item",
    "list_items",
    "remove_item",
    # Entry point
    "main",
]
