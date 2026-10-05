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


def _sync_session_bindings(event: dict) -> None:
    """Keep board card ↔ session bindings pointing at this session.

    A ``resume`` keeps its session id under a new Claude Code process, so its
    bindings take the new pid. A ``/clear`` keeps the process under a new id,
    so the process's bindings move to that id. Best-effort: a board problem
    must never break session start.
    """
    source = event.get("source")
    session_id = event.get("session_id")
    if source not in ("resume", "clear") or not session_id:
        return
    try:
        from mait_code.tools.board import service
        from mait_code.tools.board.db import connection
        from mait_code.tools.board.sessions import current_pid

        pid = current_pid()
        if pid is None:
            return
        with connection() as conn:
            if source == "resume":
                service.refresh_session_pid(conn, session_id, pid)
            else:
                service.rebind_pid(conn, pid, session_id)
    except Exception:
        logger.exception("session start: card binding sync failed")


@log_invocation(name="mc-hook-session-start")
def main():
    """Read session start event from stdin and output companion context."""
    setup_logging()
    event = json.loads(sys.stdin.read())

    _drain_bridge()
    _sync_session_bindings(event)

    context = build_session_context(session_id=event.get("session_id"))
    if context:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(result))
