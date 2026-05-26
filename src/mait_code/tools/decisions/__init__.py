"""Decisions tool — per-project ADR-lite log with rendered Markdown sync.

A SQLite-backed decision log per project. Each entry is a small ADR-style
record (title, context, decision, consequences). The CLI (``main``) handles
record / list / show / amend / supersede / search / remove operations;
``write_decisions_md`` re-renders ``docs/decisions.md`` from the database.
"""

from mait_code.tools.decisions.cli import main
from mait_code.tools.decisions.db import (
    connection,
    get_connection,
    get_data_dir,
    get_db_path,
    get_project,
)
from mait_code.tools.decisions.migrate import ensure_schema
from mait_code.tools.decisions.render import render_decisions_md, write_decisions_md

__all__ = [
    # CLI
    "main",
    # Storage
    "connection",
    "ensure_schema",
    "get_connection",
    "get_data_dir",
    "get_db_path",
    "get_project",
    # Rendering
    "render_decisions_md",
    "write_decisions_md",
]
