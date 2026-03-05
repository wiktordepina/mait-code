"""
Keyword search using FTS5 with LIKE fallback.

Provides search, listing, and deletion operations on memory entries.
"""

import sqlite3


def search_entries(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    entry_type: str | None = None,
) -> list[dict]:
    """
    Search memory entries using FTS5 BM25 ranking.

    Falls back to LIKE if FTS5 is not available.

    Args:
        conn: Database connection.
        query: Search query string.
        limit: Maximum results.
        entry_type: Optional filter by entry_type.

    Returns:
        List of dicts with id, content, entry_type, importance, memory_class, created_at.
    """
    try:
        if entry_type:
            cursor = conn.execute(
                """SELECT m.id, m.content, m.entry_type, m.importance,
                          m.memory_class, m.created_at
                   FROM memory_entries_fts f
                   JOIN memory_entries m ON m.id = f.rowid
                   WHERE memory_entries_fts MATCH ? AND m.entry_type = ?
                   ORDER BY bm25(memory_entries_fts)
                   LIMIT ?""",
                (query, entry_type, limit),
            )
        else:
            cursor = conn.execute(
                """SELECT m.id, m.content, m.entry_type, m.importance,
                          m.memory_class, m.created_at
                   FROM memory_entries_fts f
                   JOIN memory_entries m ON m.id = f.rowid
                   WHERE memory_entries_fts MATCH ?
                   ORDER BY bm25(memory_entries_fts)
                   LIMIT ?""",
                (query, limit),
            )
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # Fallback to LIKE if FTS not available
        if entry_type:
            cursor = conn.execute(
                """SELECT id, content, entry_type, importance, memory_class, created_at
                   FROM memory_entries
                   WHERE content LIKE ? AND entry_type = ?
                   ORDER BY importance DESC, created_at DESC
                   LIMIT ?""",
                (f"%{query}%", entry_type, limit),
            )
        else:
            cursor = conn.execute(
                """SELECT id, content, entry_type, importance, memory_class, created_at
                   FROM memory_entries
                   WHERE content LIKE ?
                   ORDER BY importance DESC, created_at DESC
                   LIMIT ?""",
                (f"%{query}%", limit),
            )
        rows = cursor.fetchall()

    return [
        {
            "id": r[0],
            "content": r[1],
            "entry_type": r[2],
            "importance": r[3],
            "memory_class": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


def list_entries(
    conn: sqlite3.Connection,
    limit: int = 20,
    entry_type: str | None = None,
) -> list[dict]:
    """List recent memory entries, optionally filtered by type."""
    if entry_type:
        cursor = conn.execute(
            """SELECT id, content, entry_type, importance, memory_class, created_at
               FROM memory_entries
               WHERE entry_type = ?
               ORDER BY created_at DESC LIMIT ?""",
            (entry_type, limit),
        )
    else:
        cursor = conn.execute(
            """SELECT id, content, entry_type, importance, memory_class, created_at
               FROM memory_entries
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )

    return [
        {
            "id": r[0],
            "content": r[1],
            "entry_type": r[2],
            "importance": r[3],
            "memory_class": r[4],
            "created_at": r[5],
        }
        for r in cursor.fetchall()
    ]


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Delete a memory entry by ID. Returns True if deleted."""
    cursor = conn.execute("SELECT id FROM memory_entries WHERE id = ?", (entry_id,))
    if not cursor.fetchone():
        return False
    conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
    conn.commit()
    return True
