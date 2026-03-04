"""MCP server for memory search and storage."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("mait-memory")


@server.tool()
def search_memory(query: str) -> str:
    """Search memory for past facts, decisions, and patterns."""
    return f"Memory search not yet implemented. Query: {query}"


@server.tool()
def store_memory(content: str, category: str = "general") -> str:
    """Store a new memory observation."""
    return f"Memory storage not yet implemented. Category: {category}"


def main():
    """Start the memory MCP server."""
    server.run()
