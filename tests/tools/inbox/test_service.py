"""Unit tests for the inbox service layer.

These exercise :mod:`mait_code.tools.inbox.service` directly on a temp
connection — the function-level analogue of the end-to-end CLI tests in
``test_inbox.py``.
"""

import sqlite3

import pytest

from mait_code.tools.inbox import service

from tests.tools.inbox.conftest import TEST_PROJECT


def test_add_and_list_oldest_first(inbox_db: sqlite3.Connection):
    service.add_item(inbox_db, body="first", project=TEST_PROJECT)
    service.add_item(inbox_db, body="second", project=TEST_PROJECT)
    bodies = [i["body"] for i in service.list_items(inbox_db)]
    assert bodies == ["first", "second"]


def test_list_is_global_but_project_filterable(inbox_db: sqlite3.Connection):
    service.add_item(inbox_db, body="a", project="proj-a")
    service.add_item(inbox_db, body="b", project="proj-b")
    assert len(service.list_items(inbox_db)) == 2
    filtered = [i["body"] for i in service.list_items(inbox_db, project="proj-a")]
    assert filtered == ["a"]


def test_add_item_without_project(inbox_db: sqlite3.Connection):
    item_id = service.add_item(inbox_db, body="no project")
    item = service.get_item(inbox_db, item_id)
    assert item is not None
    assert item["project"] is None


def test_count_items(inbox_db: sqlite3.Connection):
    assert service.count_items(inbox_db) == 0
    service.add_item(inbox_db, body="x")
    service.add_item(inbox_db, body="y")
    assert service.count_items(inbox_db) == 2


def test_count_items_project_filtered(inbox_db: sqlite3.Connection):
    """Passing a project counts only that capture context, not the whole inbox."""
    service.add_item(inbox_db, body="a", project="proj-a")
    service.add_item(inbox_db, body="b", project="proj-b")
    service.add_item(inbox_db, body="c", project="proj-a")
    assert service.count_items(inbox_db, project="proj-a") == 2
    assert service.count_items(inbox_db, project="proj-b") == 1


def test_get_item_missing_returns_none(inbox_db: sqlite3.Connection):
    assert service.get_item(inbox_db, 999) is None


def test_remove_item(inbox_db: sqlite3.Connection):
    item_id = service.add_item(inbox_db, body="gone")
    service.remove_item(inbox_db, item_id)
    assert service.count_items(inbox_db) == 0


def test_remove_missing_raises(inbox_db: sqlite3.Connection):
    with pytest.raises(service.ItemNotFound):
        service.remove_item(inbox_db, 999)


# --- db helper tests ---


def test_get_project_delegates_to_context(monkeypatch):
    """``get_project`` returns the context project when one is detected."""
    from mait_code.tools.inbox import db

    monkeypatch.setattr("mait_code.context.get_project", lambda: "detected-project")
    assert db.get_project() == "detected-project"


def test_get_project_falls_back_to_cwd_name(monkeypatch):
    """With no context project, fall back to the current directory's name."""
    from pathlib import Path

    from mait_code.tools.inbox import db

    monkeypatch.setattr("mait_code.context.get_project", lambda: None)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("/tmp/widgets")))
    assert db.get_project() == "widgets"


# --- migration framework tests ---


def test_ensure_schema_supports_callable_migration(monkeypatch, tmp_path):
    """A callable migration body is invoked with the connection.

    The shipped inbox migrations are all SQL-list bodies, so this exercises the
    framework's documented callable branch by injecting a one-off migration.
    """
    from mait_code.tools.inbox import migrate

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
