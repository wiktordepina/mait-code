"""MCP server for reminders."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("mait-reminders")


@server.tool()
def set_reminder(when: str, what: str) -> str:
    """Set a reminder for a future time."""
    return f"Reminders not yet implemented. When: {when}, What: {what}"


@server.tool()
def list_reminders() -> str:
    """List active and overdue reminders."""
    return "Reminders not yet implemented."


def main():
    """Start the reminders MCP server."""
    server.run()
