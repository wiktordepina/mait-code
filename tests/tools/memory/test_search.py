"""Tests for search module."""

import sqlite3
import struct
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from mait_code.tools.memory.search import (
    _parse_since,
    delete_entry,
    hybrid_search,
    list_entries,
    search_entries,
    vector_search_entries,
)


class TestSearchEntries:
    def test_fts_search_finds_content(self, populated_db: sqlite3.Connection):
        """FTS search should find matching entries."""
        results = search_entries(populated_db, "dark mode")
        assert len(results) >= 1
        assert any("dark mode" in r["content"] for r in results)

    def test_fts_search_returns_all_fields(self, populated_db: sqlite3.Connection):
        """Results should contain all expected fields."""
        results = search_entries(populated_db, "pytest")
        assert len(results) >= 1

        r = results[0]
        assert "id" in r
        assert "content" in r
        assert "entry_type" in r
        assert "importance" in r
        assert "memory_class" in r
        assert "created_at" in r

    def test_fts_search_no_results(self, populated_db: sqlite3.Connection):
        """Non-matching query should return empty list."""
        results = search_entries(populated_db, "nonexistent_xyz_query")
        assert results == []

    def test_fts_search_with_type_filter(self, populated_db: sqlite3.Connection):
        """Should filter by entry_type when specified."""
        results = search_entries(populated_db, "dark mode", entry_type="preference")
        assert len(results) >= 1
        assert all(r["entry_type"] == "preference" for r in results)

    def test_fts_search_type_filter_excludes(self, populated_db: sqlite3.Connection):
        """Filtering by wrong type should exclude results."""
        results = search_entries(populated_db, "dark mode", entry_type="event")
        assert len(results) == 0

    def test_fts_search_respects_limit(self, populated_db: sqlite3.Connection):
        """Should respect the limit parameter."""
        results = search_entries(populated_db, "User OR test OR deploy", limit=2)
        assert len(results) <= 2


class TestListEntries:
    def test_list_default(self, populated_db: sqlite3.Connection):
        """Should return recent entries."""
        results = list_entries(populated_db)
        assert len(results) == 7  # All entries from fixture

    def test_list_with_limit(self, populated_db: sqlite3.Connection):
        """Should respect limit."""
        results = list_entries(populated_db, limit=3)
        assert len(results) == 3

    def test_list_with_type(self, populated_db: sqlite3.Connection):
        """Should filter by type."""
        results = list_entries(populated_db, entry_type="event")
        assert len(results) == 2
        assert all(r["entry_type"] == "event" for r in results)

    def test_list_empty_db(self, memory_db: sqlite3.Connection):
        """Empty database should return empty list."""
        results = list_entries(memory_db)
        assert results == []

    def test_list_ordered_by_date(self, populated_db: sqlite3.Connection):
        """Results should be ordered by created_at descending."""
        results = list_entries(populated_db)
        dates = [r["created_at"] for r in results]
        assert dates == sorted(dates, reverse=True)


class TestParseSince:
    def test_hours(self):
        assert _parse_since("24h") == "-24 hours"

    def test_days(self):
        assert _parse_since("7d") == "-7 days"

    def test_weeks(self):
        assert _parse_since("1w") == "-7 days"
        assert _parse_since("2w") == "-14 days"

    def test_with_whitespace(self):
        assert _parse_since(" 24h ") == "-24 hours"

    def test_case_insensitive(self):
        assert _parse_since("24H") == "-24 hours"
        assert _parse_since("7D") == "-7 days"

    def test_invalid_returns_none(self):
        assert _parse_since("invalid") is None
        assert _parse_since("") is None
        assert _parse_since("24x") is None
        assert _parse_since("abc") is None


class TestListEntriesSince:
    def test_since_filters_recent(self, memory_db: sqlite3.Connection):
        """Entries within the time window should be returned."""
        now = datetime.now(timezone.utc)
        # Insert a recent entry
        memory_db.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("recent entry", "fact", 5, "semantic", now.isoformat()),
        )
        # Insert an old entry
        old = now - timedelta(days=30)
        memory_db.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("old entry", "fact", 5, "semantic", old.isoformat()),
        )
        memory_db.commit()

        results = list_entries(memory_db, since="7d")
        contents = [r["content"] for r in results]
        assert "recent entry" in contents
        assert "old entry" not in contents

    def test_since_with_type_filter(self, memory_db: sqlite3.Connection):
        """Since and type filters should combine."""
        now = datetime.now(timezone.utc)
        memory_db.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("recent fact", "fact", 5, "semantic", now.isoformat()),
        )
        memory_db.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("recent event", "event", 5, "episodic", now.isoformat()),
        )
        memory_db.commit()

        results = list_entries(memory_db, since="24h", entry_type="fact")
        assert len(results) == 1
        assert results[0]["content"] == "recent fact"

    def test_since_invalid_ignored(self, populated_db: sqlite3.Connection):
        """Invalid since value should be ignored (return all)."""
        results_all = list_entries(populated_db)
        results_bad = list_entries(populated_db, since="invalid")
        assert len(results_all) == len(results_bad)

    def test_since_none_returns_all(self, populated_db: sqlite3.Connection):
        """since=None should return all entries (same as no filter)."""
        results = list_entries(populated_db, since=None)
        assert len(results) == 7  # All entries from fixture


class TestVectorSearch:
    def _insert_with_embedding(self, conn, content, entry_type, vec):
        """Helper to insert an entry with a fake embedding."""
        cursor = conn.execute(
            """INSERT INTO memory_entries (content, entry_type, importance, memory_class)
               VALUES (?, ?, 5, 'semantic')""",
            (content, entry_type),
        )
        conn.commit()
        entry_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
            (entry_id, struct.pack(f"{len(vec)}f", *vec)),
        )
        conn.commit()
        return entry_id

    def test_vector_search_returns_empty_when_unavailable(
        self, memory_db: sqlite3.Connection
    ):
        """Should return empty list when embeddings are unavailable."""
        with patch(
            "mait_code.tools.memory.search.embed_text", return_value=None
        ):
            results = vector_search_entries(memory_db, "test query")
        assert results == []

    def test_vector_search_finds_entries(self, memory_db: sqlite3.Connection):
        """Should find entries by vector similarity."""
        # Insert entry with a known embedding
        vec = [1.0] + [0.0] * 767
        self._insert_with_embedding(memory_db, "vector test entry", "fact", vec)

        # Search with same vector
        query_vec = [1.0] + [0.0] * 767
        with patch(
            "mait_code.tools.memory.search.embed_text",
            return_value=query_vec,
        ):
            results = vector_search_entries(memory_db, "test")

        assert len(results) == 1
        assert results[0]["content"] == "vector test entry"
        assert "similarity" in results[0]
        assert results[0]["similarity"] > 0.9  # Same vector = high similarity

    def test_vector_search_with_type_filter(self, memory_db: sqlite3.Connection):
        """Should filter by entry_type."""
        vec = [1.0] + [0.0] * 767
        self._insert_with_embedding(memory_db, "a fact", "fact", vec)
        self._insert_with_embedding(memory_db, "an event", "event", vec)

        with patch(
            "mait_code.tools.memory.search.embed_text",
            return_value=vec,
        ):
            results = vector_search_entries(
                memory_db, "test", entry_type="fact"
            )

        assert len(results) == 1
        assert results[0]["entry_type"] == "fact"


class TestHybridSearch:
    def test_hybrid_falls_back_to_fts(self, populated_db: sqlite3.Connection):
        """With no embeddings, hybrid should still return FTS results."""
        with patch(
            "mait_code.tools.memory.search.embed_text", return_value=None
        ):
            results = hybrid_search(populated_db, "dark mode")

        assert len(results) >= 1
        assert any("dark mode" in r["content"] for r in results)
        # All results should have a relevance key
        assert all("relevance" in r for r in results)

    def test_hybrid_returns_empty_for_no_match(
        self, populated_db: sqlite3.Connection
    ):
        """Should return empty list when nothing matches."""
        with patch(
            "mait_code.tools.memory.search.embed_text", return_value=None
        ):
            results = hybrid_search(populated_db, "nonexistent_xyz")

        assert results == []

    def test_hybrid_merges_fts_and_vector(self, memory_db: sqlite3.Connection):
        """Results found by both FTS and vector should use vector similarity."""
        # Insert an entry with both FTS content and embedding
        memory_db.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class)
               VALUES (?, ?, 7, 'semantic')""",
            ("unique searchable content here", "fact"),
        )
        memory_db.commit()
        entry_id = memory_db.execute("SELECT last_insert_rowid()").fetchone()[0]

        vec = [1.0] + [0.0] * 767
        memory_db.execute(
            "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
            (entry_id, struct.pack("768f", *vec)),
        )
        memory_db.commit()

        with patch(
            "mait_code.tools.memory.search.embed_text",
            return_value=vec,
        ):
            results = hybrid_search(memory_db, "unique searchable")

        assert len(results) >= 1
        match = [r for r in results if r["id"] == entry_id]
        assert len(match) == 1
        # Should have high relevance (found by both, uses vector similarity)
        assert match[0]["relevance"] > 0.5


class TestDeleteEntry:
    def test_delete_existing(self, populated_db: sqlite3.Connection):
        """Should delete entry and return True."""
        entry_id = populated_db.execute(
            "SELECT id FROM memory_entries LIMIT 1"
        ).fetchone()[0]
        assert delete_entry(populated_db, entry_id) is True

        row = populated_db.execute(
            "SELECT id FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        assert row is None

    def test_delete_not_found(self, memory_db: sqlite3.Connection):
        """Should return False for non-existent ID."""
        assert delete_entry(memory_db, 99999) is False

    def test_delete_removes_from_fts(self, populated_db: sqlite3.Connection):
        """Deletion should also remove from FTS index via trigger."""
        # Find the dark mode entry
        row = populated_db.execute(
            "SELECT id FROM memory_entries WHERE content LIKE '%dark mode%'"
        ).fetchone()
        entry_id = row[0]

        delete_entry(populated_db, entry_id)

        fts_results = search_entries(populated_db, "dark mode")
        assert len(fts_results) == 0
