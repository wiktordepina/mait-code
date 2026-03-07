"""Session start hook — injects companion context at the beginning of each session."""

import json
import sys


def main():
    """Read session start event from stdin and output companion context."""
    _event = json.loads(sys.stdin.read())

    # Placeholder: will inject soul document, user context, and recent memories
    context = (
        "# Session Context\n\n"
        "Mait Code companion loaded. Memory and identity systems not yet implemented.\n"
    )

    result = {"hookSpecificOutput": {"context": context}}
    print(json.dumps(result))
