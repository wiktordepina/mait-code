"""Session start hook — injects companion context at the beginning of each session."""

import json
import subprocess
import sys

from mait_code.logging import log_invocation, setup_logging


def _check_reminders() -> str:
    """Check for overdue reminders via the CLI tool."""
    try:
        result = subprocess.run(
            ["mc-tool-reminders", "check"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _check_board() -> str:
    """Summarise the current project's board via the CLI tool.

    Returns a compact one-line summary of the live (non-done) columns that
    have cards, or "" when the project has no actionable cards — so the
    session context stays silent when there's nothing to surface.
    """
    try:
        result = subprocess.run(
            ["mc-tool-board", "summary", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    try:
        counts = json.loads(result.stdout).get("counts", {})
    except (ValueError, AttributeError):
        return ""

    # Done cards aren't actionable at session start; surface the live columns.
    live = [(status, n) for status, n in counts.items() if status != "done" and n]
    if not live:
        return ""

    return " · ".join(f"{n} {status.replace('_', ' ')}" for status, n in live)


def _check_inbox() -> str:
    """Return the quick-capture inbox count as a compact label.

    Returns ``"N inbox"`` when there are captured items waiting to be triaged,
    or "" when the inbox is empty — so the session context stays silent when
    there's nothing to sort.
    """
    try:
        result = subprocess.run(
            ["mc-tool-inbox", "count"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    try:
        count = int(result.stdout.strip())
    except ValueError:
        return ""

    return f"{count} inbox" if count else ""


@log_invocation(name="mc-hook-session-start")
def main():
    """Read session start event from stdin and output companion context."""
    setup_logging()
    _event = json.loads(sys.stdin.read())

    sections = []

    reminders = _check_reminders()
    if reminders:
        sections.append(f"## Reminders\n\n{reminders}")

    board = _check_board()
    if board:
        sections.append(f"## Board\n\n{board}")

    inbox = _check_inbox()
    if inbox:
        sections.append(f"## Inbox\n\n{inbox}")

    if sections:
        context = "# Session Context\n\n" + "\n\n".join(sections) + "\n"
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(result))
