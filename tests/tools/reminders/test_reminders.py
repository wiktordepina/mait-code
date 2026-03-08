"""Tests for reminders tool — migrations, CLI commands, and database operations."""

import argparse
import sqlite3
from datetime import timedelta
import pytest

from mait_code.tools.reminders.cli import _now, _parse_when
from mait_code.tools.reminders.migrate import ensure_schema


# --- Migration tests ---


def test_ensure_schema_creates_table(reminders_db: sqlite3.Connection):
    tables = reminders_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    assert "reminders" in table_names
    assert "schema_version" in table_names


def test_ensure_schema_idempotent(reminders_db: sqlite3.Connection):
    ensure_schema(reminders_db)
    ensure_schema(reminders_db)
    versions = reminders_db.execute("SELECT version FROM schema_version").fetchall()
    assert len(versions) == 1
    assert versions[0][0] == 1


def test_reminders_columns(reminders_db: sqlite3.Connection):
    columns = reminders_db.execute("PRAGMA table_info(reminders)").fetchall()
    col_names = [c[1] for c in columns]
    assert col_names == ["id", "what", "due", "created_at", "dismissed", "dismissed_at"]


# --- Helpers ---


def _insert_reminder(conn, what, due, dismissed=False, dismissed_at=None):
    conn.execute(
        "INSERT INTO reminders (what, due, created_at, dismissed, dismissed_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (what, due.isoformat(), _now().isoformat(), int(dismissed), dismissed_at),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# --- CLI command tests ---


def test_cmd_set(mock_conn):
    from mait_code.tools.reminders.cli import cmd_set

    args = argparse.Namespace(when="in 2 hours", what=["deploy", "check"])
    cmd_set(args)

    rows = mock_conn.execute("SELECT what, dismissed FROM reminders").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "deploy check"
    assert rows[0][1] == 0


def test_cmd_list_active(mock_conn, capsys):
    now = _now()
    _insert_reminder(mock_conn, "overdue task", now - timedelta(hours=1))
    _insert_reminder(mock_conn, "future task", now + timedelta(hours=1))
    _insert_reminder(
        mock_conn,
        "done task",
        now + timedelta(hours=2),
        dismissed=True,
        dismissed_at=now.isoformat(),
    )

    from mait_code.tools.reminders.cli import cmd_list

    cmd_list(argparse.Namespace(all=False))
    output = capsys.readouterr().out
    assert "overdue task" in output
    assert "future task" in output
    assert "done task" not in output


def test_cmd_list_all(mock_conn, capsys):
    now = _now()
    _insert_reminder(mock_conn, "active task", now + timedelta(hours=1))
    _insert_reminder(
        mock_conn,
        "dismissed task",
        now + timedelta(hours=2),
        dismissed=True,
        dismissed_at=now.isoformat(),
    )

    from mait_code.tools.reminders.cli import cmd_list

    cmd_list(argparse.Namespace(all=True))
    output = capsys.readouterr().out
    assert "active task" in output
    assert "dismissed task" in output


def test_cmd_dismiss(mock_conn):
    now = _now()
    rid = _insert_reminder(mock_conn, "dismiss me", now + timedelta(hours=1))

    from mait_code.tools.reminders.cli import cmd_dismiss

    cmd_dismiss(argparse.Namespace(id=rid))

    row = mock_conn.execute(
        "SELECT dismissed, dismissed_at FROM reminders WHERE id = ?", (rid,)
    ).fetchone()
    assert row[0] == 1
    assert row[1] is not None


def test_cmd_dismiss_not_found(mock_conn):
    from mait_code.tools.reminders.cli import cmd_dismiss

    with pytest.raises(SystemExit, match="1"):
        cmd_dismiss(argparse.Namespace(id=999))


def test_cmd_check_overdue(mock_conn, capsys):
    now = _now()
    _insert_reminder(mock_conn, "overdue one", now - timedelta(hours=2))
    _insert_reminder(mock_conn, "not yet", now + timedelta(hours=1))

    from mait_code.tools.reminders.cli import cmd_check

    cmd_check(None)
    output = capsys.readouterr().out
    assert "overdue one" in output
    assert "not yet" not in output


def test_cmd_check_no_overdue(mock_conn, capsys):
    now = _now()
    _insert_reminder(mock_conn, "future task", now + timedelta(hours=1))

    from mait_code.tools.reminders.cli import cmd_check

    cmd_check(None)
    output = capsys.readouterr().out
    assert output == ""


# --- Helper tests ---


def test_parse_when_returns_utc():
    result = _parse_when("in 2 hours")
    assert result is not None
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


def test_parse_when_invalid():
    assert _parse_when("not a real time xyzzy") is None
