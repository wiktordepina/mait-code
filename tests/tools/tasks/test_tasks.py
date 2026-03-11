"""Tests for tasks tool — migrations, CLI commands, and database operations."""

import argparse
import sqlite3

import pytest

from mait_code.tools.tasks.cli import _now
from mait_code.tools.tasks.migrate import ensure_schema

from tests.tools.tasks.conftest import TEST_PROJECT


# --- Migration tests ---


def test_ensure_schema_creates_tables(tasks_db: sqlite3.Connection):
    tables = tasks_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    assert "tasks" in table_names
    assert "projects" in table_names
    assert "schema_version" in table_names


def test_ensure_schema_idempotent(tasks_db: sqlite3.Connection):
    ensure_schema(tasks_db)
    ensure_schema(tasks_db)
    versions = tasks_db.execute("SELECT version FROM schema_version").fetchall()
    assert len(versions) == 2
    assert versions[-1][0] == 2


def test_tasks_columns(tasks_db: sqlite3.Connection):
    columns = tasks_db.execute("PRAGMA table_info(tasks)").fetchall()
    col_names = [c[1] for c in columns]
    assert col_names == [
        "id", "project", "title", "priority", "status", "created_at", "completed_at"
    ]


def test_projects_columns(tasks_db: sqlite3.Connection):
    columns = tasks_db.execute("PRAGMA table_info(projects)").fetchall()
    col_names = [c[1] for c in columns]
    assert col_names == ["name", "path", "github_url", "added_at"]


# --- Helpers ---


def _insert_task(conn, title, priority="medium", status="open", project=TEST_PROJECT):
    completed_at = _now().isoformat() if status == "done" else None
    conn.execute(
        "INSERT INTO tasks (project, title, priority, status, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project, title, priority, status, _now().isoformat(), completed_at),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _register_project(conn, name, path="/tmp/test"):
    conn.execute(
        "INSERT OR IGNORE INTO projects (name, path) VALUES (?, ?)",
        (name, path),
    )
    conn.commit()


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
    _register_project(mock_conn, "other-project")
    _insert_task(mock_conn, "my task", project=TEST_PROJECT)
    _insert_task(mock_conn, "other task", project="other-project")

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


# --- list-all and projects tests ---


def test_cmd_list_all(mock_conn, capsys):
    _register_project(mock_conn, "project-a")
    _register_project(mock_conn, "project-b")
    _insert_task(mock_conn, "task in a", project="project-a")
    _insert_task(mock_conn, "task in b", project="project-b")
    _insert_task(mock_conn, "done task", project="project-a", status="done")

    from mait_code.tools.tasks.cli import cmd_list_all

    cmd_list_all(None)
    output = capsys.readouterr().out
    assert "task in a" in output
    assert "task in b" in output
    assert "done task" not in output
    assert "project-a:" in output
    assert "project-b:" in output


def test_cmd_list_all_empty(mock_conn, capsys):
    from mait_code.tools.tasks.cli import cmd_list_all

    cmd_list_all(None)
    output = capsys.readouterr().out
    assert "No open tasks" in output


def test_cmd_list_all_priority_order(mock_conn, capsys):
    _insert_task(mock_conn, "low", priority="low")
    _insert_task(mock_conn, "high", priority="high")

    from mait_code.tools.tasks.cli import cmd_list_all

    cmd_list_all(None)
    output = capsys.readouterr().out
    assert output.index("high") < output.index("low")


def test_cmd_projects(mock_conn, capsys):
    from mait_code.tools.tasks.cli import cmd_projects

    cmd_projects(None)
    output = capsys.readouterr().out
    assert TEST_PROJECT in output
    assert "Registered projects" in output


def test_cmd_projects_empty(tasks_db, monkeypatch, capsys):
    """Test projects command with no registered projects."""
    from contextlib import contextmanager

    import mait_code.tools.tasks.cli as cli_mod

    # Use a fresh db with no projects pre-registered
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "empty.db"
        from mait_code.tools.tasks.db import get_connection as _gc

        conn = _gc(db_path)

        @contextmanager
        def fake_connection():
            yield conn

        monkeypatch.setattr(cli_mod, "connection", fake_connection)

        from mait_code.tools.tasks.cli import cmd_projects

        cmd_projects(None)
        output = capsys.readouterr().out
        assert "No projects" in output
        conn.close()


def test_cmd_projects_shows_github_url(mock_conn, capsys):
    mock_conn.execute(
        "UPDATE projects SET github_url = ? WHERE name = ?",
        ("https://github.com/test/repo", TEST_PROJECT),
    )
    mock_conn.commit()

    from mait_code.tools.tasks.cli import cmd_projects

    cmd_projects(None)
    output = capsys.readouterr().out
    assert "github.com/test/repo" in output


# --- ensure_project tests ---


def test_ensure_project_inserts_new(tasks_db):
    from mait_code.tools.tasks.db import ensure_project
    from unittest.mock import patch

    with patch("mait_code.tools.tasks.db.subprocess.run") as mock_run:
        mock_run.side_effect = [
            # git rev-parse --show-toplevel
            type("Result", (), {"returncode": 0, "stdout": "/home/user/my-project\n"})(),
            # git remote get-url origin
            type("Result", (), {"returncode": 0, "stdout": "git@github.com:user/my-project.git\n"})(),
        ]
        ensure_project(tasks_db, "my-project")

    row = tasks_db.execute(
        "SELECT name, path, github_url FROM projects WHERE name = ?",
        ("my-project",),
    ).fetchone()
    assert row is not None
    assert row[0] == "my-project"
    assert row[1] == "/home/user/my-project"
    assert row[2] == "git@github.com:user/my-project.git"


def test_ensure_project_noop_if_exists(tasks_db):
    """ensure_project should not modify an existing project."""
    from mait_code.tools.tasks.db import ensure_project
    from unittest.mock import patch

    original = tasks_db.execute(
        "SELECT path FROM projects WHERE name = ?", (TEST_PROJECT,)
    ).fetchone()

    with patch("mait_code.tools.tasks.db.subprocess.run") as mock_run:
        ensure_project(tasks_db, TEST_PROJECT)
        mock_run.assert_not_called()

    current = tasks_db.execute(
        "SELECT path FROM projects WHERE name = ?", (TEST_PROJECT,)
    ).fetchone()
    assert current == original


def test_ensure_project_no_git(tasks_db):
    """ensure_project should fall back to cwd when git is unavailable."""
    from mait_code.tools.tasks.db import ensure_project
    from unittest.mock import patch

    with patch(
        "mait_code.tools.tasks.db.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        ensure_project(tasks_db, "no-git-project")

    row = tasks_db.execute(
        "SELECT path, github_url FROM projects WHERE name = ?",
        ("no-git-project",),
    ).fetchone()
    assert row is not None
    assert row[0]  # Should have some path (cwd)
    assert row[1] is None  # No github URL


# --- Foreign key enforcement tests ---


def test_fk_rejects_unregistered_project(tasks_db):
    """Inserting a task with an unregistered project should raise IntegrityError."""
    with pytest.raises(sqlite3.IntegrityError):
        tasks_db.execute(
            "INSERT INTO tasks (project, title, priority, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("nonexistent-project", "orphan task", "medium", "open", _now().isoformat()),
        )
