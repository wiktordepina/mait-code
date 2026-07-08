"""Tests for the reminders service layer (presentation-agnostic queries)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mait_code.tools.reminders.db import get_connection
from mait_code.tools.reminders.service import (
    active_reminders,
    dismiss_reminder,
    dismissed_reminders,
    due_unnotified,
    mark_notified,
    overdue_reminders,
)

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path: Path):
    connection = get_connection(tmp_path / "reminders.db")
    yield connection
    connection.close()


def _seed(conn, what: str, due: datetime, *, dismissed: bool = False) -> None:
    conn.execute(
        "INSERT INTO reminders (what, due, created_at, dismissed) VALUES (?, ?, ?, ?)",
        (what, due.isoformat(), NOW.isoformat(), int(dismissed)),
    )
    conn.commit()


def test_active_reminders_split_and_order(conn) -> None:
    _seed(conn, "way overdue", NOW - timedelta(days=2))
    _seed(conn, "just overdue", NOW - timedelta(minutes=5))
    _seed(conn, "soon", NOW + timedelta(hours=1))
    _seed(conn, "later", NOW + timedelta(days=3))

    overdue, upcoming = active_reminders(conn, now=NOW)
    assert [r["what"] for r in overdue] == ["way overdue", "just overdue"]
    assert [r["what"] for r in upcoming] == ["soon", "later"]


def test_active_reminders_parses_due(conn) -> None:
    due = NOW + timedelta(hours=1)
    _seed(conn, "soon", due)

    _, upcoming = active_reminders(conn, now=NOW)
    assert upcoming[0]["due"] == due  # datetime, not the stored string


def test_due_exactly_now_is_overdue(conn) -> None:
    _seed(conn, "right now", NOW)
    overdue, upcoming = active_reminders(conn, now=NOW)
    assert [r["what"] for r in overdue] == ["right now"]
    assert upcoming == []


def test_dismissed_excluded_from_active(conn) -> None:
    _seed(conn, "gone", NOW - timedelta(days=1), dismissed=True)
    _seed(conn, "live", NOW - timedelta(days=1))

    assert [r["what"] for r in overdue_reminders(conn, now=NOW)] == ["live"]
    assert [r["what"] for r in dismissed_reminders(conn)] == ["gone"]


def test_empty_store(conn) -> None:
    assert active_reminders(conn, now=NOW) == ([], [])
    assert overdue_reminders(conn, now=NOW) == []
    assert dismissed_reminders(conn) == []


# --- Bridge-outbound helpers (notify de-dup + dismissal) --------------------


def _id_of(conn, what: str) -> int:
    return conn.execute("SELECT id FROM reminders WHERE what = ?", (what,)).fetchone()[0]


def test_dismiss_reminder_transitions_once(conn) -> None:
    _seed(conn, "live", NOW - timedelta(days=1))
    rid = _id_of(conn, "live")
    assert dismiss_reminder(conn, rid) is True
    assert [r["what"] for r in dismissed_reminders(conn)] == ["live"]
    # A second dismiss (or an unknown id) is a harmless no-op.
    assert dismiss_reminder(conn, rid) is False
    assert dismiss_reminder(conn, 9999) is False


def test_due_unnotified_filters_by_due_dismissed_and_notified(conn) -> None:
    _seed(conn, "overdue", NOW - timedelta(hours=1))
    _seed(conn, "upcoming", NOW + timedelta(hours=1))
    _seed(conn, "gone", NOW - timedelta(hours=1), dismissed=True)
    _seed(conn, "already-sent", NOW - timedelta(hours=1))
    mark_notified(conn, [_id_of(conn, "already-sent")], now=NOW)

    due = due_unnotified(conn, now=NOW)
    assert [r["what"] for r in due] == ["overdue"]


def test_mark_notified_removes_from_due(conn) -> None:
    _seed(conn, "overdue", NOW - timedelta(hours=1))
    rid = _id_of(conn, "overdue")
    assert [r["id"] for r in due_unnotified(conn, now=NOW)] == [rid]
    mark_notified(conn, [rid], now=NOW)
    assert due_unnotified(conn, now=NOW) == []
    mark_notified(conn, [])  # empty is a no-op
