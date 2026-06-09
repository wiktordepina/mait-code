"""Session start hook — injects companion context at the beginning of each session."""

import json
import sys

from mait_code.hooks.session_start.context import build_session_context
from mait_code.logging import log_invocation, setup_logging


@log_invocation(name="mc-hook-session-start")
def main():
    """Read session start event from stdin and output companion context."""
    setup_logging()
    _event = json.loads(sys.stdin.read())

    context = build_session_context()
    if context:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(result))
