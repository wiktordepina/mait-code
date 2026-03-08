"""Tests for tasks tool — migrations, CLI commands, and database operations."""

import argparse
import sqlite3

import pytest

from mait_code.tools.tasks.cli import _now
from mait_code.tools.tasks.migrate import ensure_schema


# --- Migration tests ---


def test_ensure_schema_creates_table(tasks_db: sqlite3.Connection):
    tables = tasks_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    assert "tasks" in table_names
    assert "schema_version" in table_names


def test_ensure_schema_idempotent(tasks_db: sqlite3.Connection):
    ensure_schema(tasks_db)
    ensure_schema(tasks_db)
    versions = tasks_db.execute("SELECT version FROM schema_version").fetchall()
    assert len(versions) == 1
    assert versions[0][0] == 1


def test_tasks_columns(tasks_db: sqlite3.Connection):
    columns = tasks_db.execute("PRAGMA table_info(tasks)").fetchall()
    col_names = [c[1] for c in columns]
    assert col_names == [
        "id", "project", "title", "priority", "status", "created_at", "completed_at"
    ]


# --- Helpers ---


def _insert_task(conn, title, priority="medium", status="open", project="test-project"):
    completed_at = _now().isoformat() if status == "done" else None
    conn.execute(
        "INSERT INTO tasks (project, title, priority, status, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project, title, priority, status, _now().isoformat(), completed_at),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# --- CLI command tests ---


def test_cmd_add(mock_conn, capsys):
    from mait_code.tools.tasks.cli import cmd_add

    args = argparse.Namespace(title=["Fix", "login", "bug"], priority="medium")
    cmd_add(args)

    rows = mock_conn.execute("SELECT title, priority, status FROM tasks").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Fix login bug"
    assert rows[0][1] == "medium"
    assert rows[0][2] == "open"

    output = capsys.readouterr().out
    assert "Fix login bug" in output


def test_cmd_add_with_priority(mock_conn, capsys):
    from mait_code.tools.tasks.cli import cmd_add

    args = argparse.Namespace(title=["Critical", "fix"], priority="high")
    cmd_add(args)

    rows = mock_conn.execute("SELECT priority FROM tasks").fetchall()
    assert rows[0][0] == "high"


def test_cmd_add_empty_title(mock_conn):
    from mait_code.tools.tasks.cli import cmd_add

    with pytest.raises(SystemExit, match="1"):
        cmd_add(argparse.Namespace(title=["  "], priority="medium"))


def test_cmd_list_open(mock_conn, capsys):
    _insert_task(mock_conn, "open task")
    _insert_task(mock_conn, "done task", status="done")

    from mait_code.tools.tasks.cli import cmd_list

    cmd_list(argparse.Namespace(all=False))
    output = capsys.readouterr().out
    assert "open task" in output
    assert "done task" not in output


def test_cmd_list_all(mock_conn, capsys):
    _insert_task(mock_conn, "open task")
    _insert_task(mock_conn, "done task", status="done")

    from mait_code.tools.tasks.cli import cmd_list

    cmd_list(argparse.Namespace(all=True))
    output = capsys.readouterr().out
    assert "open task" in output
    assert "done task" in output


def test_cmd_list_empty(mock_conn, capsys):
    from mait_code.tools.tasks.cli import cmd_list

    cmd_list(argparse.Namespace(all=False))
    output = capsys.readouterr().out
    assert "No tasks" in output


def test_cmd_list_project_scoped(mock_conn, capsys):
    _insert_task(mock_conn, "my task", project="test-project")
    _insert_task(mock_conn, "other task", project="/other/project")

    from mait_code.tools.tasks.cli import cmd_list

    cmd_list(argparse.Namespace(all=False))
    output = capsys.readouterr().out
    assert "my task" in output
    assert "other task" not in output


def test_cmd_list_priority_order(mock_conn, capsys):
    _insert_task(mock_conn, "low task", priority="low")
    _insert_task(mock_conn, "high task", priority="high")
    _insert_task(mock_conn, "medium task", priority="medium")

    from mait_code.tools.tasks.cli import cmd_list

    cmd_list(argparse.Namespace(all=False))
    output = capsys.readouterr().out
    high_pos = output.index("high task")
    medium_pos = output.index("medium task")
    low_pos = output.index("low task")
    assert high_pos < medium_pos < low_pos


def test_cmd_done(mock_conn, capsys):
    tid = _insert_task(mock_conn, "finish me")

    from mait_code.tools.tasks.cli import cmd_done

    cmd_done(argparse.Namespace(id=tid))

    row = mock_conn.execute(
        "SELECT status, completed_at FROM tasks WHERE id = ?", (tid,)
    ).fetchone()
    assert row[0] == "done"
    assert row[1] is not None

    output = capsys.readouterr().out
    assert "completed" in output


def test_cmd_done_already_done(mock_conn, capsys):
    tid = _insert_task(mock_conn, "already done", status="done")

    from mait_code.tools.tasks.cli import cmd_done

    cmd_done(argparse.Namespace(id=tid))

    output = capsys.readouterr().out
    assert "already completed" in output


def test_cmd_done_not_found(mock_conn):
    from mait_code.tools.tasks.cli import cmd_done

    with pytest.raises(SystemExit, match="1"):
        cmd_done(argparse.Namespace(id=999))


def test_cmd_remove(mock_conn, capsys):
    tid = _insert_task(mock_conn, "remove me")

    from mait_code.tools.tasks.cli import cmd_remove

    cmd_remove(argparse.Namespace(id=tid))

    row = mock_conn.execute(
        "SELECT id FROM tasks WHERE id = ?", (tid,)
    ).fetchone()
    assert row is None

    output = capsys.readouterr().out
    assert "removed" in output


def test_cmd_remove_not_found(mock_conn):
    from mait_code.tools.tasks.cli import cmd_remove

    with pytest.raises(SystemExit, match="1"):
        cmd_remove(argparse.Namespace(id=999))


def test_cmd_check(mock_conn, capsys):
    _insert_task(mock_conn, "open task", priority="high")
    _insert_task(mock_conn, "done task", status="done")

    from mait_code.tools.tasks.cli import cmd_check

    cmd_check(argparse.Namespace(project="test-project"))
    output = capsys.readouterr().out
    assert "open task" in output
    assert "done task" not in output


def test_cmd_check_no_tasks(mock_conn, capsys):
    from mait_code.tools.tasks.cli import cmd_check

    cmd_check(argparse.Namespace(project="test-project"))
    output = capsys.readouterr().out
    assert output == ""
