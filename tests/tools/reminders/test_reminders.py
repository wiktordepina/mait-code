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


def test_ensure_schema_supports_callable_migration(monkeypatch, tmp_path):
    """A callable migration body is invoked with the connection.

    The shipped reminders migrations are all SQL-list bodies, so this exercises
    the framework's documented callable branch by injecting a one-off migration.
    """
    from mait_code.tools.reminders import migrate

    called: list[sqlite3.Connection] = []

    def _body(conn: sqlite3.Connection) -> None:
        called.append(conn)
        conn.execute("CREATE TABLE callable_marker (id INTEGER)")

    monkeypatch.setattr(
        migrate, "MIGRATIONS", [*migrate.MIGRATIONS, (999, "callable", _body)]
    )

    conn = sqlite3.connect(tmp_path / "callable.db")
    try:
        migrate.ensure_schema(conn)
        assert called == [conn]
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='callable_marker'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


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


def test_cmd_set_empty_content_exits(mock_conn):
    from mait_code.tools.reminders.cli import cmd_set

    with pytest.raises(SystemExit, match="1"):
        cmd_set(argparse.Namespace(when="in 2 hours", what=[""]))
    # The error bails before any insert.
    assert mock_conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


def test_cmd_set_unparseable_time_exits(mock_conn):
    from mait_code.tools.reminders.cli import cmd_set

    with pytest.raises(SystemExit, match="1"):
        cmd_set(argparse.Namespace(when="not a real time xyzzy", what=["deploy"]))
    assert mock_conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


def test_cmd_list_empty(mock_conn, capsys):
    from mait_code.tools.reminders.cli import cmd_list

    cmd_list(argparse.Namespace(all=False))
    assert "No active reminders." in capsys.readouterr().out


def test_cmd_list_dismissed_only_with_all(mock_conn, capsys):
    # No active reminders, only a dismissed one — the overdue/upcoming blocks are
    # skipped and just the Dismissed section prints.
    now = _now()
    _insert_reminder(
        mock_conn,
        "archived task",
        now + timedelta(hours=1),
        dismissed=True,
        dismissed_at=now.isoformat(),
    )

    from mait_code.tools.reminders.cli import cmd_list

    cmd_list(argparse.Namespace(all=True))
    output = capsys.readouterr().out
    assert "Dismissed (1)" in output
    assert "archived task" in output
    assert "OVERDUE" not in output
    assert "Upcoming" not in output


def test_cmd_dismiss_already_dismissed(mock_conn, capsys):
    now = _now()
    rid = _insert_reminder(
        mock_conn,
        "already gone",
        now + timedelta(hours=1),
        dismissed=True,
        dismissed_at=now.isoformat(),
    )

    from mait_code.tools.reminders.cli import cmd_dismiss

    cmd_dismiss(argparse.Namespace(id=rid))
    assert f"#{rid} is already dismissed" in capsys.readouterr().out


# --- main() dispatch ---


def test_main_dispatches_subcommand(mock_conn, capsys, monkeypatch):
    now = _now()
    _insert_reminder(mock_conn, "overdue via main", now - timedelta(hours=1))
    monkeypatch.setattr("sys.argv", ["mc-tool-reminders", "check"])

    from mait_code.tools.reminders.cli import main

    main()
    assert "overdue via main" in capsys.readouterr().out


def test_main_requires_a_subcommand(monkeypatch):
    # The subparser is ``required=True`` — a bare invocation is a usage error.
    monkeypatch.setattr("sys.argv", ["mc-tool-reminders"])

    from mait_code.tools.reminders.cli import main

    with pytest.raises(SystemExit):
        main()


# --- Helper tests ---


def test_parse_when_returns_utc():
    result = _parse_when("in 2 hours")
    assert result is not None
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)


def test_parse_when_invalid():
    assert _parse_when("not a real time xyzzy") is None
