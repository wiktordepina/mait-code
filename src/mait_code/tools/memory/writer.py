"""Write to the memory database with deduplication.

Uses FTS5 plus vector similarity for candidate retrieval, then applies
dual-threshold checking: ``SequenceMatcher`` for string-level duplicates
and cosine similarity for semantic duplicates.
"""

import logging
import sqlite3
from difflib import SequenceMatcher

from mait_code import config
from mait_code.context import canonical_project
from mait_code.tools.memory.embeddings import embed_text, serialize_f32

logger = logging.getLogger(__name__)

# Maps entry_type to memory_class for decay-rate separation
MEMORY_CLASS_MAP: dict[str, str] = {
    "event": "episodic",
    "task": "episodic",
    "fact": "semantic",
    "preference": "semantic",
    "decision": "semantic",
    "insight": "semantic",
    "relationship": "semantic",
}

VALID_ENTRY_TYPES: set[str] = set(MEMORY_CLASS_MAP)

STRING_SIMILARITY_THRESHOLD: float = config.get_float("dedup-string-threshold")
VECTOR_SIMILARITY_THRESHOLD: float = config.get_float("dedup-vector-threshold")
CONFLICT_SIMILARITY_THRESHOLD: float = config.get_float("dedup-conflict-threshold")


def _project_condition(project: str | None) -> tuple[str, list]:
    """Build the SQL condition and params for project-scoped filtering.

    Args:
        project: Project identifier; ``None`` matches entries with no project.

    Returns:
        ``(sql_fragment, params)`` where ``sql_fragment`` begins with
        ``"AND m.project "``.
    """
    if project is None:
        return "AND m.project IS NULL", []
    return "AND m.project = ?", [project]


def _fts_candidates(
    conn: sqlite3.Connection,
    content: str,
    entry_type: str,
    *,
    project: str | None = None,
) -> list[tuple[int, str]]:
    """Retrieve dedup candidates via FTS5 keyword matching.

    Falls back to a ``LIKE`` search if the FTS table is unavailable.
    """
    words = [w for w in content.split()[:8] if len(w) > 2]
    proj_cond, proj_params = _project_condition(project)

    try:
        if words:
            fts_query = " OR ".join(f'"{w}"' for w in words)
            cursor = conn.execute(
                f"""SELECT m.id, m.content FROM memory_entries m
                   JOIN memory_entries_fts f ON m.id = f.rowid
                   WHERE memory_entries_fts MATCH ? AND m.entry_type = ?
                   AND m.superseded_by IS NULL
                   {proj_cond}
                   LIMIT 20""",
                [fts_query, entry_type, *proj_params],
            )
        else:
            cursor = conn.execute(
                f"""SELECT m.id, m.content FROM memory_entries m
                    WHERE m.entry_type = ? AND m.superseded_by IS NULL
                    {proj_cond} LIMIT 20""",
                [entry_type, *proj_params],
            )
        return cursor.fetchall()
    except sqlite3.OperationalError:
        # FTS table doesn't exist yet — fall back to LIKE
        first_words = " ".join(content.split()[:5])
        cursor = conn.execute(
            f"""SELECT m.id, m.content FROM memory_entries m
               WHERE m.entry_type = ? AND m.content LIKE ?
               AND m.superseded_by IS NULL
               {proj_cond}
               LIMIT 20""",
            [entry_type, f"%{first_words}%", *proj_params],
        )
        return cursor.fetchall()


def _vector_candidates(
    conn: sqlite3.Connection,
    content: str,
    entry_type: str,
    *,
    project: str | None = None,
) -> list[tuple[int, str, float]]:
    """Retrieve dedup candidates via vector similarity.

    Over-fetches and post-filters by project since sqlite-vec doesn't
    support arbitrary ``WHERE`` clauses in k-NN queries.

    Returns:
        Tuples of ``(id, content, similarity)``.
    """
    vec = embed_text(content, prefix="search_document")
    if vec is None:
        return []

    try:
        cursor = conn.execute(
            """SELECT m.id, m.content, v.distance, m.project
               FROM memory_vec v
               JOIN memory_entries m ON m.id = v.rowid
               WHERE v.embedding MATCH ? AND k = 30
                 AND m.entry_type = ?
                 AND m.superseded_by IS NULL""",
            (serialize_f32(vec), entry_type),
        )
        results = []
        for r in cursor.fetchall():
            entry_project = r[3]
            if project is None and entry_project is not None:
                continue
            if project is not None and entry_project != project:
                continue
            results.append((r[0], r[1], max(0.0, 1.0 - r[2])))
        return results
    except Exception as e:
        logger.debug("Vector dedup search failed: %s", e)
        return []


def _assess_candidates(
    conn: sqlite3.Connection,
    content: str,
    entry_type: str,
    *,
    project: str | None = None,
) -> tuple[int | None, list[tuple[int, str, float]]]:
    """Classify candidate content against existing (non-superseded) entries.

    Uses two candidate sources (FTS5 keywords plus vector similarity) and
    two similarity measures: ``SequenceMatcher`` >= 0.85 for string-level
    duplicates, cosine similarity >= 0.92 for semantic duplicates. Dedup is
    project-scoped — identical content in different projects is treated as
    separate entries. Superseded entries are excluded as candidates.

    Args:
        conn: Open memory database connection.
        content: The candidate memory content.
        entry_type: Entry type used to scope the candidate search.
        project: Project identifier; ``None`` matches global-only entries.

    Returns:
        ``(duplicate_id, conflicts)``. ``duplicate_id`` is the id of a
        near-duplicate to merge into, or ``None``. ``conflicts`` is a list of
        ``(id, content, similarity)`` for entries in the contradiction band
        ``[CONFLICT_SIMILARITY_THRESHOLD, VECTOR_SIMILARITY_THRESHOLD)`` —
        candidates that say something related-but-different. It is only
        populated when ``duplicate_id`` is ``None`` (a clear duplicate
        short-circuits the scan) and is sorted by similarity, highest first.
    """
    # Gather candidates from FTS
    fts_hits = _fts_candidates(conn, content, entry_type, project=project)

    # Check FTS candidates with string similarity
    for row_id, existing_content in fts_hits:
        if (
            SequenceMatcher(None, content, existing_content).ratio()
            >= STRING_SIMILARITY_THRESHOLD
        ):
            return row_id, []

    # Check vector candidates for semantic duplicates and contradictions
    seen_ids = {row_id for row_id, _ in fts_hits}
    vec_hits = _vector_candidates(conn, content, entry_type, project=project)

    conflicts: list[tuple[int, str, float]] = []
    for row_id, existing_content, similarity in vec_hits:
        if similarity >= VECTOR_SIMILARITY_THRESHOLD:
            return row_id, []
        # Also string-check vector candidates not seen via FTS
        if row_id not in seen_ids:
            if (
                SequenceMatcher(None, content, existing_content).ratio()
                >= STRING_SIMILARITY_THRESHOLD
            ):
                return row_id, []
        if similarity >= CONFLICT_SIMILARITY_THRESHOLD:
            conflicts.append((row_id, existing_content, similarity))

    conflicts.sort(key=lambda c: c[2], reverse=True)
    return None, conflicts


def find_duplicate(
    conn: sqlite3.Connection,
    content: str,
    entry_type: str,
    *,
    project: str | None = None,
) -> int | None:
    """Check for near-duplicate content in the database.

    Thin wrapper over :func:`_assess_candidates` that discards the
    contradiction-band candidates and returns only the merge target.

    Args:
        conn: Open memory database connection.
        content: The candidate memory content.
        entry_type: Entry type used to scope the candidate search.
        project: Project identifier; ``None`` matches global-only entries.

    Returns:
        The id of the duplicate if found, otherwise ``None``.
    """
    dup_id, _ = _assess_candidates(conn, content, entry_type, project=project)
    return dup_id


def store_memory(
    conn: sqlite3.Connection,
    content: str,
    entry_type: str = "fact",
    importance: int = 5,
    *,
    scope: str = "global",
    project: str | None = None,
    branch: str | None = None,
) -> dict:
    """Store a memory entry, deduplicating near-identical content.

    On duplicate, refreshes the timestamp and keeps the maximum importance.
    On a new entry, inserts with ``memory_class`` derived from ``entry_type``.

    Args:
        conn: Database connection (with schema applied).
        content: The memory content to store.
        entry_type: One of ``fact``, ``preference``, ``decision``, ``event``,
            ``insight``, ``task``, ``relationship``. ``decision`` is an
            extracted architectural decision; ``insight`` is reserved for
            reflection output. Invalid values fall back to ``fact``.
        importance: Importance level 1-10 (clamped).
        scope: Memory scope — ``"global"``, ``"project"``, or ``"branch"``.
        project: Project identifier (e.g. repo basename).
        branch: Branch name (for branch-scoped memories).

    Returns:
        A dict with keys ``action`` (``"created"`` or ``"deduplicated"``),
        ``id``, ``content``, ``scope``, ``project``, ``branch``, and
        ``potential_conflicts`` — a list of ``{"id", "content", "similarity"}``
        for existing entries in the contradiction band that this write may
        contradict. The write is never blocked; the conflicts are surfaced so
        the companion can suggest superseding one of them. Empty on a
        deduplicated write.
    """
    importance = max(1, min(10, importance))
    if entry_type not in VALID_ENTRY_TYPES:
        entry_type = "fact"
    if scope not in ("global", "project", "branch"):
        scope = "global"
    project = canonical_project(project)

    dup_id, conflicts = _assess_candidates(conn, content, entry_type, project=project)
    if dup_id is not None:
        conn.execute(
            """UPDATE memory_entries
               SET created_at = CURRENT_TIMESTAMP,
                   importance = MAX(importance, ?)
               WHERE id = ?""",
            (importance, dup_id),
        )
        conn.commit()
        return {
            "action": "deduplicated",
            "id": dup_id,
            "content": content,
            "scope": scope,
            "project": project,
            "branch": branch,
            "potential_conflicts": [],
        }

    memory_class = MEMORY_CLASS_MAP.get(entry_type, "episodic")
    cursor = conn.execute(
        """INSERT INTO memory_entries
           (content, entry_type, importance, memory_class, scope, project, branch)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (content, entry_type, importance, memory_class, scope, project, branch),
    )
    conn.commit()

    entry_id = cursor.lastrowid
    assert entry_id is not None  # lastrowid is populated after a successful INSERT
    _store_embedding(conn, entry_id, content)

    return {
        "action": "created",
        "id": entry_id,
        "content": content,
        "scope": scope,
        "project": project,
        "branch": branch,
        "potential_conflicts": [
            {"id": cid, "content": ccontent, "similarity": round(sim, 4)}
            for cid, ccontent, sim in conflicts
        ],
    }


def supersede_memory(
    conn: sqlite3.Connection,
    old_id: int,
    content: str,
    *,
    importance: int | None = None,
) -> dict:
    """Supersede an existing memory entry with an evolved version.

    Inserts ``content`` as a fresh entry that inherits the old entry's type,
    class, and scope (project/branch), then marks the old entry superseded —
    pointing ``superseded_by`` at the new id and stamping ``superseded_at``.
    The old row is kept for auditability but hidden from default surfacing.
    This is the explicit, manually-driven counterpart to dedup: it is called
    when a fact has genuinely changed rather than merely been repeated.

    Args:
        conn: Open memory database connection.
        old_id: Id of the entry being superseded.
        content: The new, current content.
        importance: Optional importance for the new entry (1-10, clamped).
            Defaults to the superseded entry's importance.

    Returns:
        On success, a dict with ``action="superseded"``, ``old_id``, ``id``
        (the new entry), ``content``, ``scope``, ``project``, ``branch``. If
        ``old_id`` does not exist, ``{"action": "not_found", "old_id": old_id}``.
    """
    row = conn.execute(
        """SELECT entry_type, importance, memory_class, scope, project, branch
           FROM memory_entries WHERE id = ?""",
        (old_id,),
    ).fetchone()
    if row is None:
        return {"action": "not_found", "old_id": old_id}

    entry_type, old_importance, memory_class, scope, project, branch = row
    new_importance = (
        old_importance if importance is None else max(1, min(10, importance))
    )

    cursor = conn.execute(
        """INSERT INTO memory_entries
           (content, entry_type, importance, memory_class, scope, project, branch)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (content, entry_type, new_importance, memory_class, scope, project, branch),
    )
    new_id = cursor.lastrowid
    assert new_id is not None  # lastrowid is populated after a successful INSERT
    conn.execute(
        """UPDATE memory_entries
           SET superseded_by = ?, superseded_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (new_id, old_id),
    )
    conn.commit()
    _store_embedding(conn, new_id, content)

    return {
        "action": "superseded",
        "old_id": old_id,
        "id": new_id,
        "content": content,
        "scope": scope,
        "project": project,
        "branch": branch,
    }


def _store_embedding(conn: sqlite3.Connection, entry_id: int, content: str) -> None:
    """Compute and store the embedding for a memory entry; never raises."""
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
