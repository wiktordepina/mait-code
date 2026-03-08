"""Session start hook — injects companion context at the beginning of each session."""

import json
import subprocess
import sys


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
    except FileNotFoundError, subprocess.TimeoutExpired:
        return ""


def main():
    """Read session start event from stdin and output companion context."""
    _event = json.loads(sys.stdin.read())

    parts = [
        "# Session Context\n",
        "Mait Code companion loaded. Memory and identity systems not yet implemented.",
    ]

    reminders = _check_reminders()
    if reminders:
        parts.append(f"\n## Reminders\n\n{reminders}")

    context = "\n".join(parts) + "\n"

    result = {"hookSpecificOutput": {"context": context}}
    print(json.dumps(result))
