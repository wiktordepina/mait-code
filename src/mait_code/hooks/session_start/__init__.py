"""Session-start hook — greet the user and surface overdue reminders.

Runs at the beginning of every Claude Code session. Reads overdue items from
the reminders database, formats a short greeting, and prints additional
context to surface in the system prompt.
"""

from mait_code.hooks.session_start.cli import main

__all__ = ["main"]
