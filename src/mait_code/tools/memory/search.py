"""
Search operations: keyword (FTS5), vector (sqlite-vec), and hybrid.

Provides search, listing, and deletion operations on memory entries.
"""

import logging
import sqlite3

from mait_code.tools.memory.embeddings import embed_text, serialize_f32

logger = logging.getLogger(__name__)


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


def vector_search_entries(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    entry_type: str | None = None,
) -> list[dict]:
    """
    Search memory entries using vector similarity via sqlite-vec.

    Embeds the query with the "search_query" prefix and finds nearest
    neighbours in the memory_vec table.

    Returns:
        List of dicts with id, content, entry_type, importance,
        memory_class, created_at, and similarity (0.0-1.0).
        Empty list if embeddings are unavailable.
    """
    vec = embed_text(query, prefix="search_query")
    if vec is None:
        return []

    try:
        if entry_type:
            cursor = conn.execute(
                """SELECT m.id, m.content, m.entry_type, m.importance,
                          m.memory_class, m.created_at, v.distance
                   FROM memory_vec v
                   JOIN memory_entries m ON m.id = v.rowid
                   WHERE v.embedding MATCH ? AND k = ?
                     AND m.entry_type = ?""",
                (serialize_f32(vec), limit, entry_type),
            )
        else:
            cursor = conn.execute(
                """SELECT m.id, m.content, m.entry_type, m.importance,
                          m.memory_class, m.created_at, v.distance
                   FROM memory_vec v
                   JOIN memory_entries m ON m.id = v.rowid
                   WHERE v.embedding MATCH ? AND k = ?""",
                (serialize_f32(vec), limit),
            )
        rows = cursor.fetchall()
    except Exception as e:
        logger.debug("Vector search failed: %s", e)
        return []

    return [
        {
            "id": r[0],
            "content": r[1],
            "entry_type": r[2],
            "importance": r[3],
            "memory_class": r[4],
            "created_at": r[5],
            "similarity": max(0.0, 1.0 - r[6]),
        }
        for r in rows
    ]


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    entry_type: str | None = None,
) -> list[dict]:
    """
    Combined FTS5 + vector search with merged results.

    Runs both search methods, merges by entry ID, and assigns a
    relevance score suitable for composite_score():
    - Entries found by both: use vector similarity as relevance
    - FTS-only entries: default relevance 0.3
    - Vector-only entries: default relevance 0.3

    Falls back to FTS-only if no embeddings are available.

    Returns:
        List of dicts with standard fields plus a "relevance" key.
    """
    fetch_limit = limit * 2

    fts_results = search_entries(conn, query, limit=fetch_limit, entry_type=entry_type)
    vec_results = vector_search_entries(
        conn, query, limit=fetch_limit, entry_type=entry_type
    )

    # Index vector results by ID for fast lookup
    vec_by_id: dict[int, dict] = {r["id"]: r for r in vec_results}

    merged: dict[int, dict] = {}

    for r in fts_results:
        entry_id = r["id"]
        if entry_id in vec_by_id:
            # Found by both — use vector similarity as relevance
            r["relevance"] = vec_by_id.pop(entry_id)["similarity"]
        else:
            r["relevance"] = 0.3
        merged[entry_id] = r

    # Remaining vector-only results
    for entry_id, r in vec_by_id.items():
        r["relevance"] = r.pop("similarity", 0.3)
        merged[entry_id] = r

    return list(merged.values())


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Delete a memory entry by ID. Returns True if deleted.

    The memory_vec cleanup is handled by the database trigger
    (memory_entries_vec_ad), so no explicit vec deletion is needed.
    """
    cursor = conn.execute("SELECT id FROM memory_entries WHERE id = ?", (entry_id,))
    if not cursor.fetchone():
        return False
    conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
    conn.commit()
    return True
