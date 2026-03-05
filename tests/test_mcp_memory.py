"""Tests for MCP memory server tools.

Tests call the tool functions directly (not via MCP protocol)
using a temp database instead of the default data dir.
"""

from unittest.mock import patch

import pytest

from mait_code.memory.db import get_connection
from mait_code.memory.writer import store_memory as db_store


@pytest.fixture
def mcp_db(tmp_path):
    """Patch get_connection to use a temp database for MCP tools."""
    db_path = tmp_path / "mcp_test.db"
    conn = get_connection(db_path)

    def patched_get_connection(**_kwargs):
        return get_connection(db_path)

    with patch(
        "mait_code.mcp.memory_server.get_connection", side_effect=patched_get_connection
    ):
        yield conn

    conn.close()


@pytest.fixture
def populated_mcp_db(mcp_db):
    """MCP test DB with sample data."""
    entries = [
        ("User prefers dark mode", "preference", 8),
        ("Kubernetes uses namespace default", "fact", 6),
        ("Always run linter before commit", "insight", 7),
    ]
    for content, entry_type, importance in entries:
        db_store(mcp_db, content, entry_type, importance)
    return mcp_db


class TestSearchMemory:
    def test_returns_results(self, populated_mcp_db):
        from mait_code.mcp.memory_server import search_memory

        result = search_memory("dark mode")
        assert "dark mode" in result
        assert "Found" in result

    def test_no_results(self, populated_mcp_db):
        from mait_code.mcp.memory_server import search_memory

        result = search_memory("nonexistent_xyz_query")
        assert "No memories found" in result

    def test_with_type_filter(self, populated_mcp_db):
        from mait_code.mcp.memory_server import search_memory

        result = search_memory("dark mode", entry_type="preference")
        assert "dark mode" in result

    def test_with_limit(self, populated_mcp_db):
        from mait_code.mcp.memory_server import search_memory

        result = search_memory("User OR Kubernetes OR linter", limit=1)
        # Should still return results (limit applied after scoring)
        assert "Found 1" in result


class TestStoreMemory:
    def test_store_new(self, mcp_db):
        from mait_code.mcp.memory_server import store_memory

        result = store_memory("New fact about testing", "fact", 5)
        assert "stored" in result.lower()

    def test_store_dedup(self, mcp_db):
        from mait_code.mcp.memory_server import store_memory

        store_memory("Repeated fact about testing", "fact", 5)
        result = store_memory("Repeated fact about testing", "fact", 5)
        assert "deduplicated" in result.lower()

    def test_empty_content_error(self, mcp_db):
        from mait_code.mcp.memory_server import store_memory

        result = store_memory("", "fact", 5)
        assert "Error" in result

    def test_whitespace_only_error(self, mcp_db):
        from mait_code.mcp.memory_server import store_memory

        result = store_memory("   ", "fact", 5)
        assert "Error" in result

    def test_invalid_type_error(self, mcp_db):
        from mait_code.mcp.memory_server import store_memory

        result = store_memory("some content", "invalid_type", 5)
        assert "Error" in result
        assert "Invalid" in result


class TestListRecentMemories:
    def test_with_entries(self, populated_mcp_db):
        from mait_code.mcp.memory_server import list_recent_memories

        result = list_recent_memories()
        assert "Recent" in result
        assert "dark mode" in result

    def test_empty_db(self, mcp_db):
        from mait_code.mcp.memory_server import list_recent_memories

        result = list_recent_memories()
        assert "No memories" in result

    def test_with_type_filter(self, populated_mcp_db):
        from mait_code.mcp.memory_server import list_recent_memories

        result = list_recent_memories(entry_type="preference")
        assert "dark mode" in result


class TestDeleteMemory:
    def test_delete_existing(self, populated_mcp_db):
        from mait_code.mcp.memory_server import delete_memory

        entry_id = populated_mcp_db.execute(
            "SELECT id FROM memory_entries LIMIT 1"
        ).fetchone()[0]
        result = delete_memory(entry_id)
        assert "deleted" in result.lower()

    def test_delete_not_found(self, mcp_db):
        from mait_code.mcp.memory_server import delete_memory

        result = delete_memory(99999)
        assert "not found" in result.lower()


class TestMemoryStats:
    def test_with_entries(self, populated_mcp_db):
        from mait_code.mcp.memory_server import memory_stats

        result = memory_stats()
        assert "Memory Statistics" in result
        assert "3 total" in result
        assert "By type:" in result
        assert "By class:" in result

    def test_empty_db(self, mcp_db):
        from mait_code.mcp.memory_server import memory_stats

        result = memory_stats()
        assert "No memories" in result
