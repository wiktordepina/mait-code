"""Search operations: keyword (FTS5), vector (sqlite-vec), and hybrid.

Provides search, listing, and deletion operations on memory entries.
"""

import logging
import sqlite3

from mait_code.tools.memory.embeddings import embed_text, serialize_f32

logger = logging.getLogger(__name__)

# Columns returned from all search/list queries
_BASE_COLS = (
    "m.id, m.content, m.entry_type, m.importance, m.memory_class, "
    "m.created_at, m.scope, m.project, m.branch, m.superseded_by, m.superseded_at"
)

# SQL fragment (leading "AND ") that hides superseded entries unless opted in.
_LIVE_ONLY = "AND m.superseded_by IS NULL"


def _scope_filter(project: str | None, branch: str | None) -> tuple[str, list]:
    """Build the SQL WHERE fragment for scope-aware filtering.

    When ``project`` is provided, the returned fragment matches entries
    that are global (always visible), project-scoped to ``project``, or
    branch-scoped to both ``project`` and ``branch``.

    Args:
        project: Project context, or ``None`` to disable filtering.
        branch: Branch context, or ``None`` to omit branch matching.

    Returns:
        ``(sql_fragment, params)``. The fragment begins with ``"AND "``.
    """
    if project is None:
        return "", []
    if branch is not None:
        return (
            "AND (m.scope = 'global' OR (m.project = ? AND "
            "(m.scope = 'project' OR (m.scope = 'branch' AND m.branch = ?))))",
            [project, branch],
        )
    return (
        "AND (m.scope = 'global' OR (m.project = ? AND m.scope = 'project'))",
        [project],
    )


def _row_to_dict(r: tuple) -> dict:
    """Convert a query row to a dict with the standard memory entry fields."""
    return {
        "id": r[0],
        "content": r[1],
        "entry_type": r[2],
        "importance": r[3],
        "memory_class": r[4],
        "created_at": r[5],
        "scope": r[6],
        "project": r[7],
        "branch": r[8],
        "superseded_by": r[9],
        "superseded_at": r[10],
    }


def search_entries(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    entry_type: str | None = None,
    *,
    project: str | None = None,
    branch: str | None = None,
    include_superseded: bool = False,
) -> list[dict]:
    """Search memory entries using FTS5 BM25 ranking.

    Falls back to ``LIKE`` if FTS5 is not available. When ``project`` is
    provided, filters to global plus matching project/branch entries.

    Args:
        conn: Open memory database connection.
        query: FTS5 query string (or substring for the fallback path).
        limit: Maximum number of results.
        entry_type: Optional entry-type filter.
        project: Project context for scope filtering.
        branch: Branch context for scope filtering.
        include_superseded: Include entries that have been superseded
            (hidden by default).

    Returns:
        A list of dicts with the standard memory entry fields.
    """
    scope_cond, scope_params = _scope_filter(project, branch)
    type_cond = "AND m.entry_type = ?" if entry_type else ""
    type_params = [entry_type] if entry_type else []
    live_cond = "" if include_superseded else _LIVE_ONLY

    try:
        cursor = conn.execute(
            f"""SELECT {_BASE_COLS}
                FROM memory_entries_fts f
                JOIN memory_entries m ON m.id = f.rowid
                WHERE memory_entries_fts MATCH ?
                {type_cond} {scope_cond} {live_cond}
                ORDER BY bm25(memory_entries_fts)
                LIMIT ?""",
            [query, *type_params, *scope_params, limit],
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        cursor = conn.execute(
            f"""SELECT {_BASE_COLS}
                FROM memory_entries m
                WHERE m.content LIKE ?
                {type_cond} {scope_cond} {live_cond}
                ORDER BY m.importance DESC, m.created_at DESC
                LIMIT ?""",
            [f"%{query}%", *type_params, *scope_params, limit],
        )
        rows = cursor.fetchall()

    return [_row_to_dict(r) for r in rows]


def _parse_since(since: str) -> str | None:
    """Parse a human-readable period into a SQLite datetime modifier.

    Args:
        since: Period string like ``"24h"``, ``"48h"``, ``"7d"``, ``"1w"``.

    Returns:
        A modifier suitable for ``datetime('now', modifier)``, or ``None``
        if the input cannot be parsed.
    """
    import re

    m = re.fullmatch(r"(\d+)\s*(h|d|w)", since.strip().lower())
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return f"-{value} hours"
    if unit == "d":
        return f"-{value} days"
    if unit == "w":
        return f"-{value * 7} days"
    return None


def list_entries(
    conn: sqlite3.Connection,
    limit: int = 20,
    entry_type: str | None = None,
    since: str | None = None,
    *,
    project: str | None = None,
    branch: str | None = None,
    scope: str | None = None,
    include_superseded: bool = False,
) -> list[dict]:
    """List recent memory entries, optionally filtered by type, time, and scope.

    Args:
        conn: Open memory database connection.
        limit: Maximum number of results.
        entry_type: Optional entry-type filter.
        since: Human-readable period like ``"24h"``, ``"7d"``, ``"1w"``.
        project: Filter to this project context (includes global).
        branch: Filter to this branch context.
        scope: Explicit scope filter (``"global"``, ``"project"``,
            ``"branch"``); overrides project-based filtering when set.
        include_superseded: Include entries that have been superseded
            (hidden by default).

    Returns:
        A list of dicts with the standard memory entry fields, ordered by
        ``created_at`` descending.
    """
    conditions: list[str] = []
    params: list = []

    if not include_superseded:
        conditions.append("m.superseded_by IS NULL")

    if entry_type:
        conditions.append("m.entry_type = ?")
        params.append(entry_type)

    if since:
        modifier = _parse_since(since)
        if modifier:
            conditions.append("m.created_at >= datetime('now', ?)")
            params.append(modifier)

    if scope:
        conditions.append("m.scope = ?")
        params.append(scope)
    elif project is not None:
        scope_cond, scope_params = _scope_filter(project, branch)
        if scope_cond:
            # Strip leading 'AND ' since we're building WHERE ourselves
            conditions.append(scope_cond.lstrip("AND "))
            params.extend(scope_params)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    cursor = conn.execute(
        f"""SELECT {_BASE_COLS}
            FROM memory_entries m
            {where}
            ORDER BY m.created_at DESC LIMIT ?""",
        params,
    )

    return [_row_to_dict(r) for r in cursor.fetchall()]


def vector_search_entries(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    entry_type: str | None = None,
    *,
    project: str | None = None,
    branch: str | None = None,
    include_superseded: bool = False,
) -> list[dict]:
    """Search memory entries using vector similarity via sqlite-vec.

    Over-fetches and post-filters by scope, since sqlite-vec doesn't
    support arbitrary ``WHERE`` clauses in k-NN queries.

    Args:
        conn: Open memory database connection.
        query: Query text to embed and search.
        limit: Maximum number of results.
        entry_type: Optional entry-type filter.
        project: Project context for scope filtering.
        branch: Branch context for scope filtering.
        include_superseded: Include entries that have been superseded
            (hidden by default).

    Returns:
        A list of dicts with the standard fields plus a ``"similarity"``
        key in ``[0.0, 1.0]``. Empty list if embeddings are unavailable.
    """
    vec = embed_text(query, prefix="search_query")
    if vec is None:
        return []

    # Over-fetch to account for post-filtering
    fetch_k = limit * 3 if project is not None else limit
    live_cond = "" if include_superseded else _LIVE_ONLY

    try:
        if entry_type:
            cursor = conn.execute(
                f"""SELECT {_BASE_COLS}, v.distance
                   FROM memory_vec v
                   JOIN memory_entries m ON m.id = v.rowid
                   WHERE v.embedding MATCH ? AND k = ?
                     AND m.entry_type = ? {live_cond}""",
                (serialize_f32(vec), fetch_k, entry_type),
            )
        else:
            cursor = conn.execute(
                f"""SELECT {_BASE_COLS}, v.distance
                   FROM memory_vec v
                   JOIN memory_entries m ON m.id = v.rowid
                   WHERE v.embedding MATCH ? AND k = ? {live_cond}""",
                (serialize_f32(vec), fetch_k),
            )
        rows = cursor.fetchall()
    except Exception as e:
        logger.debug("Vector search failed: %s", e)
        return []

    results = []
    for r in rows:
        entry = _row_to_dict(r)
        entry["similarity"] = max(0.0, 1.0 - r[11])

        # Post-filter by scope
        if project is not None:
            entry_scope = entry["scope"]
            if entry_scope == "global":
                pass  # Always include
            elif entry["project"] != project:
                continue
            elif entry_scope == "branch" and branch and entry["branch"] != branch:
                continue

        results.append(entry)
        if len(results) >= limit:
            break

    return results


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    entry_type: str | None = None,
    *,
    project: str | None = None,
    branch: str | None = None,
    include_superseded: bool = False,
) -> list[dict]:
    """Run a combined FTS5 + vector search and return merged results.

    Runs both search methods, merges by entry ID, and assigns a relevance
    score suitable for ``composite_score()``:

    * Entries found by both: use vector similarity as relevance.
    * FTS-only entries: default relevance ``0.3``.
    * Vector-only entries: default relevance ``0.3``.

    Falls back to FTS-only if no embeddings are available.

    Args:
        conn: Open memory database connection.
        query: Query text.
        limit: Maximum number of results from each underlying search.
        entry_type: Optional entry-type filter.
        project: Project context for scope filtering.
        branch: Branch context for scope filtering.

    Returns:
        A list of dicts with the standard fields plus a ``"relevance"`` key.
    """
    fetch_limit = limit * 2

    fts_results = search_entries(
        conn,
        query,
        limit=fetch_limit,
        entry_type=entry_type,
        project=project,
        branch=branch,
        include_superseded=include_superseded,
    )
    vec_results = vector_search_entries(
        conn,
        query,
        limit=fetch_limit,
        entry_type=entry_type,
        project=project,
        branch=branch,
        include_superseded=include_superseded,
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
    """Delete a memory entry by ID.

    The ``memory_vec`` cleanup is handled by the database trigger
    (``memory_entries_vec_ad``), so no explicit vec deletion is needed.

    Args:
        conn: Open memory database connection.
        entry_id: Primary-key id of the entry to delete.

    Returns:
        ``True`` if a row was deleted, ``False`` if no entry had that id.
    """
    cursor = conn.execute("SELECT id FROM memory_entries WHERE id = ?", (entry_id,))
    if not cursor.fetchone():
        return False
    conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
    conn.commit()
    return True
