"""Tests for the reminders service layer (presentation-agnostic queries)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mait_code.tools.reminders.db import get_connection
from mait_code.tools.reminders.service import (
    active_reminders,
    dismissed_reminders,
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
