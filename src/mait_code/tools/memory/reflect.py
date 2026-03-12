"""
Reflection system — synthesise recent observations into durable insights.

Reads recent memory entries and observation logs, calls Claude to identify
patterns and themes, stores insights back to memory.db, and proposes
updates to MEMORY.md.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta

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
One insight per line, starting with "INSIGHT: "

## Memory Updates
If you identify high-confidence facts that should be added to the companion's
persistent MEMORY.md file, list them as lines starting with "MEMORY_UPDATE: ".
These should be stable, verified facts — not speculative observations.
Only propose updates if there are clear, durable facts worth persisting.
If none, omit this section.\
"""


# ---------------------------------------------------------------------------
# Watermark — idempotent reflection tracking
# ---------------------------------------------------------------------------


def get_watermark(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
) -> int | None:
    """Get the last reflected entry ID for a project (or global).

    Returns None if no reflection has ever been done for this scope.
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
    """Set the watermark to the given entry ID."""
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


def check_novelty_gate_v2(
    conn: sqlite3.Connection,
    min_new: int = 3,
    *,
    project: str | None = None,
) -> bool:
    """Check if there are enough unreflected entries to justify reflection."""
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
    count = conn.execute(query, params).fetchone()[0]
    return count >= min_new


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
    """
    Get entries that haven't been reflected on yet.

    Uses watermark (last reflected ID) for idempotency.
    If no watermark exists and days is provided, uses days as a bootstrap window.

    Returns tuples of (id, content, entry_type, importance, created_at).
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
    """Get the timestamp of the most recent insight entry.

    Deprecated: replaced by get_watermark(). Kept for backward compat.
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

    Deprecated: replaced by check_novelty_gate_v2(). Kept for backward compat.
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
    """Check whether there are enough new observations to justify reflection.

    Deprecated: replaced by check_novelty_gate_v2(). Kept for backward compat.
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
    """Get memory entries from the last N days.

    Deprecated: replaced by get_unreflected_entries(). Kept for backward compat.
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
    """
    Read JSONL observation files from the last N days.

    Parses extraction dicts and formats them into readable text
    for the reflection prompt.
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
    """Format an extraction dict into readable text lines."""
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
    """Format DB entries into text for the reflection prompt.

    Accepts both 4-tuples (legacy: content, type, importance, created_at)
    and 5-tuples (new: id, content, type, importance, created_at).
    """
    lines = []
    for entry in entries:
        if len(entry) == 5:
            _, content, entry_type, importance, created_at = entry
        else:
            content, entry_type, importance, created_at = entry
        lines.append(
            f"- [{created_at[:10]}] ({entry_type}, imp={importance}) {content[:200]}"
        )
    return "\n".join(lines)


def parse_reflection_response(response: str) -> dict:
    """
    Parse the LLM response into insights and memory update proposals.

    Returns:
        {"insights": [...], "memory_updates": [...]}
    """
    insights = []
    memory_updates = []

    for line in response.strip().split("\n"):
        line = line.strip()
        if line.startswith("INSIGHT:"):
            text = line[8:].strip()
            if text:
                insights.append(text)
        elif line.startswith("MEMORY_UPDATE:"):
            text = line[14:].strip()
            if text:
                memory_updates.append(text)

    return {"insights": insights, "memory_updates": memory_updates}


def store_insights(
    conn: sqlite3.Connection,
    insights: list[str],
    *,
    project: str | None = None,
) -> int:
    """Store insights in memory database with fixed importance=6."""
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
    """Read the current MEMORY.md content, or None if it doesn't exist."""
    memory_md = get_data_dir() / "memory" / "MEMORY.md"
    if memory_md.exists():
        return memory_md.read_text()
    return None


def generate_memory_diff(memory_updates: list[str]) -> str:
    """Format proposed MEMORY.md additions as a readable diff."""
    lines = ["Proposed additions to MEMORY.md:", ""]
    for update in memory_updates:
        lines.append(f"+ {update}")
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
    """
    Main reflection orchestrator.

    Uses a watermark to track which entries have been reflected on,
    ensuring idempotent operation. Processes entries in batches.

    When project is provided, reflects only on global + project-scoped entries.

    Returns:
        {
            "skipped": bool,
            "reason": str | None,
            "insights": list[str],
            "stored": int,
            "memory_diff": str | None,
            "batch_info": {"processed": int, "watermark": int} | None,
        }
    """
    # Novelty gate (watermark-based)
    if not check_novelty_gate_v2(conn, min_new, project=project):
        return {
            "skipped": True,
            "reason": "not enough new observations since last reflection",
            "insights": [],
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
        model="haiku",
        timeout=60,
    )

    if not response:
        return {
            "skipped": False,
            "reason": "LLM call failed",
            "insights": [],
            "stored": 0,
            "memory_diff": None,
            "batch_info": None,
        }

    # Parse response
    parsed = parse_reflection_response(response)
    insights = parsed["insights"]
    memory_updates = parsed["memory_updates"]

    # Store insights
    stored = store_insights(conn, insights, project=project) if insights else 0

    # Update watermark to highest entry ID processed
    new_watermark = max(e[0] for e in entries)
    update_watermark(conn, new_watermark, project=project)

    # Generate memory diff
    memory_diff = None
    if memory_updates:
        memory_diff = generate_memory_diff(memory_updates)

    return {
        "skipped": False,
        "reason": None,
        "insights": insights,
        "stored": stored,
        "memory_diff": memory_diff,
        "batch_info": {"processed": len(entries), "watermark": new_watermark},
    }
