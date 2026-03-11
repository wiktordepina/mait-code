"""Tests for memory CLI tool functions.

Tests call the command functions directly using a temp database.
Embeddings are mocked to avoid model loading overhead and to ensure
deterministic FTS-only behaviour in CLI tests.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.writer import store_memory as db_store

# Mock embed_text at the two import sites (writer and search) so tests
# don't download/load the real model and behaviour is deterministic.
_EMBED_PATCHES = [
    "mait_code.tools.memory.writer.embed_text",
    "mait_code.tools.memory.search.embed_text",
    "mait_code.tools.memory.cli.is_available",
]


@pytest.fixture
def mem_db(tmp_path):
    """Patch connection to use a temp database for memory tool."""
    db_path = tmp_path / "tool_test.db"
    conn = get_connection(db_path)

    @contextmanager
    def patched_connection():
        yield conn

    with (
        patch(
            "mait_code.tools.memory.cli.connection",
            side_effect=patched_connection,
        ),
        patch(_EMBED_PATCHES[0], return_value=None),
        patch(_EMBED_PATCHES[1], return_value=None),
        patch(_EMBED_PATCHES[2], return_value=False),
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
        from mait_code.tools.memory.cli import cmd_search

        args = _make_args(query=["dark", "mode"], limit=10, type=None)
        cmd_search(args)
        out = capsys.readouterr().out
        assert "dark mode" in out
        assert "Found" in out

    def test_no_results(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_search

        args = _make_args(query=["nonexistent_xyz_query"], limit=10, type=None)
        cmd_search(args)
        out = capsys.readouterr().out
        assert "No memories found" in out

    def test_with_type_filter(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_search

        args = _make_args(query=["dark", "mode"], limit=10, type="preference")
        cmd_search(args)
        out = capsys.readouterr().out
        assert "dark mode" in out

    def test_with_limit(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_search

        args = _make_args(
            query=["User", "OR", "Kubernetes", "OR", "linter"], limit=1, type=None
        )
        cmd_search(args)
        out = capsys.readouterr().out
        assert "Found 1" in out


class TestCmdStore:
    def test_store_new(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_store

        args = _make_args(
            content=["New", "fact", "about", "testing"], type="fact", importance=5
        )
        cmd_store(args)
        out = capsys.readouterr().out
        assert "stored" in out.lower()

    def test_store_dedup(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_store

        args = _make_args(
            content=["Repeated", "fact", "about", "testing"], type="fact", importance=5
        )
        cmd_store(args)
        cmd_store(args)
        out = capsys.readouterr().out
        assert "deduplicated" in out.lower()

    def test_empty_content_error(self, mem_db):
        from mait_code.tools.memory.cli import cmd_store

        args = _make_args(content=[""], type="fact", importance=5)
        with pytest.raises(SystemExit):
            cmd_store(args)

    def test_invalid_type_error(self, mem_db):
        from mait_code.tools.memory.cli import cmd_store

        args = _make_args(
            content=["some", "content"], type="invalid_type", importance=5
        )
        with pytest.raises(SystemExit):
            cmd_store(args)


class TestCmdList:
    def test_with_entries(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_list

        args = _make_args(limit=10, type=None, since=None)
        cmd_list(args)
        out = capsys.readouterr().out
        assert "Recent" in out
        assert "dark mode" in out

    def test_empty_db(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_list

        args = _make_args(limit=10, type=None, since=None)
        cmd_list(args)
        out = capsys.readouterr().out
        assert "No memories" in out

    def test_with_type_filter(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_list

        args = _make_args(limit=10, type="preference", since=None)
        cmd_list(args)
        out = capsys.readouterr().out
        assert "dark mode" in out


    def test_with_since_filter(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_list

        args = _make_args(limit=10, type=None, since="24h")
        cmd_list(args)
        out = capsys.readouterr().out
        # Entries were just inserted so should appear in last 24h
        assert "dark mode" in out
        assert "since 24h" in out

    def test_with_since_no_results(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_list

        # Set all entries to old timestamps
        populated_mem_db.execute(
            "UPDATE memory_entries SET created_at = '2020-01-01T00:00:00Z'"
        )
        populated_mem_db.commit()

        args = _make_args(limit=10, type=None, since="24h")
        cmd_list(args)
        out = capsys.readouterr().out
        assert "No memories found" in out


class TestCmdDelete:
    def test_delete_existing(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_delete

        entry_id = populated_mem_db.execute(
            "SELECT id FROM memory_entries LIMIT 1"
        ).fetchone()[0]
        args = _make_args(id=entry_id)
        cmd_delete(args)
        out = capsys.readouterr().out
        assert "deleted" in out.lower()

    def test_delete_not_found(self, mem_db):
        from mait_code.tools.memory.cli import cmd_delete

        args = _make_args(id=99999)
        with pytest.raises(SystemExit):
            cmd_delete(args)


class TestCmdStats:
    def test_with_entries(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_stats

        cmd_stats(None)
        out = capsys.readouterr().out
        assert "Memory Statistics" in out
        assert "3 total" in out
        assert "By type:" in out
        assert "By class:" in out
        assert "Embeddings:" in out

    def test_empty_db(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_stats

        cmd_stats(None)
        out = capsys.readouterr().out
        assert "No memories" in out


class TestCmdReindex:
    def test_reindex_no_model(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_reindex

        with pytest.raises(SystemExit):
            cmd_reindex(None)
        err = capsys.readouterr().err
        assert "embedding model unavailable" in err

    def test_reindex_empty_db(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_reindex

        with (
            patch("mait_code.tools.memory.cli.is_available", return_value=True),
        ):
            cmd_reindex(None)
        out = capsys.readouterr().out
        assert "No memory entries" in out


class TestCmdRestore:
    def test_restore_no_obs_dir(self, mem_db, tmp_path, capsys):
        from mait_code.tools.memory.cli import cmd_restore

        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "nonexistent",
        ):
            args = _make_args(dry_run=False)
            with pytest.raises(SystemExit):
                cmd_restore(args)

    def test_restore_dry_run(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        # Create observation log
        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "timestamp": "2025-01-01T00:00:00Z",
            "trigger": "PreCompact",
            "extraction": {
                "facts": [{"content": "Python uses indentation", "importance": 7}],
                "entities": [{"name": "Python", "entity_type": "tool"}],
                "relationships": [],
            },
        }
        (obs_dir / "2025-01-01.jsonl").write_text(json.dumps(record) + "\n")

        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            args = _make_args(dry_run=True)
            cmd_restore(args)

        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "Memories stored: 1" in out
        assert "Entities upserted: 1" in out

        # Verify nothing was actually written
        count = mem_db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        assert count == 0

    def test_restore_replays_data(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        # Create observation log
        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "timestamp": "2025-01-01T00:00:00Z",
            "trigger": "PreCompact",
            "extraction": {
                "facts": [{"content": "Auth uses JWT RS256", "importance": 8}],
                "preferences": [{"content": "Dark mode preferred", "importance": 6}],
                "entities": [
                    {"name": "Auth Service", "entity_type": "service"},
                ],
                "relationships": [
                    {
                        "source": "Auth Service",
                        "target": "JWT",
                        "relationship_type": "uses",
                        "context": "RS256 signing",
                    }
                ],
            },
        }
        (obs_dir / "2025-01-01.jsonl").write_text(json.dumps(record) + "\n")

        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            args = _make_args(dry_run=False)
            cmd_restore(args)

        out = capsys.readouterr().out
        assert "Memories stored: 2" in out
        assert "Entities upserted: 1" in out
        assert "Relationships upserted: 1" in out

        # Verify data was written
        count = mem_db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        assert count == 2
