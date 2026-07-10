"""Tests for due-for-review computation (memory resurfacing)."""

import sqlite3
from datetime import UTC, datetime

from mait_code.tools.memory.review import due_for_review

# A fixed "now" so decay is deterministic regardless of wall-clock.
_NOW = datetime(2026, 7, 10, tzinfo=UTC)


def _insert(
    conn: sqlite3.Connection,
    content: str,
    *,
    importance: int,
    memory_class: str,
    reviewed_at: str,
    created_at: str | None = None,
) -> int:
    """Insert a memory with an explicit review anchor; return its id."""
    cur = conn.execute(
        """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at, reviewed_at)
           VALUES (?, 'fact', ?, ?, ?, ?)""",
        (content, importance, memory_class, created_at or reviewed_at, reviewed_at),
    )
    conn.commit()
    return cur.lastrowid


def test_empty_when_nothing_due(memory_db: sqlite3.Connection):
    # A semantic fact reviewed yesterday is nowhere near its 90-day half-life.
    _insert(
        memory_db,
        "fresh fact",
        importance=8,
        memory_class="semantic",
        reviewed_at="2026-07-09T00:00:00+00:00",
    )
    assert due_for_review(memory_db, now=_NOW) == []


def test_stale_high_importance_is_due(memory_db: sqlite3.Connection):
    # Semantic half-life is 90 days; ~200 days since review → recall well below 0.5.
    _insert(
        memory_db,
        "stale but important",
        importance=8,
        memory_class="semantic",
        reviewed_at="2025-12-22T00:00:00+00:00",
    )
    due = due_for_review(memory_db, now=_NOW)
    assert [d["content"] for d in due] == ["stale but important"]
    assert due[0]["recall"] < 0.5
    assert due[0]["reviewed_at"] == "2025-12-22T00:00:00+00:00"


def test_low_importance_does_not_nag(memory_db: sqlite3.Connection):
    # Equally stale, but below the default importance floor (5) → excluded.
    _insert(
        memory_db,
        "stale and trivial",
        importance=3,
        memory_class="semantic",
        reviewed_at="2025-01-01T00:00:00+00:00",
    )
    assert due_for_review(memory_db, now=_NOW) == []


def test_ranked_most_decayed_first(memory_db: sqlite3.Connection):
    _insert(
        memory_db,
        "moderately stale",
        importance=8,
        memory_class="semantic",
        reviewed_at="2026-02-01T00:00:00+00:00",
    )
    _insert(
        memory_db,
        "very stale",
        importance=8,
        memory_class="semantic",
        reviewed_at="2024-01-01T00:00:00+00:00",
    )
    due = due_for_review(memory_db, now=_NOW)
    assert [d["content"] for d in due] == ["very stale", "moderately stale"]
    assert due[0]["recall"] < due[1]["recall"]


def test_limit_caps_results(memory_db: sqlite3.Connection):
    for i in range(5):
        _insert(
            memory_db,
            f"stale {i}",
            importance=8,
            memory_class="semantic",
            reviewed_at="2024-01-01T00:00:00+00:00",
        )
    assert len(due_for_review(memory_db, now=_NOW, limit=2)) == 2


def test_null_reviewed_at_falls_back_to_created_at(memory_db: sqlite3.Connection):
    """A row inserted post-migration (reviewed_at NULL) anchors on created_at."""
    memory_db.execute(
        """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at)
           VALUES ('no review stamp', 'fact', 8, 'semantic', '2024-01-01T00:00:00+00:00')""",
    )
    memory_db.commit()
    due = due_for_review(memory_db, now=_NOW)
    assert [d["content"] for d in due] == ["no review stamp"]
    # COALESCE surfaces created_at as the anchor.
    assert due[0]["reviewed_at"] == "2024-01-01T00:00:00+00:00"


def test_reviewing_clears_due(memory_db: sqlite3.Connection):
    from mait_code.tools.memory.writer import mark_reviewed

    entry_id = _insert(
        memory_db,
        "was stale",
        importance=8,
        memory_class="semantic",
        reviewed_at="2024-01-01T00:00:00+00:00",
    )
    assert due_for_review(memory_db, now=_NOW)  # due before review
    mark_reviewed(memory_db, entry_id)  # stamps reviewed_at = now
    # After review the anchor is ~now, so recall ≈ 1.0 → not due.
    assert due_for_review(memory_db, now=datetime.now(UTC)) == []


def test_superseded_entries_excluded(memory_db: sqlite3.Connection):
    """Retired/superseded rows never surface for review."""
    entry_id = _insert(
        memory_db,
        "stale and retired",
        importance=8,
        memory_class="semantic",
        reviewed_at="2024-01-01T00:00:00+00:00",
    )
    memory_db.execute(
        "UPDATE memory_entries SET superseded_at = CURRENT_TIMESTAMP WHERE id = ?",
        (entry_id,),
    )
    memory_db.commit()
    assert due_for_review(memory_db, now=_NOW) == []
