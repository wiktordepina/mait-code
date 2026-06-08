"""Presentation-agnostic reminder queries shared by the CLI, hook and TUIs.

Pure functions over an open ``sqlite3.Connection`` — the caller owns the
connection lifecycle, mirroring :mod:`mait_code.tools.inbox.service`. Each
reminder is returned as a dict with its ``due`` already parsed to an aware
:class:`~datetime.datetime`, so callers format rather than re-parse.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

__all__ = [
    "active_reminders",
    "dismissed_reminders",
    "overdue_reminders",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reminder_dict(row: tuple) -> dict:
    rid, what, due_str = row
    return {"id": rid, "what": what, "due": datetime.fromisoformat(due_str)}


def active_reminders(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Return the active reminders split into ``(overdue, upcoming)``.

    Both lists are ordered by due date. A reminder is overdue when its due
    time is at or before *now* (default: the current UTC time).
    """
    now = now or _now()
    rows = conn.execute(
        "SELECT id, what, due FROM reminders WHERE dismissed = 0 ORDER BY due"
    ).fetchall()
    reminders = [_reminder_dict(r) for r in rows]
    overdue = [r for r in reminders if r["due"] <= now]
    upcoming = [r for r in reminders if r["due"] > now]
    return overdue, upcoming


def overdue_reminders(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[dict]:
    """Return only the overdue active reminders, ordered by due date."""
    overdue, _ = active_reminders(conn, now=now)
    return overdue


def dismissed_reminders(conn: sqlite3.Connection) -> list[dict]:
    """Return dismissed reminders, ordered by due date."""
    rows = conn.execute(
        "SELECT id, what, due FROM reminders WHERE dismissed = 1 ORDER BY due"
    ).fetchall()
    return [_reminder_dict(r) for r in rows]
