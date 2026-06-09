"""Session-start hook — greet the user and surface overdue reminders.

Runs at the beginning of every Claude Code session. Builds the companion
context (overdue reminders, board summary, inbox count) from each tool's
store layer and prints it as additional context for the system prompt.
The builder lives in :mod:`~mait_code.hooks.session_start.context` and is
shared with the home TUI's system prompt view.
"""

from mait_code.hooks.session_start.cli import main
from mait_code.hooks.session_start.context import (
    board_section,
    build_session_context,
    inbox_section,
    reminders_section,
)

__all__ = [
    # CLI
    "main",
    # Context builder
    "board_section",
    "build_session_context",
    "inbox_section",
    "reminders_section",
]
