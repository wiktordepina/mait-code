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


def _check_tasks() -> str:
    """Check for open project tasks via the CLI tool."""
    try:
        result = subprocess.run(
            ["mc-tool-tasks", "check"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


@log_invocation(name="mc-hook-session-start")
def main():
    """Read session start event from stdin and output companion context."""
    setup_logging()
    _event = json.loads(sys.stdin.read())

    sections = []

    reminders = _check_reminders()
    if reminders:
        sections.append(f"## Reminders\n\n{reminders}")

    tasks = _check_tasks()
    if tasks:
        sections.append(f"## Project Tasks\n\n{tasks}")

    if sections:
        context = "# Session Context\n\n" + "\n\n".join(sections) + "\n"
        result = {"hookSpecificOutput": {"context": context}}
        print(json.dumps(result))
