"""Reflection system — synthesise recent observations into durable insights.

Reads recent memory entries and observation logs, calls Claude to identify
patterns and themes, stores insights back to ``memory.db``, and proposes
updates to ``MEMORY.md``.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta

from mait_code.config import get as config_get
from mait_code.llm import call_claude
from mait_code.tools.memory.db import get_data_dir
from mait_code.tools.memory.writer import store_memory

logger = logging.getLogger(__name__)

REFLECTION_SYSTEM_PROMPT = """\
You are reviewing an AI companion's recent memories and activity observations.
Generate 3-5 high-level insights that synthesise patterns across these entries.

Each insight should be something NOT directly stated in any single entry but
emerges from looking at multiple entries together.

Focus on: recurring themes, behavioural patterns, project trajectory,
evolving preferences, and actionable observations.

Format your response in two sections:

## Insights
One insight per line, starting with "INSIGHT: ".

## Memory Operations
Propose changes to the companion's persistent MEMORY.md file. MEMORY.md is a
small, curated set of durable facts — not a log. Consolidation matters as much
as addition: keep it sharp, non-redundant, and current. Use one line per
operation, choosing from:

MEMORY_ADD: <new durable fact>
MEMORY_REWRITE: <existing fact, verbatim> -> <corrected/sharper fact> [entries: #12, #34]
MEMORY_MERGE: <single consolidated fact> [entries: #5, #9, #21]
MEMORY_RETIRE: <existing fact to drop, verbatim> [entries: #7]

Rules:
- ADD only stable, verified facts — never speculation.
- REWRITE replaces an existing MEMORY.md fact with a better version. Copy the
  existing text verbatim before " -> " so it can be located.
- MERGE folds two or more overlapping facts into one. Give the single
  consolidated fact.
- RETIRE drops a fact that is now stale or contradicted. Copy its existing text
  verbatim.
- A REWRITE or RETIRE MUST be justified by a newer entry above that contradicts
  or supersedes the old fact. If nothing contradicts it, leave it alone.
- Strongly bias toward leaving stable facts untouched. Do not churn wording for
  its own sake. Most reflections should propose few or no operations.
- The optional "[entries: #N, ...]" suffix lists the memory-database entries
  (shown as #N in the entries above) that back the fact, so the underlying
  store can be consolidated too. Include ids only when you can point to specific
  entries above; omit the suffix otherwise.

Omit this section entirely if nothing warrants changing.\
"""


# ---------------------------------------------------------------------------
# Watermark — idempotent reflection tracking
# ---------------------------------------------------------------------------


def get_watermark(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
) -> int | None:
    """Return the last reflected entry ID for a project (or global scope).

    Args:
        conn: Open memory database connection.
        project: Project identifier, or ``None`` for the global watermark.

    Returns:
        The watermark, or ``None`` if no reflection has ever been done for
        this scope.
    """
    project_key = project or ""
    row = conn.execute(
        "SELECT last_reflected_id FROM reflection_watermark WHERE project = ?",
        (project_key,),
    ).fetchone()
    return row[0] if row else None


def update_watermark(
    conn: sqlite3.Connection,
    last_id: int,
    *,
    project: str | None = None,
) -> None:
    """Set the watermark for a project (or global) to ``last_id``.

    Args:
        conn: Open memory database connection.
        last_id: The new high-water-mark entry ID.
        project: Project identifier, or ``None`` for the global watermark.
    """
    project_key = project or ""
    conn.execute(
        """INSERT INTO reflection_watermark (project, last_reflected_id, last_reflected_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(project) DO UPDATE SET
             last_reflected_id = excluded.last_reflected_id,
             last_reflected_at = excluded.last_reflected_at""",
        (project_key, last_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Novelty gate (watermark-based)
# ---------------------------------------------------------------------------


def count_unreflected(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
) -> int:
    """Return the number of entries above the reflection watermark.

    Counts the non-insight entries that a future :func:`reflect` run would
    consider — the observation backlog. With no watermark (no reflection has
    ever run for the scope), every non-insight entry counts.

    Args:
        conn: Open memory database connection.
        project: Project identifier to scope the count; ``None`` for global.
    """
    watermark = get_watermark(conn, project=project)

    conditions = ["entry_type != 'insight'"]
    params: list = []

    if watermark is not None:
        conditions.append("id > ?")
        params.append(watermark)

    if project is not None:
        conditions.append("(scope = 'global' OR project = ?)")
        params.append(project)

    query = f"SELECT COUNT(*) FROM memory_entries WHERE {' AND '.join(conditions)}"
    return conn.execute(query, params).fetchone()[0]


def get_last_reflected_at(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
) -> datetime | None:
    """Return when reflection last ran for a project (or global scope).

    Reads ``last_reflected_at`` from the watermark table — the authoritative
    record of the most recent :func:`reflect` run, regardless of whether it
    produced insights.

    Args:
        conn: Open memory database connection.
        project: Project identifier, or ``None`` for the global watermark.

    Returns:
        The parsed timestamp, or ``None`` if reflection has never run.
    """
    project_key = project or ""
    row = conn.execute(
        "SELECT last_reflected_at FROM reflection_watermark WHERE project = ?",
        (project_key,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return datetime.fromisoformat(row[0])


def check_novelty_gate_v2(
    conn: sqlite3.Connection,
    min_new: int = 3,
    *,
    project: str | None = None,
) -> bool:
    """Return ``True`` if there are enough unreflected entries to justify reflection.

    Args:
        conn: Open memory database connection.
        min_new: Minimum number of new non-insight entries required.
        project: Project identifier to scope the check; ``None`` for global.
    """
    return count_unreflected(conn, project=project) >= min_new


# ---------------------------------------------------------------------------
# Entry retrieval (watermark-aware, batch-limited)
# ---------------------------------------------------------------------------


def get_unreflected_entries(
    conn: sqlite3.Connection,
    batch_size: int = 50,
    days: int | None = None,
    exclude_types: tuple[str, ...] = ("insight",),
    *,
    project: str | None = None,
    watermark: int | None = None,
) -> list[tuple]:
    """Return entries that haven't been reflected on yet.

    Uses ``watermark`` (last reflected ID) for idempotency. If no watermark
    exists and ``days`` is provided, uses ``days`` as a bootstrap window.

    Args:
        conn: Open memory database connection.
        batch_size: Maximum number of entries to return.
        days: Bootstrap window in days when no watermark exists.
        exclude_types: Entry types to exclude (e.g. ``"insight"``).
        project: Project identifier; when set, includes global plus
            project-scoped entries.
        watermark: High-water-mark entry ID; only entries above this are
            returned.

    Returns:
        Tuples of ``(id, content, entry_type, importance, created_at)``.
    """
    conditions: list[str] = []
    params: list = []

    if watermark is not None:
        conditions.append("id > ?")
        params.append(watermark)
    elif days is not None:
        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")

    if exclude_types:
        placeholders = ", ".join("?" for _ in exclude_types)
        conditions.append(f"entry_type NOT IN ({placeholders})")
        params.extend(exclude_types)

    if project is not None:
        conditions.append("(scope = 'global' OR project = ?)")
        params.append(project)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(batch_size)

    query = f"""SELECT id, content, entry_type, importance, created_at
                FROM memory_entries
                {where}
                ORDER BY id ASC
                LIMIT ?"""

    return conn.execute(query, params).fetchall()


# ---------------------------------------------------------------------------
# Deprecated — kept for backward compatibility, no longer called by reflect()
# ---------------------------------------------------------------------------


def get_last_reflection_date(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
) -> datetime | None:
    """Return the timestamp of the most recent insight entry.

    Deprecated: replaced by ``get_watermark()``; kept for backward compat.

    Args:
        conn: Open memory database connection.
        project: Project identifier, or ``None`` for any scope.

    Returns:
        The parsed timestamp, or ``None`` if there is no insight entry.
    """
    if project is not None:
        cursor = conn.execute(
            """SELECT created_at FROM memory_entries
               WHERE entry_type = 'insight'
                 AND (scope = 'global' OR project = ?)
               ORDER BY created_at DESC LIMIT 1""",
            (project,),
        )
    else:
        cursor = conn.execute(
            """SELECT created_at FROM memory_entries
               WHERE entry_type = 'insight'
               ORDER BY created_at DESC LIMIT 1"""
        )
    row = cursor.fetchone()
    if row:
        try:
            return datetime.strptime(row[0][:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None
    return None


def count_entries_since(
    conn: sqlite3.Connection,
    since: datetime,
    exclude_types: tuple[str, ...] = ("insight",),
    *,
    project: str | None = None,
) -> int:
    """Count non-insight memory entries added since a given timestamp.

    Deprecated: replaced by ``check_novelty_gate_v2()``; kept for backward
    compat.

    Args:
        conn: Open memory database connection.
        since: Lower bound timestamp.
        exclude_types: Entry types to exclude from the count.
        project: Project identifier, or ``None`` to count all scopes.
    """
    conditions = ["created_at >= ?"]
    params: list = [since.strftime("%Y-%m-%d %H:%M:%S")]

    if exclude_types:
        placeholders = ", ".join("?" for _ in exclude_types)
        conditions.append(f"entry_type NOT IN ({placeholders})")
        params.extend(exclude_types)

    if project is not None:
        conditions.append("(scope = 'global' OR project = ?)")
        params.append(project)

    query = f"SELECT COUNT(*) FROM memory_entries WHERE {' AND '.join(conditions)}"
    return conn.execute(query, params).fetchone()[0]


def check_novelty_gate(
    conn: sqlite3.Connection,
    min_new: int = 3,
    *,
    project: str | None = None,
) -> bool:
    """Return ``True`` if there are enough new observations to justify reflection.

    Deprecated: replaced by ``check_novelty_gate_v2()``; kept for backward
    compat.

    Args:
        conn: Open memory database connection.
        min_new: Minimum number of new non-insight entries required.
        project: Project identifier, or ``None`` for any scope.
    """
    last_reflection = get_last_reflection_date(conn, project=project)
    if last_reflection is None:
        return True

    new_count = count_entries_since(conn, last_reflection, project=project)
    return new_count >= min_new


def get_recent_entries(
    conn: sqlite3.Connection,
    days: int = 7,
    limit: int = 200,
    exclude_types: tuple[str, ...] = ("insight",),
    *,
    project: str | None = None,
) -> list[tuple]:
    """Return memory entries from the last ``days`` days.

    Deprecated: replaced by ``get_unreflected_entries()``; kept for backward
    compat.

    Args:
        conn: Open memory database connection.
        days: Lookback window in days.
        limit: Maximum number of entries to return.
        exclude_types: Entry types to exclude.
        project: Project identifier; when set, includes global plus
            project-scoped entries.
    """
    conditions = ["created_at >= datetime('now', ?)"]
    params: list = [f"-{days} days"]

    if exclude_types:
        placeholders = ", ".join("?" for _ in exclude_types)
        conditions.append(f"entry_type NOT IN ({placeholders})")
        params.extend(exclude_types)

    if project is not None:
        conditions.append("(scope = 'global' OR project = ?)")
        params.append(project)

    params.append(limit)
    query = f"""SELECT content, entry_type, importance, created_at
                FROM memory_entries
                WHERE {" AND ".join(conditions)}
                ORDER BY created_at DESC
                LIMIT ?"""

    return conn.execute(query, params).fetchall()


# ---------------------------------------------------------------------------
# Observation log reading (kept for restore command, no longer used by reflect)
# ---------------------------------------------------------------------------


def read_observation_logs(days: int = 7) -> str:
    """Read JSONL observation files from the last ``days`` days.

    Parses extraction dicts and formats them into readable text for the
    reflection prompt.

    Args:
        days: Lookback window in days.

    Returns:
        A newline-joined string of formatted extraction items.
    """
    obs_dir = get_data_dir() / "memory" / "observations"
    if not obs_dir.exists():
        return ""

    cutoff = datetime.now() - timedelta(days=days)
    parts = []

    for log_file in sorted(obs_dir.glob("*.jsonl")):
        try:
            file_date = datetime.strptime(log_file.stem, "%Y-%m-%d")
        except ValueError:
            continue
        if file_date < cutoff:
            continue

        try:
            with open(log_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    extraction = record.get("extraction", {})
                    items = _format_extraction(extraction)
                    if items:
                        parts.append(items)
        except OSError:
            logger.warning("failed to read observation log: %s", log_file)
            continue

    return "\n".join(parts)


def _format_extraction(extraction: dict) -> str:
    """Format a single extraction dict as readable text lines."""
    lines = []
    for category in ("facts", "preferences", "decisions", "bugs_fixed"):
        for item in extraction.get(category, []):
            content = item.get("content", "").strip()
            if content:
                imp = item.get("importance", 5)
                lines.append(f"- [{category}] (imp={imp}) {content[:200]}")

    for entity in extraction.get("entities", []):
        name = entity.get("name", "")
        etype = entity.get("entity_type", "unknown")
        ctx = entity.get("context", "")
        if name:
            lines.append(f"- [entity] {name} ({etype}): {ctx[:100]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting and parsing
# ---------------------------------------------------------------------------


def format_entries_text(entries: list[tuple]) -> str:
    """Format DB entries as text for the reflection prompt.

    Accepts both 4-tuples (legacy:
    ``(content, type, importance, created_at)``) and 5-tuples
    (``(id, content, type, importance, created_at)``).

    Args:
        entries: Rows fetched from ``memory_entries``.

    Returns:
        A newline-joined string of formatted entries.
    """
    lines = []
    for entry in entries:
        if len(entry) == 5:
            entry_id, content, entry_type, importance, created_at = entry
            prefix = f"#{entry_id} "
        else:
            content, entry_type, importance, created_at = entry
            prefix = ""
        lines.append(
            f"- {prefix}[{created_at[:10]}] ({entry_type}, imp={importance}) "
            f"{content[:200]}"
        )
    return "\n".join(lines)


# Op markers the reflection model may emit, mapped to their op kind.
# ``MEMORY_UPDATE`` is kept as a back-compat alias for ``MEMORY_ADD``.
_OP_MARKERS: dict[str, str] = {
    "MEMORY_ADD:": "add",
    "MEMORY_UPDATE:": "add",
    "MEMORY_REWRITE:": "rewrite",
    "MEMORY_MERGE:": "merge",
    "MEMORY_RETIRE:": "retire",
}

# Trailing "[entries: #1, #2]" suffix carrying the backing db entry ids.
_ENTRIES_SUFFIX = re.compile(r"\[entries:\s*([^\]]*)\]\s*$", re.IGNORECASE)


def _extract_entry_ids(text: str) -> tuple[str, list[int]]:
    """Split a trailing ``[entries: #1, #2]`` suffix off an op line.

    Returns the text with the suffix removed (stripped) and the parsed ids in
    order, de-duplicated. A line with no suffix yields an empty id list.
    """
    match = _ENTRIES_SUFFIX.search(text)
    if not match:
        return text.strip(), []
    ids = [int(n) for n in re.findall(r"\d+", match.group(1))]
    return text[: match.start()].strip(), list(dict.fromkeys(ids))


def _build_op(kind: str, body: str) -> dict | None:
    """Build a structured op dict from a marker kind and its line body.

    Returns ``None`` for malformed bodies (e.g. a rewrite missing its ``->``,
    or an empty payload) so the caller can drop them silently.
    """
    body, entry_ids = _extract_entry_ids(body)
    if kind == "rewrite":
        old, sep, new = body.partition("->")
        old, new = old.strip(), new.strip()
        if not sep or not old or not new:
            return None
        return {"op": "rewrite", "old": old, "new": new, "entry_ids": entry_ids}
    if not body:
        return None
    if kind == "retire":
        return {"op": "retire", "old": body, "new": None, "entry_ids": entry_ids}
    if kind == "merge":
        return {"op": "merge", "old": None, "new": body, "entry_ids": entry_ids}
    return {"op": "add", "old": None, "new": body, "entry_ids": entry_ids}


def parse_reflection_response(response: str) -> dict:
    """Parse the LLM response into insights and structured memory operations.

    Recognises ``INSIGHT:`` lines plus the consolidation op markers in
    :data:`_OP_MARKERS`. Each op is a dict with keys ``op`` (``"add"`` /
    ``"rewrite"`` / ``"merge"`` / ``"retire"``), ``old`` (existing MEMORY.md
    text, or ``None``), ``new`` (new text, or ``None`` for retire), and
    ``entry_ids`` (backing db entries to consolidate, possibly empty).
    Unrecognised or malformed lines are ignored, not fatal.

    Args:
        response: The raw LLM response text.

    Returns:
        A dict ``{"insights": [...], "ops": [...]}``.
    """
    insights: list[str] = []
    ops: list[dict] = []

    for raw in response.strip().split("\n"):
        line = raw.strip()
        if line.startswith("INSIGHT:"):
            text = line[len("INSIGHT:") :].strip()
            if text:
                insights.append(text)
            continue
        for marker, kind in _OP_MARKERS.items():
            if line.startswith(marker):
                op = _build_op(kind, line[len(marker) :].strip())
                if op is not None:
                    ops.append(op)
                break

    return {"insights": insights, "ops": ops}


def store_insights(
    conn: sqlite3.Connection,
    insights: list[str],
    *,
    project: str | None = None,
) -> int:
    """Store insights in the memory database with fixed ``importance=6``.

    Args:
        conn: Open memory database connection.
        insights: Insight strings to store.
        project: Project identifier; when set, insights are project-scoped,
            otherwise they are stored globally.

    Returns:
        The number of insights stored.
    """
    stored = 0
    scope = "project" if project else "global"
    for insight in insights:
        store_memory(
            conn,
            insight,
            "insight",
            importance=6,
            scope=scope,
            project=project,
        )
        stored += 1
    return stored


def read_memory_md() -> str | None:
    """Return the current ``MEMORY.md`` content, or ``None`` if missing."""
    memory_md = get_data_dir() / "memory" / "MEMORY.md"
    if memory_md.exists():
        return memory_md.read_text()
    return None


def _entry_previews(
    conn: sqlite3.Connection, ops: list[dict], *, width: int = 80
) -> dict[int, str]:
    """Fetch short content snippets for every db entry an op references."""
    ids = {i for op in ops for i in op.get("entry_ids", [])}
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, content FROM memory_entries WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    return {row[0]: row[1][:width] for row in rows}


def _entry_tag(entry_ids: list[int], verb: str) -> str:
    """Render the ``[verb #1, #2]`` annotation for an op's db targets."""
    if not entry_ids:
        return ""
    return f"   [{verb} " + ", ".join(f"#{i}" for i in entry_ids) + "]"


def generate_memory_diff(
    ops: list[dict], previews: dict[int, str] | None = None
) -> str:
    """Render proposed MEMORY.md operations as a readable before/after diff.

    Additions show as ``+``, retirements as ``-``, rewrites as the old line
    (``~``) followed by its replacement (``→``), and merges as one ``-`` per
    folded db entry followed by the single consolidated ``+`` line. Each op that
    names backing db entries is annotated with the store-level verb applied to
    them.

    Args:
        ops: Structured ops from :func:`parse_reflection_response`.
        previews: Optional ``{entry_id: content snippet}`` used to show the
            source rows of a merge; falls back to an inline id tag when absent.
    """
    previews = previews or {}
    lines = ["Proposed MEMORY.md changes:", ""]
    for op in ops:
        kind = op["op"]
        entry_ids = op.get("entry_ids", [])
        if kind == "add":
            lines.append(f"+ {op['new']}")
        elif kind == "rewrite":
            lines.append(f"~ {op['old']}")
            lines.append(f"    → {op['new']}{_entry_tag(entry_ids, 'supersede')}")
        elif kind == "retire":
            lines.append(f"- {op['old']}{_entry_tag(entry_ids, 'retire')}")
        elif kind == "merge":
            shown = False
            for i in entry_ids:
                snippet = previews.get(i)
                if snippet:
                    lines.append(f"- #{i} {snippet}")
                    shown = True
            if shown:
                lines.append(f"+ {op['new']}")
            else:
                lines.append(f"+ {op['new']}{_entry_tag(entry_ids, 'merge')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def reflect(
    conn: sqlite3.Connection,
    days: int = 7,
    min_new: int = 3,
    batch_size: int = 50,
    *,
    project: str | None = None,
    branch: str | None = None,
) -> dict:
    """Run the main reflection orchestrator.

    Uses a watermark to track which entries have been reflected on, ensuring
    idempotent operation. Processes entries in batches. When ``project`` is
    provided, reflects only on global plus project-scoped entries.

    Args:
        conn: Open memory database connection.
        days: Bootstrap window in days when no watermark exists.
        min_new: Minimum new non-insight entries required to proceed.
        batch_size: Maximum entries processed per reflection.
        project: Project identifier scoping the reflection.
        branch: Branch name included in the prompt context only.

    Returns:
        A dict with keys ``skipped``, ``reason``, ``insights``, ``ops`` (the
        structured MEMORY.md operations proposed — see
        :func:`parse_reflection_response`), ``stored``, ``memory_diff``, and
        ``batch_info`` (the last containing ``processed`` and ``watermark``
        counts, or ``None`` when skipped).
    """
    # Novelty gate (watermark-based)
    if not check_novelty_gate_v2(conn, min_new, project=project):
        return {
            "skipped": True,
            "reason": "not enough new observations since last reflection",
            "insights": [],
            "ops": [],
            "stored": 0,
            "memory_diff": None,
            "batch_info": None,
        }

    # Get watermark and unreflected entries
    watermark = get_watermark(conn, project=project)
    entries = get_unreflected_entries(
        conn,
        batch_size,
        days=days if watermark is None else None,
        project=project,
        watermark=watermark,
    )

    if not entries:
        return {
            "skipped": True,
            "reason": "no unreflected entries found",
            "insights": [],
            "ops": [],
            "stored": 0,
            "memory_diff": None,
            "batch_info": None,
        }

    # Build prompt
    entries_text = format_entries_text(entries)

    prompt_parts = []
    if entries_text:
        prompt_parts.append(f"Recent memory entries:\n{entries_text}")

    current_memory = read_memory_md()
    if current_memory:
        prompt_parts.append(f"Current MEMORY.md content:\n{current_memory[:2000]}")

    if project:
        prompt_parts.insert(
            0,
            f"Project context: {project}" + (f" (branch: {branch})" if branch else ""),
        )

    prompt = "\n\n".join(prompt_parts)

    # Call LLM
    response = call_claude(
        prompt,
        system_prompt=REFLECTION_SYSTEM_PROMPT,
        model=config_get("reflection-model"),
    )

    if not response:
        return {
            "skipped": False,
            "reason": "LLM call failed",
            "insights": [],
            "ops": [],
            "stored": 0,
            "memory_diff": None,
            "batch_info": None,
        }

    # Parse response
    parsed = parse_reflection_response(response)
    insights = parsed["insights"]
    ops = parsed["ops"]

    # Store insights
    stored = store_insights(conn, insights, project=project) if insights else 0

    # Update watermark to highest entry ID processed
    new_watermark = max(e[0] for e in entries)
    update_watermark(conn, new_watermark, project=project)

    # Generate memory diff (with snippets of any backing db entries)
    memory_diff = None
    if ops:
        memory_diff = generate_memory_diff(ops, _entry_previews(conn, ops))

    return {
        "skipped": False,
        "reason": None,
        "insights": insights,
        "ops": ops,
        "stored": stored,
        "memory_diff": memory_diff,
        "batch_info": {"processed": len(entries), "watermark": new_watermark},
    }
