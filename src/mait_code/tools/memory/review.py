"""Due-for-review computation for memory resurfacing.

Surfaces important-but-ageing memories for a quick "still true? refine?
promote? retire?" pass, so curated memory stays fresh instead of decaying
silently.

The decay curve is **not** reinvented here: it reuses
:func:`mait_code.tools.memory.scoring.recency_score` — the same per-class
exponential decay that drives retrieval ranking (episodic 3d / semantic 90d /
procedural 180d half-lives). The only twist is the *anchor*: retrieval decays
from ``created_at``, whereas resurfacing decays from ``reviewed_at`` (the last
time the memory was engaged with), so reviewing an item resets its curve.

A memory is **due** when its recall probability, measured from that anchor,
has fallen below ``review-threshold`` (default 0.5 — one half-life since last
review), and its importance is at least ``review-min-importance`` so
low-value memories decay without nagging.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from mait_code import config
from mait_code.tools.memory.db import LIVE_ENTRY_SQL
from mait_code.tools.memory.scoring import recency_score
from mait_code.tools.memory.search import _scope_filter

__all__ = [
    "due_for_review",
]

# Explicit column list rather than reusing search._BASE_COLS: this query needs
# ``reviewed_at`` (coalesced to ``created_at`` for rows that predate a review),
# and search's row mapper is coupled to a fixed column order shared with
# vector search. Keeping this self-contained avoids that fragility.
_REVIEW_COLS = (
    "m.id, m.content, m.entry_type, m.importance, m.memory_class, "
    "m.created_at, m.scope, m.project, m.branch, "
    "COALESCE(m.reviewed_at, m.created_at)"
)


def _row_to_entry(r: tuple) -> dict:
    """Map a review query row to a memory-entry dict (with ``reviewed_at``)."""
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
        "reviewed_at": r[9],
    }


def due_for_review(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    limit: int | None = None,
    project: str | None = None,
    branch: str | None = None,
) -> list[dict]:
    """Return live memories whose recall has decayed below the review threshold.

    Args:
        conn: Open memory database connection.
        now: Override the current time (for testing); defaults to UTC now
            inside :func:`~mait_code.tools.memory.scoring.recency_score`.
        limit: Cap the number of returned items (most-decayed first). ``None``
            returns every due item.
        project: When set, restrict to memories visible in this project
            (global + project/branch scoped), mirroring ``list``'s scope
            filtering. ``None`` considers every live memory.
        branch: Branch context for scope filtering; only meaningful with
            ``project``.

    Returns:
        A list of memory-entry dicts, each with a ``recall`` float in
        ``[0.0, 1.0]``, ordered most-decayed (lowest recall) first. Empty when
        nothing is due.
    """
    threshold = config.get_float("review-threshold")
    min_importance = config.get_int("review-min-importance")

    conditions = [LIVE_ENTRY_SQL, "m.importance >= ?"]
    params: list = [min_importance]
    if project is not None:
        frag, scope_params = _scope_filter(project, branch)
        if frag:
            # `_scope_filter` returns a leading "AND "; strip it since we join
            # the conditions ourselves (mirrors search.list_entries).
            conditions.append(frag.lstrip("AND "))
            params.extend(scope_params)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT {_REVIEW_COLS} FROM memory_entries m WHERE {where}",
        params,
    ).fetchall()

    due: list[dict] = []
    for r in rows:
        entry = _row_to_entry(r)
        recall = recency_score(
            entry["reviewed_at"], now, memory_class=entry["memory_class"]
        )
        if recall < threshold:
            entry["recall"] = recall
            due.append(entry)

    due.sort(key=lambda e: e["recall"])
    if limit is not None:
        due = due[:limit]
    return due
