"""Session start hook — injects companion context at the beginning of each session."""

import json
import logging
import sys

from mait_code.hooks.session_start.context import build_session_context
from mait_code.logging import log_invocation, setup_logging

logger = logging.getLogger(__name__)


def _drain_bridge() -> None:
    """Drain the Bridge into the inbox before the context counts it.

    A no-op unless the Bridge gate is on (:func:`run_drain` short-circuits
    before any network access). Best-effort: a transport hiccup must never
    break session start.
    """
    try:
        from mait_code.bridge.service import run_drain

        run_drain()
    except Exception:
        logger.exception("session start: bridge drain failed")


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
