"""Tests for memory writer with deduplication."""

import sqlite3
from unittest.mock import patch

import numpy as np

from mait_code.tools.memory.writer import (
    CONFLICT_SIMILARITY_THRESHOLD,
    MEMORY_CLASS_MAP,
    STRING_SIMILARITY_THRESHOLD,
    VALID_ENTRY_TYPES,
    VECTOR_SIMILARITY_THRESHOLD,
    find_duplicate,
    store_memory,
    supersede_memory,
)


class TestStoreMemory:
    def test_store_new_entry(self, memory_db: sqlite3.Connection):
        """Basic insert should succeed."""
        result = store_memory(memory_db, "User prefers dark mode", "preference", 8)

        assert result["action"] == "created"
        assert result["id"] is not None
        assert result["content"] == "User prefers dark mode"

    def test_store_canonicalises_project(
        self, memory_db: sqlite3.Connection, tmp_path, monkeypatch
    ):
        """An aliased project slug is rewritten to its canonical form on write."""
        import mait_code.context as context_mod

        monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
        context_mod._alias_cache.clear()
        (tmp_path / "project-aliases.json").write_text('{"old-proj": "new-proj"}')

        result = store_memory(
            memory_db, "scoped content", "fact", scope="project", project="old-proj"
        )
        assert result["project"] == "new-proj"

        row = memory_db.execute(
            "SELECT project FROM memory_entries WHERE id = ?", (result["id"],)
        ).fetchone()
        assert row[0] == "new-proj"
        context_mod._alias_cache.clear()

    def test_store_sets_memory_class(self, memory_db: sqlite3.Connection):
        """Memory class should be set from MEMORY_CLASS_MAP."""
        for entry_type, expected_class in MEMORY_CLASS_MAP.items():
            store_memory(memory_db, f"test {entry_type}", entry_type, 5)
            row = memory_db.execute(
                "SELECT memory_class FROM memory_entries WHERE content = ?",
                (f"test {entry_type}",),
            ).fetchone()
            assert row[0] == expected_class, (
                f"{entry_type} should map to {expected_class}"
            )

    def test_dedup_identical_content(self, memory_db: sqlite3.Connection):
        """Exact duplicate content should be deduplicated."""
        content = "User prefers dark mode in all editors"
        r1 = store_memory(memory_db, content, "preference", 5)
        r2 = store_memory(memory_db, content, "preference", 5)

        assert r1["action"] == "created"
        assert r2["action"] == "deduplicated"
        assert r2["id"] == r1["id"]

        count = memory_db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        assert count == 1

    def test_dedup_near_identical(self, memory_db: sqlite3.Connection):
        """Content with >= 85% string similarity should be deduplicated."""
        store_memory(
            memory_db, "User prefers dark mode in all text editors", "preference", 5
        )
        result = store_memory(
            memory_db, "User prefers dark mode in all code editors", "preference", 5
        )

        assert result["action"] == "deduplicated"

    def test_dedup_paraphrase_via_vector(self, memory_db: sqlite3.Connection):
        """Semantic duplicates below string threshold should be caught by vector similarity."""
        original = "Tool invocations in skill instructions execute within allowed-tools permission scope"
        store_memory(memory_db, original, "fact", 8)

        # Paraphrase with extra words — string similarity ~0.87, under 0.90
        paraphrase = "Tool invocations in skill instructions execute within the allowed-tools permission scope, unlike preprocessing"

        # Mock vector search to return high similarity
        with patch(
            "mait_code.tools.memory.writer._vector_candidates",
            return_value=[(1, original, 0.96)],
        ):
            result = store_memory(memory_db, paraphrase, "fact", 8)

        assert result["action"] == "deduplicated"

    def test_dedup_vector_below_threshold(self, memory_db: sqlite3.Connection):
        """Content with vector similarity below threshold should not be deduplicated."""
        store_memory(memory_db, "Python is a programming language", "fact", 5)

        with patch(
            "mait_code.tools.memory.writer._vector_candidates",
            return_value=[(1, "Python is a programming language", 0.80)],
        ):
            result = store_memory(
                memory_db, "JavaScript is a scripting language", "fact", 5
            )

        assert result["action"] == "created"

    def test_dedup_updates_importance(self, memory_db: sqlite3.Connection):
        """Dedup should keep the maximum importance."""
        content = "Important fact about the system"
        store_memory(memory_db, content, "fact", 3)
        store_memory(memory_db, content, "fact", 8)

        row = memory_db.execute(
            "SELECT importance FROM memory_entries WHERE content = ?", (content,)
        ).fetchone()
        assert row[0] == 8

    def test_dedup_does_not_lower_importance(self, memory_db: sqlite3.Connection):
        """Dedup with lower importance should not reduce existing importance."""
        content = "Important fact about deployment"
        store_memory(memory_db, content, "fact", 9)
        store_memory(memory_db, content, "fact", 3)

        row = memory_db.execute(
            "SELECT importance FROM memory_entries WHERE content = ?", (content,)
        ).fetchone()
        assert row[0] == 9

    def test_dedup_updates_timestamp(self, memory_db: sqlite3.Connection):
        """Dedup should refresh the created_at timestamp."""
        content = "Some recurring fact"
        store_memory(memory_db, content, "fact", 5)

        # Set timestamp to yesterday explicitly
        memory_db.execute(
            "UPDATE memory_entries SET created_at = datetime('now', '-1 day') WHERE content = ?",
            (content,),
        )
        memory_db.commit()

        old_ts = memory_db.execute(
            "SELECT created_at FROM memory_entries WHERE content = ?", (content,)
        ).fetchone()[0]

        store_memory(memory_db, content, "fact", 5)

        new_ts = memory_db.execute(
            "SELECT created_at FROM memory_entries WHERE content = ?", (content,)
        ).fetchone()[0]

        assert new_ts > old_ts

    def test_store_clamps_importance(self, memory_db: sqlite3.Connection):
        """Values outside 1-10 should be clamped."""
        r1 = store_memory(memory_db, "low importance", "fact", -5)
        r2 = store_memory(memory_db, "high importance", "fact", 99)

        low = memory_db.execute(
            "SELECT importance FROM memory_entries WHERE id = ?", (r1["id"],)
        ).fetchone()[0]
        high = memory_db.execute(
            "SELECT importance FROM memory_entries WHERE id = ?", (r2["id"],)
        ).fetchone()[0]

        assert low == 1
        assert high == 10

    def test_store_invalid_type_defaults_to_fact(self, memory_db: sqlite3.Connection):
        """Unknown entry_type should default to 'fact'."""
        result = store_memory(memory_db, "some content", "unknown_type", 5)

        row = memory_db.execute(
            "SELECT entry_type FROM memory_entries WHERE id = ?", (result["id"],)
        ).fetchone()
        assert row[0] == "fact"

    def test_different_types_not_deduplicated(self, memory_db: sqlite3.Connection):
        """Same content with different entry_type should not deduplicate."""
        content = "Database migration completed successfully"
        r1 = store_memory(memory_db, content, "event", 5)
        r2 = store_memory(memory_db, content, "fact", 5)

        assert r1["action"] == "created"
        assert r2["action"] == "created"
        assert r1["id"] != r2["id"]

    def test_store_reports_no_conflicts_for_unrelated(
        self, memory_db: sqlite3.Connection
    ):
        """A brand-new entry with no near-neighbours reports no conflicts."""
        first = store_memory(
            memory_db, "User prefers tabs over spaces", "preference", 5
        )
        assert first["potential_conflicts"] == []


class TestConflictBand:
    """The 0.6-0.9 contradiction band: store the new fact, surface the conflict."""

    def test_midband_similarity_surfaces_conflict(self, memory_db: sqlite3.Connection):
        """A candidate in [conflict, vector) is stored AND flagged, not merged."""
        original = store_memory(memory_db, "The deploy target is staging", "fact", 5)

        sim = (CONFLICT_SIMILARITY_THRESHOLD + VECTOR_SIMILARITY_THRESHOLD) / 2
        with patch(
            "mait_code.tools.memory.writer._vector_candidates",
            return_value=[(original["id"], "The deploy target is staging", sim)],
        ):
            result = store_memory(
                memory_db, "The deploy target is production", "fact", 5
            )

        assert result["action"] == "created"
        assert result["id"] != original["id"]
        conflicts = result["potential_conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["id"] == original["id"]
        assert conflicts[0]["similarity"] == round(sim, 4)

    def test_below_conflict_threshold_no_flag(self, memory_db: sqlite3.Connection):
        """Similarity below the conflict floor is just an unrelated new entry."""
        original = store_memory(memory_db, "Uses Redis for caching", "fact", 5)

        low = CONFLICT_SIMILARITY_THRESHOLD - 0.1
        with patch(
            "mait_code.tools.memory.writer._vector_candidates",
            return_value=[(original["id"], "Uses Redis for caching", low)],
        ):
            result = store_memory(memory_db, "Runs on Kubernetes", "fact", 5)

        assert result["action"] == "created"
        assert result["potential_conflicts"] == []

    def test_above_vector_threshold_merges_not_conflicts(
        self, memory_db: sqlite3.Connection
    ):
        """At/above the dedup threshold it's a duplicate — merge, no conflict list."""
        original = store_memory(memory_db, "The cache TTL is 60 seconds", "fact", 5)

        with patch(
            "mait_code.tools.memory.writer._vector_candidates",
            return_value=[(original["id"], "The cache TTL is 60 seconds", 0.97)],
        ):
            result = store_memory(memory_db, "Cache TTL: sixty seconds", "fact", 5)

        assert result["action"] == "deduplicated"
        assert result["potential_conflicts"] == []


class TestSupersede:
    def test_supersede_marks_old_and_creates_new(self, memory_db: sqlite3.Connection):
        """Superseding links the old entry to the new one with a timestamp."""
        old = store_memory(memory_db, "Backend is written in Go", "fact", 6)
        result = supersede_memory(memory_db, old["id"], "Backend is written in Rust")

        assert result["action"] == "superseded"
        assert result["old_id"] == old["id"]
        assert result["id"] != old["id"]

        old_row = memory_db.execute(
            "SELECT superseded_by, superseded_at FROM memory_entries WHERE id = ?",
            (old["id"],),
        ).fetchone()
        assert old_row[0] == result["id"]
        assert old_row[1] is not None

        new_row = memory_db.execute(
            "SELECT content, superseded_by FROM memory_entries WHERE id = ?",
            (result["id"],),
        ).fetchone()
        assert new_row[0] == "Backend is written in Rust"
        assert new_row[1] is None

    def test_supersede_inherits_type_and_scope(self, memory_db: sqlite3.Connection):
        """The new entry carries over the old one's type and scope."""
        old = store_memory(
            memory_db,
            "Cluster lives in eu-west-1",
            "fact",
            7,
            scope="project",
            project="infra",
        )
        result = supersede_memory(memory_db, old["id"], "Cluster lives in eu-west-2")

        row = memory_db.execute(
            "SELECT entry_type, scope, project, importance FROM memory_entries "
            "WHERE id = ?",
            (result["id"],),
        ).fetchone()
        assert row[0] == "fact"
        assert row[1] == "project"
        assert row[2] == "infra"
        assert row[3] == 7  # importance inherited

    def test_supersede_importance_override(self, memory_db: sqlite3.Connection):
        """An explicit importance overrides the inherited value (clamped)."""
        old = store_memory(memory_db, "Old budget is 1000", "fact", 4)
        result = supersede_memory(
            memory_db, old["id"], "New budget is 2000", importance=99
        )
        row = memory_db.execute(
            "SELECT importance FROM memory_entries WHERE id = ?", (result["id"],)
        ).fetchone()
        assert row[0] == 10

    def test_supersede_missing_id(self, memory_db: sqlite3.Connection):
        """Superseding a nonexistent entry returns not_found, writes nothing."""
        result = supersede_memory(memory_db, 9999, "whatever")
        assert result["action"] == "not_found"
        count = memory_db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        assert count == 0

    def test_supersede_chain(self, memory_db: sqlite3.Connection):
        """Superseding twice leaves only the latest entry current."""
        a = store_memory(memory_db, "Version is 1.0", "fact", 5)
        b = supersede_memory(memory_db, a["id"], "Version is 2.0")
        c = supersede_memory(memory_db, b["id"], "Version is 3.0")

        current = memory_db.execute(
            "SELECT id, content FROM memory_entries WHERE superseded_by IS NULL"
        ).fetchall()
        assert len(current) == 1
        assert current[0][0] == c["id"]
        assert current[0][1] == "Version is 3.0"

    def test_superseded_excluded_from_dedup_candidates(
        self, memory_db: sqlite3.Connection
    ):
        """A superseded entry is not offered as a duplicate target."""
        content = "The primary region is us-east-1"
        old = store_memory(memory_db, content, "fact", 5)
        # Replace with unrelated content so the only entry resembling `content`
        # is the now-superseded row.
        supersede_memory(memory_db, old["id"], "Cody is a brindle whippet")

        # Re-stating the OLD (now superseded) content must not dedup into the
        # hidden superseded row — it's excluded as a candidate.
        assert find_duplicate(memory_db, content, "fact") is None


class TestScopedDedup:
    def test_same_project_different_branch_deduplicates(
        self, memory_db: sqlite3.Connection
    ):
        """Same content in same project but different branches should deduplicate."""
        content = "The API uses JSON responses"
        r1 = store_memory(
            memory_db,
            content,
            "fact",
            5,
            scope="branch",
            project="my-project",
            branch="feature/a",
        )
        r2 = store_memory(
            memory_db,
            content,
            "fact",
            5,
            scope="branch",
            project="my-project",
            branch="feature/b",
        )
        assert r1["action"] == "created"
        assert r2["action"] == "deduplicated"

    def test_different_projects_not_deduplicated(self, memory_db: sqlite3.Connection):
        """Same content in different projects should NOT deduplicate."""
        content = "Uses PostgreSQL for persistence"
        r1 = store_memory(
            memory_db,
            content,
            "fact",
            5,
            scope="project",
            project="project-a",
        )
        r2 = store_memory(
            memory_db,
            content,
            "fact",
            5,
            scope="project",
            project="project-b",
        )
        assert r1["action"] == "created"
        assert r2["action"] == "created"
        assert r1["id"] != r2["id"]

    def test_global_vs_project_not_deduplicated(self, memory_db: sqlite3.Connection):
        """Global and project-scoped same content should NOT deduplicate."""
        content = "Redis is used for caching"
        r1 = store_memory(memory_db, content, "fact", 5)  # global (default)
        r2 = store_memory(
            memory_db,
            content,
            "fact",
            5,
            scope="project",
            project="my-project",
        )
        assert r1["action"] == "created"
        assert r2["action"] == "created"
        assert r1["id"] != r2["id"]

    def test_store_returns_scope_fields(self, memory_db: sqlite3.Connection):
        """store_memory should return scope, project, branch in result dict."""
        result = store_memory(
            memory_db,
            "scoped content",
            "fact",
            5,
            scope="branch",
            project="my-project",
            branch="feature/x",
        )
        assert result["scope"] == "branch"
        assert result["project"] == "my-project"
        assert result["branch"] == "feature/x"

    def test_store_persists_scope_fields(self, memory_db: sqlite3.Connection):
        """Scope fields should be stored in the database."""
        result = store_memory(
            memory_db,
            "persisted scope",
            "fact",
            7,
            scope="project",
            project="test-proj",
        )
        row = memory_db.execute(
            "SELECT scope, project, branch FROM memory_entries WHERE id = ?",
            (result["id"],),
        ).fetchone()
        assert row[0] == "project"
        assert row[1] == "test-proj"
        assert row[2] is None

    def test_invalid_scope_defaults_to_global(self, memory_db: sqlite3.Connection):
        """Invalid scope value should default to 'global'."""
        result = store_memory(
            memory_db,
            "bad scope",
            "fact",
            5,
            scope="invalid",
        )
        row = memory_db.execute(
            "SELECT scope FROM memory_entries WHERE id = ?",
            (result["id"],),
        ).fetchone()
        assert row[0] == "global"


class TestStoreMemoryEmbedding:
    def test_store_creates_embedding(self, memory_db: sqlite3.Connection):
        """Storing a memory should also insert an embedding."""
        mock_vec = np.zeros(768, dtype="float32")

        with patch(
            "mait_code.tools.memory.writer.embed_text",
            return_value=mock_vec.tolist(),
        ):
            result = store_memory(memory_db, "test with embedding", "fact", 5)

        count = memory_db.execute(
            "SELECT COUNT(*) FROM memory_vec WHERE rowid = ?", (result["id"],)
        ).fetchone()[0]
        assert count == 1

    def test_store_works_without_embeddings(self, memory_db: sqlite3.Connection):
        """Storage should succeed even when embeddings are unavailable."""
        with patch(
            "mait_code.tools.memory.writer.embed_text",
            return_value=None,
        ):
            result = store_memory(memory_db, "test without embedding", "fact", 5)

        assert result["action"] == "created"
        assert result["id"] is not None

        # No embedding should be stored
        count = memory_db.execute(
            "SELECT COUNT(*) FROM memory_vec WHERE rowid = ?", (result["id"],)
        ).fetchone()[0]
        assert count == 0

    def test_dedup_does_not_store_new_embedding(self, memory_db: sqlite3.Connection):
        """Deduplication should not insert a new embedding row."""
        mock_vec = np.zeros(768, dtype="float32")

        with patch(
            "mait_code.tools.memory.writer.embed_text",
            return_value=mock_vec.tolist(),
        ):
            store_memory(memory_db, "duplicate content test", "fact", 5)
            store_memory(memory_db, "duplicate content test", "fact", 5)

        # Only one embedding row should exist (from the first store)
        count = memory_db.execute("SELECT COUNT(*) FROM memory_vec").fetchone()[0]
        assert count == 1


class TestFindDuplicate:
    def test_no_duplicate_in_empty_db(self, memory_db: sqlite3.Connection):
        """Empty database should return None."""
        assert find_duplicate(memory_db, "any content", "fact") is None

    def test_finds_exact_match(self, memory_db: sqlite3.Connection):
        """Should find exact duplicate."""
        content = "User prefers vim keybindings"
        store_memory(memory_db, content, "preference", 5)

        dup_id = find_duplicate(memory_db, content, "preference")
        assert dup_id is not None

    def test_valid_entry_types(self):
        """All expected types should be present."""
        expected = {
            "fact",
            "preference",
            "decision",
            "event",
            "insight",
            "task",
            "relationship",
        }
        assert VALID_ENTRY_TYPES == expected

    def test_similarity_thresholds(self):
        """Thresholds should be set correctly."""
        assert STRING_SIMILARITY_THRESHOLD == 0.85
        assert VECTOR_SIMILARITY_THRESHOLD == 0.92

    def test_vector_candidates_graceful_without_embeddings(
        self, memory_db: sqlite3.Connection
    ):
        """Vector candidate retrieval should return empty when embeddings unavailable."""
        from mait_code.tools.memory.writer import _vector_candidates

        with patch(
            "mait_code.tools.memory.writer.embed_text",
            return_value=None,
        ):
            result = _vector_candidates(memory_db, "test content", "fact")

        assert result == []
