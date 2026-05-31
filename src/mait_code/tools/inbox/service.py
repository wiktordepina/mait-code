"""Presentation-agnostic inbox operations shared by the CLI (and any future TUI).

Pure functions over an open ``sqlite3.Connection`` — queries and mutations. The
caller owns the connection lifecycle: the argparse CLI opens one per command via
:func:`~mait_code.tools.inbox.db.connection`.

The inbox is a single frictionless "capture now, sort later" holding pen. Items
carry an optional ``project`` (the capture context — a routing hint), but the
store itself is global: triage drains items out to the board, tasks, decisions,
or memory, keeping the inbox near-empty. Mutations raise :class:`ItemNotFound`
for a missing id rather than printing and exiting — that ``print``/``sys.exit``
is a CLI concern the caller layers on top.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone

__all__ = [
    "ItemNotFound",
    "add_item",
    "count_items",
    "get_item",
    "list_items",
    "remove_item",
]

_ITEM_COLS = "id, body, project, created_at"
_ITEM_KEYS = ("id", "body", "project", "created_at")


class ItemNotFound(Exception):
    """Raised by mutations when no inbox item has the given id."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"inbox item #{item_id} not found")
        self.item_id = item_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _item_dict(row: Sequence) -> dict:
    """Map a row selected with ``_ITEM_COLS`` to a JSON-friendly dict."""
    return dict(zip(_ITEM_KEYS, row))


# --- Queries ---


def list_items(conn: sqlite3.Connection, *, project: str | None = None) -> list[dict]:
    """Return captured items oldest-first (capture order, for triage).

    Args:
        conn: Open inbox connection.
        project: Restrict to one capture-context project, or ``None`` for the
            whole inbox (the default — capture is global).
    """
    if project is None:
        rows = conn.execute(
            f"SELECT {_ITEM_COLS} FROM inbox_items ORDER BY created_at, id"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_ITEM_COLS} FROM inbox_items WHERE project = ? "
            f"ORDER BY created_at, id",
            (project,),
        ).fetchall()
    return [_item_dict(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    """Return one item as a dict, or ``None`` if no item has that id."""
    row = conn.execute(
        f"SELECT {_ITEM_COLS} FROM inbox_items WHERE id = ?", (item_id,)
    ).fetchone()
    return _item_dict(row) if row is not None else None


def count_items(conn: sqlite3.Connection, *, project: str | None = None) -> int:
    """Return the number of items in the inbox (global unless *project* given)."""
    if project is None:
        row = conn.execute("SELECT COUNT(*) FROM inbox_items").fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM inbox_items WHERE project = ?", (project,)
        ).fetchone()
    return row[0]


# --- Mutations ---


def add_item(conn: sqlite3.Connection, *, body: str, project: str | None = None) -> int:
    """Insert a captured item and return its new id."""
    cursor = conn.execute(
        "INSERT INTO inbox_items (body, project, created_at) VALUES (?, ?, ?)",
        (body, project, _now()),
    )
    conn.commit()
    item_id = cursor.lastrowid
    assert item_id is not None  # a successful INSERT always sets lastrowid
    return item_id


def remove_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Delete an item permanently (triage routes it out, then removes it).

    Raises :class:`ItemNotFound` if the id is unknown.
    """
    row = conn.execute("SELECT id FROM inbox_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ItemNotFound(item_id)
    conn.execute("DELETE FROM inbox_items WHERE id = ?", (item_id,))
    conn.commit()
