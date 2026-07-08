"""Session start hook — injects companion context at the beginning of each session."""

import json
import logging
import sys

from mait_code.hooks.session_start.context import build_session_context
from mait_code.logging import log_invocation, setup_logging

logger = logging.getLogger(__name__)


def _drain_bridge() -> None:
    """Drain the Bridge into the inbox, and publish due reminders outward.

    Both are no-ops unless the Bridge gate is on (each short-circuits before any
    network access). Best-effort: a transport hiccup must never break session
    start. Drain first so any "Done" dismissals land before we re-notify.
    """
    try:
        from mait_code.bridge.service import publish_due_reminders, run_drain

        run_drain()
        publish_due_reminders()
    except Exception:
        logger.exception("session start: bridge sync failed")


@log_invocation(name="mc-hook-session-start")
def main():
    """Read session start event from stdin and output companion context."""
    setup_logging()
    _event = json.loads(sys.stdin.read())

    _drain_bridge()

    context = build_session_context()
    if context:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(result))
