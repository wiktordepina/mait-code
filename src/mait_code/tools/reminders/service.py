"""Presentation-agnostic reminder queries shared by the CLI, hook and TUIs.

Pure functions over an open ``sqlite3.Connection`` — the caller owns the
connection lifecycle, mirroring :mod:`mait_code.tools.inbox.service`. Each
reminder is returned as a dict with its ``due`` already parsed to an aware
:class:`~datetime.datetime`, so callers format rather than re-parse.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone

__all__ = [
    "active_reminders",
    "dismiss_reminder",
    "dismissed_reminders",
    "due_unnotified",
    "mark_notified",
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


def due_unnotified(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> list[dict]:
    """Return overdue, active reminders not yet published outward.

    The Bridge's outbound half publishes these once and calls
    :func:`mark_notified`, so a still-overdue reminder isn't re-sent to the
    phone on every session.
    """
    now = now or _now()
    rows = conn.execute(
        "SELECT id, what, due FROM reminders "
        "WHERE dismissed = 0 AND notified_at IS NULL ORDER BY due"
    ).fetchall()
    return [r for r in (_reminder_dict(row) for row in rows) if r["due"] <= now]


def mark_notified(
    conn: sqlite3.Connection,
    ids: Iterable[int],
    *,
    now: datetime | None = None,
) -> None:
    """Stamp ``notified_at`` on the given reminders (idempotent per id)."""
    ids = list(ids)
    if not ids:
        return
    stamp = (now or _now()).isoformat()
    conn.executemany(
        "UPDATE reminders SET notified_at = ? WHERE id = ?",
        [(stamp, rid) for rid in ids],
    )
    conn.commit()


def dismiss_reminder(
    conn: sqlite3.Connection, reminder_id: int, *, now: datetime | None = None
) -> bool:
    """Dismiss a reminder by id, idempotently.

    Returns ``True`` when this call transitioned an active reminder to
    dismissed, ``False`` when the id is unknown or already dismissed — so a
    Bridge ``dismiss`` control message that arrives twice, or names a reminder
    that no longer exists, is a harmless no-op rather than an error.
    """
    row = conn.execute(
        "SELECT dismissed FROM reminders WHERE id = ?", (reminder_id,)
    ).fetchone()
    if row is None or row[0]:
        return False
    conn.execute(
        "UPDATE reminders SET dismissed = 1, dismissed_at = ? WHERE id = ?",
        ((now or _now()).isoformat(), reminder_id),
    )
    conn.commit()
    return True
