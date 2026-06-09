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

    def test_store_surfaces_conflict(self, mem_db, capsys):
        """A mid-band conflict prints a contradiction warning with a supersede hint."""
        from mait_code.tools.memory.cli import cmd_store

        original = db_store(mem_db, "The deploy target is staging", "fact", 5)
        args = _make_args(
            content=["The", "deploy", "target", "is", "production"],
            type="fact",
            importance=5,
        )
        with patch(
            "mait_code.tools.memory.writer._vector_candidates",
            return_value=[(original["id"], "The deploy target is staging", 0.75)],
        ):
            cmd_store(args)
        out = capsys.readouterr().out
        assert "stored" in out.lower()
        assert "may contradict" in out
        assert f"#{original['id']}" in out
        assert "supersede" in out


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

    def test_include_superseded_flag(self, populated_mem_db, capsys):
        """--include-superseded surfaces hidden entries with a marker."""
        from mait_code.tools.memory.cli import cmd_list

        target = populated_mem_db.execute(
            "SELECT id FROM memory_entries WHERE content = 'User prefers dark mode'"
        ).fetchone()[0]
        populated_mem_db.execute(
            "UPDATE memory_entries SET superseded_by = -1, "
            "superseded_at = CURRENT_TIMESTAMP WHERE id = ?",
            (target,),
        )
        populated_mem_db.commit()

        # Hidden by default
        cmd_list(_make_args(limit=10, type=None, since=None, include_superseded=False))
        assert "dark mode" not in capsys.readouterr().out

        # Shown (and marked) with the flag
        cmd_list(_make_args(limit=10, type=None, since=None, include_superseded=True))
        out = capsys.readouterr().out
        assert "dark mode" in out
        assert "superseded by #-1" in out


class TestCmdSupersede:
    def test_supersede_success(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_supersede

        old_id = populated_mem_db.execute(
            "SELECT id FROM memory_entries WHERE content = 'User prefers dark mode'"
        ).fetchone()[0]
        args = _make_args(
            old_id=old_id, content=["User", "prefers", "light", "mode"], importance=None
        )
        cmd_supersede(args)
        out = capsys.readouterr().out
        assert f"#{old_id} superseded by #" in out

        row = populated_mem_db.execute(
            "SELECT superseded_by FROM memory_entries WHERE id = ?", (old_id,)
        ).fetchone()
        assert row[0] is not None

    def test_supersede_not_found(self, mem_db):
        from mait_code.tools.memory.cli import cmd_supersede

        args = _make_args(old_id=99999, content=["whatever"], importance=None)
        with pytest.raises(SystemExit):
            cmd_supersede(args)

    def test_supersede_empty_content(self, mem_db):
        from mait_code.tools.memory.cli import cmd_supersede

        args = _make_args(old_id=1, content=[""], importance=None)
        with pytest.raises(SystemExit):
            cmd_supersede(args)


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

    def test_superseded_count(self, populated_mem_db, capsys):
        """The superseded line appears once an entry has been superseded."""
        from mait_code.tools.memory.cli import cmd_stats

        target = populated_mem_db.execute("SELECT id FROM memory_entries").fetchone()[0]
        populated_mem_db.execute(
            "UPDATE memory_entries SET superseded_by = -1, "
            "superseded_at = CURRENT_TIMESTAMP WHERE id = ?",
            (target,),
        )
        populated_mem_db.commit()

        cmd_stats(None)
        out = capsys.readouterr().out
        assert "Superseded" in out
        assert "1" in out


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

    def test_run_reindex_raises_when_unavailable(self, populated_mem_db):
        from mait_code.tools.memory.cli import ReindexError, run_reindex

        with pytest.raises(ReindexError, match="embedding model unavailable"):
            run_reindex()

    def test_run_reindex_returns_count(self, mem_db):
        from mait_code.tools.memory.cli import run_reindex

        with patch("mait_code.tools.memory.cli.is_available", return_value=True):
            assert run_reindex() == 0


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


class TestCmdCanonicalizeProjects:
    def _setup(
        self, tmp_path, monkeypatch, aliases='{"h-cc-bridge": "hermes-cc-bridge"}'
    ):
        import mait_code.context as context_mod

        monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
        context_mod._alias_cache.clear()
        if aliases is not None:
            (tmp_path / "project-aliases.json").write_text(aliases)

    def test_rewrites_aliased_project_slugs(
        self, mem_db, tmp_path, monkeypatch, capsys
    ):
        from mait_code.tools.memory.cli import cmd_canonicalize_projects

        self._setup(tmp_path, monkeypatch)
        # Seed under the old slug via raw SQL — store_memory would canonicalise
        # it on the way in, which is not what we're exercising here.
        mem_db.execute(
            "INSERT INTO memory_entries (content, entry_type, project, scope) "
            "VALUES (?, 'fact', 'h-cc-bridge', 'project')",
            ("token stored in settings.json",),
        )
        mem_db.commit()

        cmd_canonicalize_projects(_make_args(dry_run=False))

        row = mem_db.execute(
            "SELECT project FROM memory_entries WHERE content = ?",
            ("token stored in settings.json",),
        ).fetchone()
        assert row[0] == "hermes-cc-bridge"

        # The AU trigger keeps the FTS shadow in sync with the new slug.
        hits = mem_db.execute(
            "SELECT m.id FROM memory_entries_fts f JOIN memory_entries m ON m.id = f.rowid "
            "WHERE memory_entries_fts MATCH '\"hermes-cc-bridge\"'"
        ).fetchall()
        assert len(hits) == 1

    def test_dry_run_does_not_write(self, mem_db, tmp_path, monkeypatch, capsys):
        from mait_code.tools.memory.cli import cmd_canonicalize_projects

        self._setup(tmp_path, monkeypatch)
        mem_db.execute(
            "INSERT INTO memory_entries (content, entry_type, project, scope) "
            "VALUES (?, 'fact', 'h-cc-bridge', 'project')",
            ("token",),
        )
        mem_db.commit()

        cmd_canonicalize_projects(_make_args(dry_run=True))

        row = mem_db.execute(
            "SELECT project FROM memory_entries WHERE content = ?", ("token",)
        ).fetchone()
        assert row[0] == "h-cc-bridge"  # unchanged

    def test_no_aliases_is_noop(self, mem_db, tmp_path, monkeypatch, capsys):
        from mait_code.tools.memory.cli import cmd_canonicalize_projects

        self._setup(tmp_path, monkeypatch, aliases=None)
        cmd_canonicalize_projects(_make_args(dry_run=False))
        assert "No project aliases configured" in capsys.readouterr().out
