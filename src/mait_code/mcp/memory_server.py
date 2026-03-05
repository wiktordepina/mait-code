"""MCP server for memory search and storage."""

from mcp.server.fastmcp import FastMCP

from mait_code.memory.db import get_connection
from mait_code.memory.scoring import composite_score
from mait_code.memory.search import delete_entry, list_entries, search_entries
from mait_code.memory.writer import VALID_ENTRY_TYPES
from mait_code.memory.writer import store_memory as _store_memory

server = FastMCP("mait-memory")


@server.tool()
def search_memory(
    query: str,
    limit: int = 10,
    entry_type: str | None = None,
) -> str:
    """
    Search memory for past facts, decisions, patterns, and preferences.

    Results are ranked by a composite score combining recency, importance,
    and keyword relevance.

    Args:
        query: Natural language search query.
        limit: Maximum results (default 10).
        entry_type: Optional filter (fact, preference, event, insight, task, relationship).
    """
    conn = get_connection()
    try:
        results = search_entries(conn, query, limit=limit * 2, entry_type=entry_type)

        if not results:
            return f"No memories found matching '{query}'."

        scored = []
        for r in results:
            score = composite_score(
                r["created_at"],
                r["importance"],
                relevance=0.7,
                memory_class=r.get("memory_class"),
            )
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        lines = [f"Found {len(scored)} memories matching '{query}':\n"]
        for score, r in scored:
            lines.append(
                f"[#{r['id']}] ({r['entry_type']}, importance={r['importance']}, "
                f"score={score:.2f}) {r['created_at'][:10]}"
            )
            lines.append(f"  {r['content']}")
            lines.append("")

        return "\n".join(lines)
    finally:
        conn.close()


@server.tool()
def store_memory(
    content: str,
    entry_type: str = "fact",
    importance: int = 5,
) -> str:
    """
    Store a new memory observation. Automatically deduplicates near-identical content.

    Args:
        content: The memory content to store.
        entry_type: Type: fact, preference, event, insight, task, relationship.
        importance: Importance level 1-10 (default 5).
    """
    if not content.strip():
        return "Error: Content cannot be empty."

    if entry_type not in VALID_ENTRY_TYPES:
        return (
            f"Error: Invalid entry_type '{entry_type}'. "
            f"Valid types: {', '.join(sorted(VALID_ENTRY_TYPES))}"
        )

    conn = get_connection()
    try:
        result = _store_memory(conn, content.strip(), entry_type, importance)
        if result["action"] == "deduplicated":
            return (
                f"Memory deduplicated (updated entry #{result['id']}): {content[:80]}"
            )
        return (
            f"Memory stored (#{result['id']}): "
            f"[{entry_type}, importance={importance}] {content[:80]}"
        )
    finally:
        conn.close()


@server.tool()
def list_recent_memories(
    limit: int = 10,
    entry_type: str | None = None,
) -> str:
    """
    List the most recent memory entries.

    Args:
        limit: Maximum entries to return (default 10).
        entry_type: Optional filter by type.
    """
    conn = get_connection()
    try:
        results = list_entries(conn, limit=limit, entry_type=entry_type)
        if not results:
            return "No memories stored yet."

        lines = [f"Recent {len(results)} memories:\n"]
        for r in results:
            lines.append(
                f"[#{r['id']}] ({r['entry_type']}, importance={r['importance']}) "
                f"{r['created_at'][:10]}"
            )
            lines.append(f"  {r['content'][:120]}")
            lines.append("")

        return "\n".join(lines)
    finally:
        conn.close()


@server.tool()
def delete_memory(entry_id: int) -> str:
    """
    Delete a memory entry by its ID.

    Args:
        entry_id: The numeric ID of the memory to delete.
    """
    conn = get_connection()
    try:
        if delete_entry(conn, entry_id):
            return f"Memory #{entry_id} deleted."
        return f"Error: Memory #{entry_id} not found."
    finally:
        conn.close()


@server.tool()
def memory_stats() -> str:
    """Show statistics about stored memories."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        if total == 0:
            return "No memories stored yet."

        by_type = conn.execute(
            "SELECT entry_type, COUNT(*) FROM memory_entries "
            "GROUP BY entry_type ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_class = conn.execute(
            "SELECT memory_class, COUNT(*) FROM memory_entries GROUP BY memory_class"
        ).fetchall()

        lines = [f"Memory Statistics ({total} total entries)\n"]
        lines.append("By type:")
        for row in by_type:
            lines.append(f"  {row[0]}: {row[1]}")
        lines.append("\nBy class:")
        for row in by_class:
            lines.append(f"  {row[0]}: {row[1]}")

        return "\n".join(lines)
    finally:
        conn.close()


def main():
    """Start the memory MCP server."""
    server.run()
