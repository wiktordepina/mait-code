"""Tests for the memory stats service (collect_stats + reflection freshness)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.reflect import count_unreflected, get_last_reflected_at
from mait_code.tools.memory.stats import collect_stats


@pytest.fixture
def conn(tmp_path: Path):
    connection = get_connection(tmp_path / "memory.db")
    yield connection
    connection.close()


def _seed_entry(conn, content: str, entry_type: str, *, project: str | None = None):
    cursor = conn.execute(
        """INSERT INTO memory_entries
           (content, entry_type, importance, memory_class, scope, project, created_at)
           VALUES (?, ?, 5, 'semantic', ?, ?, '2026-06-01 09:00:00')""",
        (content, entry_type, "project" if project else "global", project),
    )
    conn.commit()
    return cursor.lastrowid


def _set_watermark(conn, last_id: int, at: str = "2026-06-05 12:00:00") -> None:
    conn.execute(
        "INSERT INTO reflection_watermark (project, last_reflected_id, last_reflected_at) "
        "VALUES ('', ?, ?)",
        (last_id, at),
    )
    conn.commit()


# --- collect_stats ---


def test_collect_stats_counts(conn) -> None:
    _seed_entry(conn, "a", "fact")
    _seed_entry(conn, "b", "fact")
    _seed_entry(conn, "c", "decision", project="demo")

    stats = collect_stats(conn)
    assert stats.total == 3
    assert ("fact", 2) in stats.by_type
    assert ("decision", 1) in stats.by_type
    assert ("(global)", 2) in stats.by_project
    assert ("demo", 1) in stats.by_project


def test_collect_stats_counts_superseded_and_retired_separately(conn) -> None:
    """Superseded and retired rows are counted independently, not conflated."""
    from mait_code.tools.memory.writer import retire_memory, supersede_memory

    a = _seed_entry(conn, "old fact", "fact")
    _seed_entry(conn, "stale fact", "fact")
    supersede_memory(conn, a, "new fact")  # a → superseded, plus one live successor
    # Retire the most recent live 'stale fact' row.
    stale_id = conn.execute(
        "SELECT id FROM memory_entries WHERE content = 'stale fact'"
    ).fetchone()[0]
    retire_memory(conn, stale_id)

    stats = collect_stats(conn)
    assert stats.superseded == 1
    assert stats.retired == 1


def test_collect_stats_embedding_coverage(conn) -> None:
    _seed_entry(conn, "a", "fact")
    _seed_entry(conn, "b", "fact")

    stats = collect_stats(conn)
    # No embedding path was run, so nothing is in memory_vec.
    assert stats.embedded == 0
    assert stats.unembedded == 2
    assert stats.embedded_pct == 0
    assert stats.provider  # cheap config read, never empty
    assert stats.model


def test_collect_stats_empty_store(conn) -> None:
    stats = collect_stats(conn)
    assert stats.total == 0
    assert stats.unembedded == 0
    assert stats.embedded_pct == 0
    assert stats.unreflected == 0
    assert stats.last_reflected_at is None


def test_collect_stats_missing_vec_table_counts_zero(conn) -> None:
    """If the vec table is absent, embedded coverage degrades to zero.

    The COUNT against ``memory_vec`` raises ``sqlite3.Error`` on a store
    without the sqlite-vec table; stats should report zero rather than fail.
    """
    _seed_entry(conn, "a", "fact")
    conn.execute("DROP TABLE IF EXISTS memory_vec")
    conn.commit()

    stats = collect_stats(conn)
    assert stats.embedded == 0
    assert stats.total == 1
    assert stats.unembedded == 1


# --- reflection freshness ---


def test_count_unreflected_without_watermark_counts_all(conn) -> None:
    _seed_entry(conn, "a", "fact")
    _seed_entry(conn, "b", "decision")
    assert count_unreflected(conn) == 2


def test_count_unreflected_respects_watermark_and_skips_insights(conn) -> None:
    first = _seed_entry(conn, "a", "fact")
    assert first is not None
    _set_watermark(conn, first)
    _seed_entry(conn, "b", "fact")
    _seed_entry(conn, "c", "insight")  # insights never count as backlog

    assert count_unreflected(conn) == 1


def test_get_last_reflected_at(conn) -> None:
    assert get_last_reflected_at(conn) is None
    first = _seed_entry(conn, "a", "fact")
    assert first is not None
    _set_watermark(conn, first, at="2026-06-05 12:00:00")

    assert get_last_reflected_at(conn) == datetime(2026, 6, 5, 12, 0)


def test_stats_carries_reflection_freshness(conn) -> None:
    first = _seed_entry(conn, "a", "fact")
    assert first is not None
    _seed_entry(conn, "b", "fact")
    _set_watermark(conn, first)

    stats = collect_stats(conn)
    assert stats.unreflected == 1
    assert stats.last_reflected_at == datetime(2026, 6, 5, 12, 0)
