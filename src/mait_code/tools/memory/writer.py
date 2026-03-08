"""
Write to memory database with deduplication.

Uses FTS5 for fast candidate retrieval and SequenceMatcher for
precise similarity checking. Near-identical entries (>= 90% similar)
are merged rather than duplicated.
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

SIMILARITY_THRESHOLD: float = 0.90


def find_duplicate(
    conn: sqlite3.Connection, content: str, entry_type: str
) -> int | None:
    """
    Check for near-duplicate content in the database.

    Uses FTS5 for fast candidate retrieval, then SequenceMatcher for
    precise similarity. Returns the ID of the duplicate if found
    (>= 0.90 similarity), or None.
    """
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
        candidates = cursor.fetchall()
    except sqlite3.OperationalError:
        # FTS table doesn't exist yet — fall back to LIKE
        first_words = " ".join(content.split()[:5])
        cursor = conn.execute(
            """SELECT id, content FROM memory_entries
               WHERE entry_type = ? AND content LIKE ?
               LIMIT 20""",
            (entry_type, f"%{first_words}%"),
        )
        candidates = cursor.fetchall()

    for row_id, existing_content in candidates:
        if (
            SequenceMatcher(None, content, existing_content).ratio()
            >= SIMILARITY_THRESHOLD
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
