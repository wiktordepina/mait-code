"""Observation queries — the raw extraction tier, for browsing surfaces.

The observe hook stores what it extracts from sessions as ordinary
``memory_entries`` rows (facts, preferences, decisions, events); reflection
later synthesises them into ``insight`` rows and advances a per-project
watermark. This module is the read layer over that raw tier: list the
observations with their reflected/pending standing against the watermark,
enumerate the projects they span, and summarise the daily JSONL capture logs
the hook also writes.

``memory.db`` is the source of truth throughout — the watermark is defined
over its entry IDs. The JSONL files under ``memory/observations/`` only
contribute per-capture metadata (trigger, counts) that the rows don't carry,
and are read best-effort.
"""

from __future__ import annotations

import json
import sqlite3

from mait_code.tools.memory.db import get_data_dir

__all__ = [
    # Queries
    "list_observations",
    "observation_projects",
    # Capture-log summaries
    "BATCH_CATEGORIES",
    "daily_batches",
]

#: Categories an extraction batch may carry, in display order.
BATCH_CATEGORIES: tuple[str, ...] = (
    "facts",
    "preferences",
    "decisions",
    "bugs_fixed",
    "entities",
    "relationships",
)

#: Effectively "everything": a browser shows the whole tier, so the query just
#: needs a bound that no real store approaches (mirrors the memory browser).
_FETCH_LIMIT = 100_000


def list_observations(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    limit: int = _FETCH_LIMIT,
) -> list[dict]:
    """List the raw observations, newest first, flagged against the watermark.

    Returns every non-insight entry (insights are reflection *output*, not
    observations), each carrying the standard entry fields plus ``reflected``:
    whether the entry sits at or below the relevant reflection watermark — the
    project's own when ``project`` is given, the global one otherwise, matching
    :func:`~mait_code.tools.memory.reflect.count_unreflected`. With no
    watermark for the scope, nothing has been reflected yet.

    Args:
        conn: Open memory database connection.
        project: Filter to this project context (includes global entries) and
            judge against its watermark; ``None`` for everything.
        limit: Maximum number of results.

    Returns:
        A list of dicts ordered by entry ID descending (newest first).
    """
    # Imported here, not at module top: reflect.py pulls in the LLM layer.
    from mait_code.tools.memory.reflect import get_watermark

    conditions = ["entry_type != 'insight'"]
    params: list = []
    if project is not None:
        conditions.append("(scope = 'global' OR project = ?)")
        params.append(project)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT id, content, entry_type, importance, memory_class,
                   scope, project, branch, created_at
            FROM memory_entries
            WHERE {" AND ".join(conditions)}
            ORDER BY id DESC
            LIMIT ?""",
        params,
    ).fetchall()

    watermark = get_watermark(conn, project=project)
    return [
        {
            "id": row[0],
            "content": row[1],
            "entry_type": row[2],
            "importance": row[3],
            "memory_class": row[4],
            "scope": row[5],
            "project": row[6],
            "branch": row[7],
            "created_at": row[8],
            "reflected": watermark is not None and row[0] <= watermark,
        }
        for row in rows
    ]


def observation_projects(conn: sqlite3.Connection) -> list[str]:
    """List the distinct projects observations span, alphabetically.

    Feeds filter UIs (the observations browser's project ``Select``); global
    entries carry no project and so don't contribute a name.

    Args:
        conn: Open memory database connection.
    """
    rows = conn.execute(
        """SELECT DISTINCT project FROM memory_entries
           WHERE entry_type != 'insight' AND project IS NOT NULL
           ORDER BY project COLLATE NOCASE"""
    ).fetchall()
    return [row[0] for row in rows]


def daily_batches(day: str) -> list[dict]:
    """Summarise a day's capture batches from its JSONL observation log.

    Each observe-hook run appends one record to
    ``memory/observations/<day>.jsonl``; this reads them back as light
    summaries — when and why a capture happened and how much it extracted —
    without the extraction bodies (those live in ``memory.db``).

    Best-effort by design: a missing file, an unreadable file, or a malformed
    line yields no batch rather than raising — the JSONL is supplementary
    metadata, never load-bearing.

    Args:
        day: The log's date stamp, ``YYYY-MM-DD``.

    Returns:
        Dicts with ``timestamp``, ``trigger``, ``project``, ``branch`` and
        ``counts`` (items per :data:`BATCH_CATEGORIES` category; zero-count
        categories omitted), in file (chronological) order.
    """
    path = get_data_dir() / "memory" / "observations" / f"{day}.jsonl"
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []

    batches: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        extraction = record.get("extraction") or {}
        counts = {
            category: len(extraction.get(category) or [])
            for category in BATCH_CATEGORIES
        }
        batches.append(
            {
                "timestamp": record.get("timestamp"),
                "trigger": record.get("trigger"),
                "project": record.get("project"),
                "branch": record.get("branch"),
                "counts": {c: n for c, n in counts.items() if n},
            }
        )
    return batches
