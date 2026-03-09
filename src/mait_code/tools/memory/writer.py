"""
Write to memory database with deduplication.

Uses FTS5 + vector similarity for candidate retrieval, then applies
dual-threshold checking: SequenceMatcher for string-level duplicates
and cosine similarity for semantic duplicates.
"""

import logging
import sqlite3
from difflib import SequenceMatcher

from mait_code.tools.memory.embeddings import embed_text, serialize_f32

logger = logging.getLogger(__name__)

# Maps entry_type to memory_class for decay-rate separation
MEMORY_CLASS_MAP: dict[str, str] = {
    "event": "episodic",
    "task": "episodic",
    "fact": "semantic",
    "preference": "semantic",
    "insight": "semantic",
    "relationship": "semantic",
}

VALID_ENTRY_TYPES: set[str] = set(MEMORY_CLASS_MAP)

STRING_SIMILARITY_THRESHOLD: float = 0.85
VECTOR_SIMILARITY_THRESHOLD: float = 0.92


def _fts_candidates(
    conn: sqlite3.Connection, content: str, entry_type: str
) -> list[tuple[int, str]]:
    """Retrieve dedup candidates via FTS5 keyword matching."""
    words = [w for w in content.split()[:8] if len(w) > 2]

    try:
        if words:
            fts_query = " OR ".join(f'"{w}"' for w in words)
            cursor = conn.execute(
                """SELECT m.id, m.content FROM memory_entries m
                   JOIN memory_entries_fts f ON m.id = f.rowid
                   WHERE memory_entries_fts MATCH ? AND m.entry_type = ?
                   LIMIT 20""",
                (fts_query, entry_type),
            )
        else:
            cursor = conn.execute(
                "SELECT id, content FROM memory_entries WHERE entry_type = ? LIMIT 20",
                (entry_type,),
            )
        return cursor.fetchall()
    except sqlite3.OperationalError:
        # FTS table doesn't exist yet — fall back to LIKE
        first_words = " ".join(content.split()[:5])
        cursor = conn.execute(
            """SELECT id, content FROM memory_entries
               WHERE entry_type = ? AND content LIKE ?
               LIMIT 20""",
            (entry_type, f"%{first_words}%"),
        )
        return cursor.fetchall()


def _vector_candidates(
    conn: sqlite3.Connection, content: str, entry_type: str
) -> list[tuple[int, str, float]]:
    """Retrieve dedup candidates via vector similarity.

    Returns list of (id, content, similarity) tuples.
    """
    vec = embed_text(content, prefix="search_document")
    if vec is None:
        return []

    try:
        cursor = conn.execute(
            """SELECT m.id, m.content, v.distance
               FROM memory_vec v
               JOIN memory_entries m ON m.id = v.rowid
               WHERE v.embedding MATCH ? AND k = 10
                 AND m.entry_type = ?""",
            (serialize_f32(vec), entry_type),
        )
        return [(r[0], r[1], max(0.0, 1.0 - r[2])) for r in cursor.fetchall()]
    except Exception as e:
        logger.debug("Vector dedup search failed: %s", e)
        return []


def find_duplicate(
    conn: sqlite3.Connection, content: str, entry_type: str
) -> int | None:
    """
    Check for near-duplicate content in the database.

    Uses two candidate sources (FTS5 keywords + vector similarity) and
    two similarity measures: SequenceMatcher >= 0.85 for string-level
    duplicates, cosine similarity >= 0.92 for semantic duplicates.

    Returns the ID of the duplicate if found, or None.
    """
    # Gather candidates from FTS
    fts_hits = _fts_candidates(conn, content, entry_type)

    # Check FTS candidates with string similarity
    for row_id, existing_content in fts_hits:
        if (
            SequenceMatcher(None, content, existing_content).ratio()
            >= STRING_SIMILARITY_THRESHOLD
        ):
            return row_id

    # Check vector candidates for semantic duplicates
    seen_ids = {row_id for row_id, _ in fts_hits}
    vec_hits = _vector_candidates(conn, content, entry_type)

    for row_id, existing_content, similarity in vec_hits:
        if similarity >= VECTOR_SIMILARITY_THRESHOLD:
            return row_id
        # Also string-check vector candidates not seen via FTS
        if row_id not in seen_ids:
            if (
                SequenceMatcher(None, content, existing_content).ratio()
                >= STRING_SIMILARITY_THRESHOLD
            ):
                return row_id

    return None


def store_memory(
    conn: sqlite3.Connection,
    content: str,
    entry_type: str = "fact",
    importance: int = 5,
) -> dict:
    """
    Store a memory entry, deduplicating near-identical content.

    On duplicate: updates timestamp and keeps max importance.
    On new: inserts with memory_class derived from entry_type.

    Args:
        conn: Database connection (with schema applied).
        content: The memory content to store.
        entry_type: One of: fact, preference, event, insight, task, relationship.
        importance: Importance level 1-10.

    Returns:
        Dict with keys: action ("created"|"deduplicated"), id, content.
    """
    importance = max(1, min(10, importance))
    if entry_type not in VALID_ENTRY_TYPES:
        entry_type = "fact"

    dup_id = find_duplicate(conn, content, entry_type)
    if dup_id is not None:
        conn.execute(
            """UPDATE memory_entries
               SET created_at = CURRENT_TIMESTAMP,
                   importance = MAX(importance, ?)
               WHERE id = ?""",
            (importance, dup_id),
        )
        conn.commit()
        return {"action": "deduplicated", "id": dup_id, "content": content}

    memory_class = MEMORY_CLASS_MAP.get(entry_type, "episodic")
    cursor = conn.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class)
           VALUES (?, ?, ?, ?)""",
        (content, entry_type, importance, memory_class),
    )
    conn.commit()

    entry_id = cursor.lastrowid
    _store_embedding(conn, entry_id, content)

    return {"action": "created", "id": entry_id, "content": content}


def _store_embedding(
    conn: sqlite3.Connection, entry_id: int, content: str
) -> None:
    """Compute and store embedding for a memory entry. Never raises."""
    try:
        vec = embed_text(content, prefix="search_document")
        if vec is not None:
            conn.execute(
                "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
                (entry_id, serialize_f32(vec)),
            )
            conn.commit()
    except Exception as e:
        logger.debug("Embedding storage failed for entry %d: %s", entry_id, e)
