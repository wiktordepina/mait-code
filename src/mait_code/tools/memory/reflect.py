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


def get_last_reflection_date(conn: sqlite3.Connection) -> datetime | None:
    """Get the timestamp of the most recent insight entry."""
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
) -> int:
    """Count non-insight memory entries added since a given timestamp."""
    if exclude_types:
        placeholders = ", ".join("?" for _ in exclude_types)
        query = f"""SELECT COUNT(*) FROM memory_entries
                    WHERE created_at >= ? AND entry_type NOT IN ({placeholders})"""
        params = (since.strftime("%Y-%m-%d %H:%M:%S"), *exclude_types)
    else:
        query = "SELECT COUNT(*) FROM memory_entries WHERE created_at >= ?"
        params = (since.strftime("%Y-%m-%d %H:%M:%S"),)

    return conn.execute(query, params).fetchone()[0]


def check_novelty_gate(conn: sqlite3.Connection, min_new: int = 3) -> bool:
    """
    Check whether there are enough new observations to justify reflection.

    Returns True if reflection should proceed, False to skip.
    """
    last_reflection = get_last_reflection_date(conn)
    if last_reflection is None:
        # Never reflected before — always proceed
        return True

    new_count = count_entries_since(conn, last_reflection)
    return new_count >= min_new


def get_recent_entries(
    conn: sqlite3.Connection,
    days: int = 7,
    limit: int = 200,
    exclude_types: tuple[str, ...] = ("insight",),
) -> list[tuple]:
    """
    Get memory entries from the last N days.

    Excludes insight entries by default to prevent feedback loops.
    """
    if exclude_types:
        placeholders = ", ".join("?" for _ in exclude_types)
        query = f"""SELECT content, entry_type, importance, created_at
                    FROM memory_entries
                    WHERE created_at >= datetime('now', ?)
                      AND entry_type NOT IN ({placeholders})
                    ORDER BY created_at DESC
                    LIMIT ?"""
        params = (f"-{days} days", *exclude_types, limit)
    else:
        query = """SELECT content, entry_type, importance, created_at
                   FROM memory_entries
                   WHERE created_at >= datetime('now', ?)
                   ORDER BY created_at DESC
                   LIMIT ?"""
        params = (f"-{days} days", limit)

    return conn.execute(query, params).fetchall()


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


def format_entries_text(entries: list[tuple]) -> str:
    """Format DB entries into text for the reflection prompt."""
    return "\n".join(
        f"- [{created_at[:10]}] ({entry_type}, imp={importance}) {content[:200]}"
        for content, entry_type, importance, created_at in entries
    )


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


def store_insights(conn: sqlite3.Connection, insights: list[str]) -> int:
    """Store insights in memory database with fixed importance=6."""
    stored = 0
    for insight in insights:
        store_memory(conn, insight, "insight", importance=6)
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


def reflect(
    conn: sqlite3.Connection,
    days: int = 7,
    min_new: int = 3,
) -> dict:
    """
    Main reflection orchestrator.

    Returns:
        {
            "skipped": bool,
            "reason": str | None,
            "insights": list[str],
            "stored": int,
            "memory_diff": str | None,
        }
    """
    # Novelty gate
    if not check_novelty_gate(conn, min_new):
        return {
            "skipped": True,
            "reason": "not enough new observations since last reflection",
            "insights": [],
            "stored": 0,
            "memory_diff": None,
        }

    # Gather data
    entries = get_recent_entries(conn, days)
    observations_text = read_observation_logs(days)

    if not entries and not observations_text:
        return {
            "skipped": True,
            "reason": "no data found for the given time period",
            "insights": [],
            "stored": 0,
            "memory_diff": None,
        }

    # Build prompt
    entries_text = format_entries_text(entries)

    prompt_parts = []
    if entries_text:
        prompt_parts.append(f"Recent memory entries ({days} days):\n{entries_text}")
    if observations_text:
        # Cap observation text to avoid exceeding context limits
        obs_capped = observations_text[:4000]
        prompt_parts.append(f"Recent observation logs:\n{obs_capped}")

    current_memory = read_memory_md()
    if current_memory:
        # Cap MEMORY.md content
        prompt_parts.append(
            f"Current MEMORY.md content:\n{current_memory[:2000]}"
        )

    prompt = "\n\n".join(prompt_parts)

    # Call LLM
    response = call_claude(
        prompt,
        system_prompt=REFLECTION_SYSTEM_PROMPT,
        model="haiku",
        max_tokens=1024,
        timeout=60,
    )

    if not response:
        return {
            "skipped": False,
            "reason": "LLM call failed",
            "insights": [],
            "stored": 0,
            "memory_diff": None,
        }

    # Parse response
    parsed = parse_reflection_response(response)
    insights = parsed["insights"]
    memory_updates = parsed["memory_updates"]

    # Store insights
    stored = store_insights(conn, insights) if insights else 0

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
    }
