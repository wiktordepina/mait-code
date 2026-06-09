"""Build the session-start companion context.

One builder, two consumers: the session-start hook injects the result as
``additionalContext`` at the top of every session, and the home TUI's system
prompt view renders the same text on demand — so what the user inspects is
exactly what Claude is shown.

Each section reads its tool's store layer directly (no subprocess hops) and
is best-effort: a broken or missing store yields an empty section, never an
exception — session start must not be able to fail from here.
"""

from __future__ import annotations

import logging

__all__ = [
    "board_section",
    "build_session_context",
    "inbox_section",
    "reminders_section",
]

logger = logging.getLogger(__name__)


def reminders_section() -> str:
    """Overdue reminders, formatted like ``mc-tool-reminders check``.

    Returns "" when nothing is overdue, so the context stays silent.
    """
    from mait_code.tools.reminders.db import get_connection
    from mait_code.tools.reminders.service import overdue_reminders

    conn = get_connection()
    try:
        overdue = overdue_reminders(conn)
    finally:
        conn.close()

    if not overdue:
        return ""

    lines = [f"You have {len(overdue)} overdue reminder(s):", ""]
    lines += [
        f"  [#{r['id']}] {r['due'].strftime('%Y-%m-%d %H:%M')} — {r['what']}"
        for r in overdue
    ]
    lines += ["", "Use `mc-tool-reminders dismiss <id>` to dismiss."]
    return "\n".join(lines)


def board_section() -> str:
    """A one-line summary of the current project's live board columns.

    Returns "" when the project has no actionable (non-done) cards, so the
    context stays silent when there's nothing to surface.
    """
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection, get_project

    conn = get_connection()
    try:
        counts = service.summary_counts(conn, project=get_project())
    finally:
        conn.close()

    # Done cards aren't actionable at session start; surface the live columns.
    live = [(status, n) for status, n in counts.items() if status != "done" and n]
    if not live:
        return ""

    return " · ".join(f"{n} {status.replace('_', ' ')}" for status, n in live)


def inbox_section() -> str:
    """The quick-capture inbox count as a compact label.

    Returns ``"N inbox"`` when there are captured items waiting to be triaged,
    or "" when the inbox is empty — so the context stays silent when there's
    nothing to sort.
    """
    from mait_code.tools.inbox import service
    from mait_code.tools.inbox.db import get_connection

    conn = get_connection()
    try:
        count = service.count_items(conn)
    finally:
        conn.close()

    return f"{count} inbox" if count else ""


def build_session_context() -> str:
    """Assemble the full session-start context markdown.

    Returns "" when every section is silent — the hook then emits nothing,
    keeping quiet sessions quiet.
    """
    parts: list[tuple[str, str]] = []
    for title, builder in (
        ("Reminders", reminders_section),
        ("Board", board_section),
        ("Inbox", inbox_section),
    ):
        try:
            body = builder()
        except Exception:
            logger.exception("session context: %s section failed", title.lower())
            body = ""
        if body:
            parts.append((title, body))

    if not parts:
        return ""

    sections = [f"## {title}\n\n{body}" for title, body in parts]
    return "# Session Context\n\n" + "\n\n".join(sections) + "\n"
