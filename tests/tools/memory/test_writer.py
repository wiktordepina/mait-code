"""Tests for memory writer with deduplication."""

import sqlite3
from unittest.mock import patch

import numpy as np

from mait_code.tools.memory.writer import (
    MEMORY_CLASS_MAP,
    VALID_ENTRY_TYPES,
    find_duplicate,
    store_memory,
)


class TestStoreMemory:
    def test_store_new_entry(self, memory_db: sqlite3.Connection):
        """Basic insert should succeed."""
        result = store_memory(memory_db, "User prefers dark mode", "preference", 8)

        assert result["action"] == "created"
        assert result["id"] is not None
        assert result["content"] == "User prefers dark mode"

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
        """Content with >= 90% similarity should be deduplicated."""
        store_memory(
            memory_db, "User prefers dark mode in all text editors", "preference", 5
        )
        result = store_memory(
            memory_db, "User prefers dark mode in all code editors", "preference", 5
        )

        assert result["action"] == "deduplicated"

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

    def test_dedup_does_not_embed(self, memory_db: sqlite3.Connection):
        """Deduplication should not attempt to store a new embedding."""
        mock_vec = np.zeros(768, dtype="float32")

        with patch(
            "mait_code.tools.memory.writer.embed_text",
            return_value=mock_vec.tolist(),
        ) as mock_embed:
            store_memory(memory_db, "duplicate content test", "fact", 5)
            store_memory(memory_db, "duplicate content test", "fact", 5)

        # embed_text should only be called once (for the first store)
        assert mock_embed.call_count == 1


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
        expected = {"fact", "preference", "event", "insight", "task", "relationship"}
        assert VALID_ENTRY_TYPES == expected
