"""Tests for memory CLI tool functions.

Tests call the command functions directly using a temp database.
"""

from unittest.mock import patch

import pytest

from mait_code.memory.db import get_connection
from mait_code.memory.writer import store_memory as db_store


@pytest.fixture
def mem_db(tmp_path):
    """Patch get_connection to use a temp database for memory tool."""
    db_path = tmp_path / "tool_test.db"
    conn = get_connection(db_path)

    def patched_get_connection(**_kwargs):
        return get_connection(db_path)

    with patch(
        "mait_code.tools.memory.get_connection", side_effect=patched_get_connection
    ):
        yield conn

    conn.close()


@pytest.fixture
def populated_mem_db(mem_db):
    """Memory test DB with sample data."""
    entries = [
        ("User prefers dark mode", "preference", 8),
        ("Kubernetes uses namespace default", "fact", 6),
        ("Always run linter before commit", "insight", 7),
    ]
    for content, entry_type, importance in entries:
        db_store(mem_db, content, entry_type, importance)
    return mem_db


def _make_args(**kwargs):
    """Create a simple namespace to simulate parsed args."""

    class Args:
        pass

    args = Args()
    for k, v in kwargs.items():
        setattr(args, k, v)
    return args


class TestCmdSearch:
    def test_returns_results(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_search

        args = _make_args(query=["dark", "mode"], limit=10, type=None)
        cmd_search(args)
        out = capsys.readouterr().out
        assert "dark mode" in out
        assert "Found" in out

    def test_no_results(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_search

        args = _make_args(query=["nonexistent_xyz_query"], limit=10, type=None)
        cmd_search(args)
        out = capsys.readouterr().out
        assert "No memories found" in out

    def test_with_type_filter(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_search

        args = _make_args(query=["dark", "mode"], limit=10, type="preference")
        cmd_search(args)
        out = capsys.readouterr().out
        assert "dark mode" in out

    def test_with_limit(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_search

        args = _make_args(
            query=["User", "OR", "Kubernetes", "OR", "linter"], limit=1, type=None
        )
        cmd_search(args)
        out = capsys.readouterr().out
        assert "Found 1" in out


class TestCmdStore:
    def test_store_new(self, mem_db, capsys):
        from mait_code.tools.memory import cmd_store

        args = _make_args(
            content=["New", "fact", "about", "testing"], type="fact", importance=5
        )
        cmd_store(args)
        out = capsys.readouterr().out
        assert "stored" in out.lower()

    def test_store_dedup(self, mem_db, capsys):
        from mait_code.tools.memory import cmd_store

        args = _make_args(
            content=["Repeated", "fact", "about", "testing"], type="fact", importance=5
        )
        cmd_store(args)
        cmd_store(args)
        out = capsys.readouterr().out
        assert "deduplicated" in out.lower()

    def test_empty_content_error(self, mem_db):
        from mait_code.tools.memory import cmd_store

        args = _make_args(content=[""], type="fact", importance=5)
        with pytest.raises(SystemExit):
            cmd_store(args)

    def test_invalid_type_error(self, mem_db):
        from mait_code.tools.memory import cmd_store

        args = _make_args(content=["some", "content"], type="invalid_type", importance=5)
        with pytest.raises(SystemExit):
            cmd_store(args)


class TestCmdList:
    def test_with_entries(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_list

        args = _make_args(limit=10, type=None)
        cmd_list(args)
        out = capsys.readouterr().out
        assert "Recent" in out
        assert "dark mode" in out

    def test_empty_db(self, mem_db, capsys):
        from mait_code.tools.memory import cmd_list

        args = _make_args(limit=10, type=None)
        cmd_list(args)
        out = capsys.readouterr().out
        assert "No memories" in out

    def test_with_type_filter(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_list

        args = _make_args(limit=10, type="preference")
        cmd_list(args)
        out = capsys.readouterr().out
        assert "dark mode" in out


class TestCmdDelete:
    def test_delete_existing(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_delete

        entry_id = populated_mem_db.execute(
            "SELECT id FROM memory_entries LIMIT 1"
        ).fetchone()[0]
        args = _make_args(id=entry_id)
        cmd_delete(args)
        out = capsys.readouterr().out
        assert "deleted" in out.lower()

    def test_delete_not_found(self, mem_db):
        from mait_code.tools.memory import cmd_delete

        args = _make_args(id=99999)
        with pytest.raises(SystemExit):
            cmd_delete(args)


class TestCmdStats:
    def test_with_entries(self, populated_mem_db, capsys):
        from mait_code.tools.memory import cmd_stats

        cmd_stats(None)
        out = capsys.readouterr().out
        assert "Memory Statistics" in out
        assert "3 total" in out
        assert "By type:" in out
        assert "By class:" in out

    def test_empty_db(self, mem_db, capsys):
        from mait_code.tools.memory import cmd_stats

        cmd_stats(None)
        out = capsys.readouterr().out
        assert "No memories" in out
