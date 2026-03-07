"""Tests for search module."""

import sqlite3

from mait_code.tools.memory.search import delete_entry, list_entries, search_entries


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
