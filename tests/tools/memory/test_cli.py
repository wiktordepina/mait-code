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
    def patched_connection(db_path=None):
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

    @staticmethod
    def _embed_one_entry(conn) -> None:
        """Hand-embed the first entry so the missing set is the other two."""
        from mait_code.tools.memory.embeddings import serialize_f32

        first = conn.execute("SELECT id FROM memory_entries ORDER BY id").fetchone()[0]
        conn.execute(
            "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
            (first, serialize_f32([0.5] * 768)),
        )
        conn.commit()

    @staticmethod
    def _reindex_patches():
        return (
            patch("mait_code.tools.memory.cli.is_available", return_value=True),
            patch(
                "mait_code.tools.memory.cli.check_dimension_match",
                return_value=(True, 768, 768),
            ),
            patch(
                "mait_code.tools.memory.cli.embed_texts",
                side_effect=lambda texts, prefix: [[0.1] * 768 for _ in texts],
            ),
        )

    def test_run_reindex_missing_only_skips_embedded(self, populated_mem_db):
        from mait_code.tools.memory.cli import run_reindex

        self._embed_one_entry(populated_mem_db)
        available, dim_match, embed = self._reindex_patches()
        with available, dim_match, embed as embed_mock:
            assert run_reindex(missing_only=True) == 2
        # The pre-embedded entry was never re-sent to the model.
        sent = [t for call in embed_mock.call_args_list for t in call.args[0]]
        assert "User prefers dark mode" not in sent
        n_vec = populated_mem_db.execute("SELECT COUNT(*) FROM memory_vec").fetchone()
        assert n_vec[0] == 3

    def test_run_reindex_full_reembeds_everything(self, populated_mem_db):
        from mait_code.tools.memory.cli import run_reindex

        self._embed_one_entry(populated_mem_db)
        available, dim_match, embed = self._reindex_patches()
        with available, dim_match, embed:
            assert run_reindex() == 3

    def test_run_reindex_missing_only_noop_when_complete(
        self, populated_mem_db, capsys
    ):
        from mait_code.tools.memory.cli import run_reindex

        available, dim_match, embed = self._reindex_patches()
        with available, dim_match, embed:
            assert run_reindex(missing_only=True) == 3  # first run fills the gap
            assert run_reindex(missing_only=True) == 0  # second finds nothing
        assert "Nothing to embed" in capsys.readouterr().out


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


class TestCmdEntitiesMerge:
    def _seed(self, conn):
        from mait_code.tools.memory.entities import upsert_entity, upsert_relationship

        user = upsert_entity(conn, "User", "unknown")
        wiktor = upsert_entity(conn, "Wiktor", "person")
        ghostty = upsert_entity(conn, "Ghostty", "tool")
        upsert_relationship(conn, user, ghostty, "uses", "terminal")
        return wiktor

    def test_merge_success(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_entities

        self._seed(mem_db)
        cmd_entities(_make_args(query=["merge", "User", "Wiktor"], limit=20))
        out = capsys.readouterr().out
        assert "Merged 'User' into" in out
        assert "Wiktor" in out
        assert "repointed: 1" in out

    def test_merge_wrong_arity(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_entities

        with pytest.raises(SystemExit):
            cmd_entities(_make_args(query=["merge", "User"], limit=20))
        assert "Usage: entities merge" in capsys.readouterr().err

    def test_merge_missing_entity(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_entities

        self._seed(mem_db)
        with pytest.raises(SystemExit):
            cmd_entities(_make_args(query=["merge", "Nobody", "Wiktor"], limit=20))
        assert "not found" in capsys.readouterr().err


# --- Search modes beyond hybrid ---


class TestCmdSearchModes:
    """The ``--mode`` flag switches between hybrid, fts, and vector search."""

    def test_empty_query_exits(self, mem_db):
        from mait_code.tools.memory.cli import cmd_search

        # A whitespace-only query is rejected before any DB access.
        args = _make_args(query=["   "], limit=10, type=None, mode="hybrid")
        with pytest.raises(SystemExit):
            cmd_search(args)

    def test_fts_mode(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_search

        args = _make_args(query=["dark", "mode"], limit=10, type=None, mode="fts")
        cmd_search(args)
        out = capsys.readouterr().out
        assert "dark mode" in out
        assert "Found" in out

    def test_vector_mode_surfaces_similarity_as_relevance(
        self, populated_mem_db, capsys
    ):
        from mait_code.tools.memory.cli import cmd_search

        # vector_search_entries normally needs an embedding model; stub it to
        # return a hand-built hit carrying a ``similarity`` key, which the
        # vector branch renames to ``relevance``.
        hit = populated_mem_db.execute(
            "SELECT id, content, entry_type, importance, created_at, scope, "
            "project, branch, memory_class FROM memory_entries LIMIT 1"
        ).fetchone()
        result = {
            "id": hit[0],
            "content": hit[1],
            "entry_type": hit[2],
            "importance": hit[3],
            "created_at": hit[4],
            "scope": hit[5],
            "project": hit[6],
            "branch": hit[7],
            "memory_class": hit[8],
            "similarity": 0.91,
        }
        args = _make_args(query=["anything"], limit=10, type=None, mode="vector")
        with patch(
            "mait_code.tools.memory.cli.vector_search_entries",
            return_value=[result],
        ):
            cmd_search(args)
        out = capsys.readouterr().out
        assert "Found 1" in out
        assert hit[1] in out


# --- Store scope resolution ---


class TestFormatScopeLabel:
    """The display label collapses scope/project/branch into one string."""

    def test_global(self):
        from mait_code.tools.memory.cli import _format_scope_label

        assert _format_scope_label({"scope": "global"}) == "global"

    def test_branch(self):
        from mait_code.tools.memory.cli import _format_scope_label

        label = _format_scope_label(
            {"scope": "branch", "project": "proj", "branch": "feat"}
        )
        assert label == "proj:feat"

    def test_project(self):
        from mait_code.tools.memory.cli import _format_scope_label

        assert _format_scope_label({"scope": "project", "project": "proj"}) == "proj"

    def test_unknown_scope_without_project_falls_back_to_scope(self):
        from mait_code.tools.memory.cli import _format_scope_label

        # Neither global nor a (branch+branch) nor a project present, so the
        # raw scope value is returned unchanged.
        assert _format_scope_label({"scope": "session"}) == "session"


class TestCmdStoreScope:
    """Scope is derived from explicit --scope, then context, then 'global'."""

    def test_global_when_no_context(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_store

        # No explicit scope and no project/branch in context -> global.
        args = _make_args(
            content=["floating", "fact"],
            type="fact",
            importance=5,
            scope=None,
            project=None,
            branch=None,
        )
        with patch(
            "mait_code.tools.memory.cli.get_context",
            return_value={"project": None, "branch": None, "scope": None},
        ):
            cmd_store(args)
        out = capsys.readouterr().out
        assert "scope=global" in out
        row = mem_db.execute(
            "SELECT scope FROM memory_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[0] == "global"

    def test_explicit_scope_honoured(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_store

        args = _make_args(
            content=["explicitly", "global"],
            type="fact",
            importance=5,
            scope="global",
            project="some-proj",
            branch=None,
        )
        cmd_store(args)
        out = capsys.readouterr().out
        assert "scope=global" in out
        # Global scope strips the project so it is not stored against one.
        row = mem_db.execute(
            "SELECT scope, project FROM memory_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[0] == "global"
        assert row[1] is None

    def test_branch_context_implies_branch_scope(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_store

        # No explicit --scope, but a branch in context -> scope=branch.
        args = _make_args(
            content=["on", "a", "branch"],
            type="fact",
            importance=5,
            scope=None,
            project="proj-x",
            branch="feature-y",
        )
        cmd_store(args)
        out = capsys.readouterr().out
        assert "scope=proj-x:feature-y" in out
        row = mem_db.execute(
            "SELECT scope, project, branch FROM memory_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row == ("branch", "proj-x", "feature-y")

    def test_project_context_implies_project_scope(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_store

        # Project but no branch -> scope=project. _resolve_context would
        # otherwise autodetect the running repo's branch, so pin the context.
        args = _make_args(
            content=["on", "a", "project"],
            type="fact",
            importance=5,
            scope=None,
            project="proj-z",
            branch=None,
        )
        with patch(
            "mait_code.tools.memory.cli.get_context",
            return_value={"project": "proj-z", "branch": None, "scope": None},
        ):
            cmd_store(args)
        out = capsys.readouterr().out
        assert "scope=proj-z" in out
        row = mem_db.execute(
            "SELECT scope, project, branch FROM memory_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row == ("project", "proj-z", None)


# --- Entity search (non-merge path) ---


class TestCmdEntitiesSearch:
    def _seed(self, conn):
        from mait_code.tools.memory.entities import upsert_entity, upsert_relationship

        wiktor = upsert_entity(conn, "Wiktor", "person")
        cody = upsert_entity(conn, "Cody", "concept")
        upsert_relationship(conn, wiktor, cody, "owns", "the whippet")
        return wiktor, cody

    def test_list_all_entities(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_entities

        self._seed(mem_db)
        # An empty query lists every entity with its relationship count.
        cmd_entities(_make_args(query=[], limit=20))
        out = capsys.readouterr().out
        assert "Wiktor" in out
        assert "Cody" in out
        assert "relationships" in out

    def test_search_with_query(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_entities

        self._seed(mem_db)
        cmd_entities(_make_args(query=["Wiktor"], limit=20))
        out = capsys.readouterr().out
        assert "matching" in out
        assert "Wiktor" in out

    def test_no_entities_found(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_entities

        cmd_entities(_make_args(query=["nonexistent_entity_zzz"], limit=20))
        out = capsys.readouterr().out
        assert "No entities found" in out


# --- Relationships command ---


class TestCmdRelationships:
    def _seed(self, conn):
        from mait_code.tools.memory.entities import upsert_entity, upsert_relationship

        wiktor = upsert_entity(conn, "Wiktor", "person")
        cody = upsert_entity(conn, "Cody", "concept")
        aws = upsert_entity(conn, "AWS", "service")
        # Wiktor is the source of one relationship and the target of another,
        # so both the outgoing (→) and incoming (←) render branches are hit.
        upsert_relationship(conn, wiktor, cody, "owns", "the whippet")
        upsert_relationship(conn, aws, wiktor, "managed_by", "")
        return wiktor

    def test_outgoing_and_incoming(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_relationships

        self._seed(mem_db)
        cmd_relationships(_make_args(entity=["Wiktor"]))
        out = capsys.readouterr().out
        assert "Relationships for 'Wiktor'" in out
        assert "→" in out  # outgoing edge
        assert "←" in out  # incoming edge
        assert "the whippet" in out  # context line for the outgoing edge

    def test_entity_not_found(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_relationships

        with pytest.raises(SystemExit):
            cmd_relationships(_make_args(entity=["Ghost"]))
        assert "not found" in capsys.readouterr().err

    def test_entity_without_relationships(self, mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_relationships
        from mait_code.tools.memory.entities import upsert_entity

        upsert_entity(mem_db, "Lonely", "concept")
        cmd_relationships(_make_args(entity=["Lonely"]))
        out = capsys.readouterr().out
        assert "No relationships found" in out


# --- Reindex internals: failure and dimension-mismatch paths ---


class TestReindexInternals:
    def test_embed_missing_propagates_embedding_failure(self, populated_mem_db):
        """A ``None`` from embed_texts is surfaced as a ReindexError."""
        from mait_code.tools.memory.cli import ReindexError, _embed_missing

        with patch("mait_code.tools.memory.cli.embed_texts", return_value=None):
            with pytest.raises(ReindexError, match="embedding failed"):
                _embed_missing(populated_mem_db)

    def test_reindex_embeddings_tolerates_missing_vec_table(self, populated_mem_db):
        """_reindex_embeddings swallows a DELETE error if the vec table is gone."""
        from mait_code.tools.memory.cli import _reindex_embeddings

        populated_mem_db.execute("DROP TABLE IF EXISTS memory_vec")
        populated_mem_db.commit()

        with patch(
            "mait_code.tools.memory.cli.embed_texts",
            side_effect=lambda texts, prefix: [[0.1] * 768 for _ in texts],
        ):
            # The DELETE fails silently; recreate the table first so the
            # subsequent INSERTs land somewhere.
            from mait_code.tools.memory.cli import _recreate_vec_table

            _recreate_vec_table(populated_mem_db, 768)
            assert _reindex_embeddings(populated_mem_db) == 3

    def test_reindex_swallows_delete_error(self, populated_mem_db):
        """A failing ``DELETE FROM memory_vec`` is swallowed, not raised."""
        from mait_code.tools.memory.cli import _reindex_embeddings

        # sqlite3.Connection.execute is read-only, so wrap the connection in a
        # thin proxy that fails only the clearing DELETE and forwards the rest.
        class FlakyConn:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, *params):
                if sql.strip().upper().startswith("DELETE FROM MEMORY_VEC"):
                    raise RuntimeError("locked")
                return self._inner.execute(sql, *params)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        conn = FlakyConn(populated_mem_db)
        with patch(
            "mait_code.tools.memory.cli.embed_texts",
            side_effect=lambda texts, prefix: [[0.1] * 768 for _ in texts],
        ):
            # The DELETE error is caught; embedding then proceeds over all 3.
            assert _reindex_embeddings(conn) == 3

    def test_recreate_vec_table_changes_dimension(self, populated_mem_db):
        from mait_code.tools.memory.cli import _recreate_vec_table

        _recreate_vec_table(populated_mem_db, 256)
        # The freshly created vec table accepts a 256-d vector.
        from mait_code.tools.memory.embeddings import serialize_f32

        first = populated_mem_db.execute(
            "SELECT id FROM memory_entries ORDER BY id LIMIT 1"
        ).fetchone()[0]
        populated_mem_db.execute(
            "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
            (first, serialize_f32([0.2] * 256)),
        )
        populated_mem_db.commit()
        assert (
            populated_mem_db.execute("SELECT COUNT(*) FROM memory_vec").fetchone()[0]
            == 1
        )

    def test_run_reindex_recreates_on_dimension_mismatch(self, populated_mem_db):
        from mait_code.tools.memory.cli import run_reindex

        with (
            patch("mait_code.tools.memory.cli.is_available", return_value=True),
            patch(
                "mait_code.tools.memory.cli.check_dimension_match",
                return_value=(False, 256, 768),
            ),
            patch(
                "mait_code.tools.memory.cli.embed_texts",
                side_effect=lambda texts, prefix: [[0.1] * 768 for _ in texts],
            ),
        ):
            # Mismatch triggers a vec-table rebuild at 768d, then embeds all 7.
            assert run_reindex() == 3

    def test_run_reindex_bedrock_hint(self, populated_mem_db, capsys):
        """When the unavailable provider is bedrock, the hint names boto3."""
        from mait_code.tools.memory.cli import ReindexError, run_reindex

        with (
            patch("mait_code.tools.memory.cli.is_available", return_value=False),
            patch(
                "mait_code.tools.memory.cli._embedding_provider_name",
                return_value="bedrock",
            ),
            pytest.raises(ReindexError, match="boto3"),
        ):
            run_reindex()

    def test_cmd_reindex_prints_done_count(self, populated_mem_db, capsys):
        from mait_code.tools.memory.cli import cmd_reindex

        with (
            patch("mait_code.tools.memory.cli.is_available", return_value=True),
            patch(
                "mait_code.tools.memory.cli.check_dimension_match",
                return_value=(True, 768, 768),
            ),
            patch(
                "mait_code.tools.memory.cli.embed_texts",
                side_effect=lambda texts, prefix: [[0.1] * 768 for _ in texts],
            ),
        ):
            cmd_reindex(None)
        out = capsys.readouterr().out
        assert "Done." in out
        assert "embeddings stored" in out


# --- Restore: warning/error branches ---


class TestCmdRestoreBranches:
    def test_no_log_files(self, mem_db, tmp_path):
        from mait_code.tools.memory.cli import cmd_restore

        # The observations dir exists but holds no .jsonl files.
        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            with pytest.raises(SystemExit):
                cmd_restore(_make_args(dry_run=False))

    def test_invalid_json_line_counts_error(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        good = {
            "extraction": {
                "facts": [{"content": "Valid fact", "importance": 5}],
                "entities": [],
                "relationships": [],
            }
        }
        # One garbage line, one blank line, one good record.
        (obs_dir / "log.jsonl").write_text("{ not json\n\n" + json.dumps(good) + "\n")
        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            cmd_restore(_make_args(dry_run=True))
        out = capsys.readouterr().out
        assert "invalid JSON" in out
        assert "Errors: 1" in out

    def test_relationship_replay_creates_endpoints(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        # Relationship references entities that are not declared in the
        # ``entities`` list, so both endpoints are auto-upserted as 'unknown'.
        record = {
            "extraction": {
                "facts": [],
                "entities": [],
                "relationships": [
                    {
                        "source": "ServiceA",
                        "target": "ServiceB",
                        "relationship_type": "depends_on",
                        "context": "calls API",
                    }
                ],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        assert "Relationships upserted: 1" in out
        # Both endpoints were created on the fly.
        names = {
            r[0] for r in mem_db.execute("SELECT name FROM memory_entities").fetchall()
        }
        assert {"ServiceA", "ServiceB"} <= names

    def test_restore_skips_blank_content_and_names(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        # Blank content/name/endpoints are skipped without counting.
        record = {
            "extraction": {
                "facts": [{"content": "   ", "importance": 5}],
                "entities": [{"name": "  ", "entity_type": "tool"}],
                "relationships": [
                    {"source": "", "target": "X", "relationship_type": "uses"}
                ],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        assert "Memories stored: 0" in out
        assert "Entities upserted: 0" in out
        assert "Relationships upserted: 0" in out

    def test_store_failure_counts_error(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "extraction": {
                "facts": [{"content": "Boom", "importance": 5}],
                "entities": [],
                "relationships": [],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch(
                "mait_code.tools.memory.writer.store_memory",
                side_effect=RuntimeError("disk full"),
            ),
        ):
            cmd_restore(_make_args(dry_run=False))
        captured = capsys.readouterr()
        # The per-item warning goes to stderr; the tally lands in the summary.
        assert "failed to store" in captured.err
        assert "Errors: 1" in captured.out

    def test_entity_upsert_failure_counts_error(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "extraction": {
                "facts": [],
                "entities": [{"name": "Wobble", "entity_type": "tool"}],
                "relationships": [],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch(
                "mait_code.tools.memory.entities.upsert_entity",
                side_effect=RuntimeError("constraint"),
            ),
        ):
            cmd_restore(_make_args(dry_run=False))
        captured = capsys.readouterr()
        assert "failed to upsert entity" in captured.err
        assert "Errors: 1" in captured.out

    def test_relationship_endpoint_upsert_failure_counts_error(
        self, mem_db, tmp_path, capsys
    ):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        # Endpoints are not declared, so they're auto-upserted — and that
        # upsert raises, exercising the relationship-endpoint error branch.
        record = {
            "extraction": {
                "facts": [],
                "entities": [],
                "relationships": [
                    {"source": "A", "target": "B", "relationship_type": "uses"}
                ],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch(
                "mait_code.tools.memory.entities.upsert_entity",
                side_effect=RuntimeError("boom"),
            ),
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        # Source endpoint creation fails -> the relationship is skipped and
        # the error tallied; no relationship is recorded.
        assert "Relationships upserted: 0" in out
        assert "Errors: 1" in out

    def test_relationship_target_upsert_failure_counts_error(
        self, mem_db, tmp_path, capsys
    ):
        import json

        from mait_code.tools.memory import entities as entities_mod
        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        # Source is declared (so its id is cached); only the auto-created target
        # endpoint upsert raises, hitting the target-failure branch.
        record = {
            "extraction": {
                "facts": [],
                "entities": [{"name": "Source", "entity_type": "tool"}],
                "relationships": [
                    {
                        "source": "Source",
                        "target": "Target",
                        "relationship_type": "uses",
                    }
                ],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")

        real_upsert = entities_mod.upsert_entity

        def selective_upsert(conn, name, entity_type):
            if name == "Target":
                raise RuntimeError("target boom")
            return real_upsert(conn, name, entity_type)

        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch(
                "mait_code.tools.memory.entities.upsert_entity",
                side_effect=selective_upsert,
            ),
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        assert "Relationships upserted: 0" in out
        assert "Errors: 1" in out

    def test_relationship_upsert_failure_counts_error(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        # Both endpoints upsert fine; the relationship write itself raises.
        record = {
            "extraction": {
                "facts": [],
                "entities": [
                    {"name": "A", "entity_type": "tool"},
                    {"name": "B", "entity_type": "tool"},
                ],
                "relationships": [
                    {"source": "A", "target": "B", "relationship_type": "uses"}
                ],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch(
                "mait_code.tools.memory.entities.upsert_relationship",
                side_effect=RuntimeError("rel boom"),
            ),
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        assert "Relationships upserted: 0" in out
        assert "Errors: 1" in out

    def test_dry_run_counts_relationships(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "extraction": {
                "facts": [],
                "entities": [],
                "relationships": [
                    {"source": "A", "target": "B", "relationship_type": "uses"}
                ],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with patch(
            "mait_code.tools.memory.db.get_data_dir",
            return_value=tmp_path / "data",
        ):
            cmd_restore(_make_args(dry_run=True))
        out = capsys.readouterr().out
        # In dry-run the relationship is counted without touching the DB.
        assert "[dry-run]" in out
        assert "Relationships upserted: 1" in out

    def test_restore_reindex_runs_but_embeds_nothing(self, mem_db, tmp_path, capsys):
        """Reindex is attempted but writes zero vectors -> no 'Done' line."""
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "extraction": {
                "facts": [{"content": "Stored but vectorless", "importance": 5}],
                "entities": [],
                "relationships": [],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch("mait_code.tools.memory.cli.is_available", return_value=True),
            # The reindex helper reports nothing embedded, so the success
            # line is suppressed.
            patch("mait_code.tools.memory.cli._reindex_embeddings", return_value=0),
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        assert "Reindexing embeddings" in out
        assert "embeddings stored" not in out

    def test_restore_reindexes_after_write(self, mem_db, tmp_path, capsys):
        import json

        from mait_code.tools.memory.cli import cmd_restore

        obs_dir = tmp_path / "data" / "memory" / "observations"
        obs_dir.mkdir(parents=True)
        record = {
            "extraction": {
                "facts": [{"content": "Reindex me", "importance": 5}],
                "entities": [],
                "relationships": [],
            }
        }
        (obs_dir / "log.jsonl").write_text(json.dumps(record) + "\n")
        with (
            patch(
                "mait_code.tools.memory.db.get_data_dir",
                return_value=tmp_path / "data",
            ),
            patch("mait_code.tools.memory.cli.is_available", return_value=True),
            patch(
                "mait_code.tools.memory.cli.embed_texts",
                side_effect=lambda texts, prefix: [[0.1] * 768 for _ in texts],
            ),
        ):
            cmd_restore(_make_args(dry_run=False))
        out = capsys.readouterr().out
        assert "Reindexing embeddings" in out
        assert "embeddings stored" in out


# --- Reflect drain edge cases ---


class TestCmdReflectDrain:
    def test_drain_complete_with_no_insights(self, capsys):
        """Draining past the first batch with empty insights prints a notice."""
        from mait_code.tools.memory.cli import cmd_reflect

        args = _make_args(
            days=7, min_new=0, batch_size=3, drain=True, project=None, branch=None
        )
        calls = {"n": 0}

        def fake_reflect(conn, **kwargs):
            calls["n"] += 1
            # First batch is full (keep draining), second is short (stop) —
            # neither yields insights, so the "Drain complete" branch fires.
            processed = 3 if calls["n"] == 1 else 1
            return {
                "skipped": False,
                "insights": [],
                "stored": 0,
                "memory_diff": None,
                "batch_info": {"processed": processed},
            }

        with (
            patch("mait_code.tools.memory.cli.connection"),
            patch("mait_code.tools.memory.reflect.reflect", side_effect=fake_reflect),
        ):
            cmd_reflect(args)
        out = capsys.readouterr().out
        assert calls["n"] == 2
        assert "Drain complete" in out

    def test_drain_stops_when_a_later_batch_is_skipped(self, capsys):
        """If a later drain pass reports skipped, the loop breaks quietly."""
        from mait_code.tools.memory.cli import cmd_reflect

        args = _make_args(
            days=7, min_new=0, batch_size=3, drain=True, project=None, branch=None
        )
        calls = {"n": 0}

        def fake_reflect(conn, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                # Full batch with an insight -> keep draining.
                return {
                    "skipped": False,
                    "insights": ["first"],
                    "stored": 1,
                    "memory_diff": None,
                    "batch_info": {"processed": 3},
                }
            # Second pass is skipped — break without the "skipped" notice
            # (that notice only prints on the very first iteration).
            return {
                "skipped": True,
                "reason": "nothing new",
                "insights": [],
                "stored": 0,
                "memory_diff": None,
                "batch_info": None,
            }

        with (
            patch("mait_code.tools.memory.cli.connection"),
            patch("mait_code.tools.memory.reflect.reflect", side_effect=fake_reflect),
        ):
            cmd_reflect(args)
        out = capsys.readouterr().out
        assert calls["n"] == 2
        # The first insight still surfaces; the skip notice does not.
        assert "first" in out
        assert "Reflection skipped" not in out

    def test_drain_hits_iteration_cap(self, capsys):
        """A pathological always-full drain stops at the iteration ceiling."""
        from mait_code.tools.memory.cli import cmd_reflect

        args = _make_args(
            days=7, min_new=0, batch_size=3, drain=True, project=None, branch=None
        )

        def fake_reflect(conn, **kwargs):
            # Every batch is full and yields no insight, so only the 20-iteration
            # cap can break the loop.
            return {
                "skipped": False,
                "insights": [],
                "stored": 0,
                "memory_diff": None,
                "batch_info": {"processed": 3},
            }

        with (
            patch("mait_code.tools.memory.cli.connection"),
            patch("mait_code.tools.memory.reflect.reflect", side_effect=fake_reflect),
        ):
            cmd_reflect(args)
        out = capsys.readouterr().out
        assert "maximum drain iterations" in out


# --- main() dispatch ---


class TestMain:
    """main() builds the parser and dispatches to the chosen subcommand."""

    def test_requires_subcommand(self, monkeypatch):
        from mait_code.tools.memory.cli import main

        # The subparser is required=True — a bare call is a usage error.
        monkeypatch.setattr("sys.argv", ["mc-tool-memory"])
        with pytest.raises(SystemExit):
            main()

    def test_dispatches_list(self, mem_db, capsys, monkeypatch):
        from mait_code.tools.memory.cli import main

        monkeypatch.setattr("sys.argv", ["mc-tool-memory", "list"])
        main()
        assert "No memories" in capsys.readouterr().out

    def test_dispatches_stats(self, mem_db, capsys, monkeypatch):
        from mait_code.tools.memory.cli import main

        monkeypatch.setattr("sys.argv", ["mc-tool-memory", "stats"])
        main()
        assert "No memories" in capsys.readouterr().out

    def test_dispatches_store(self, mem_db, capsys, monkeypatch):
        from mait_code.tools.memory.cli import main

        monkeypatch.setattr(
            "sys.argv",
            ["mc-tool-memory", "store", "a", "stored", "fact", "--scope", "global"],
        )
        main()
        out = capsys.readouterr().out
        assert "stored" in out.lower()
        # The dispatched store actually wrote a row.
        assert mem_db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0] == 1

    def test_dispatches_search(self, populated_mem_db, capsys, monkeypatch):
        from mait_code.tools.memory.cli import main

        monkeypatch.setattr(
            "sys.argv",
            ["mc-tool-memory", "search", "dark", "mode", "--scope", "all"],
        )
        main()
        assert "dark mode" in capsys.readouterr().out
