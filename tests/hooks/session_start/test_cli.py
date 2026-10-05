"""Tests for the session-start hook — section builders and context assembly.

The builders read each tool's store layer directly, so these tests seed real
temp databases (the root conftest points ``MAIT_CODE_DATA_DIR`` at ``tmp_path``)
rather than faking subprocess seams.
"""

import io
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

import mait_code.hooks.session_start.context as ctx_mod
from mait_code.hooks.session_start.cli import main
from mait_code.hooks.session_start.context import (
    board_section,
    build_session_context,
    inbox_section,
    reminders_section,
    session_section,
)


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Restore the mait_code logger's handlers after each test.

    Calling ``main()`` runs the ``@log_invocation`` decorator, which invokes
    ``setup_logging()`` and adds a file handler to the global ``mait_code``
    logger. Without this, that handler leaks into ``tests/test_logging.py``.
    """
    logger = logging.getLogger("mait_code")
    original = logger.handlers[:]
    yield
    for handler in logger.handlers[:]:
        if handler not in original:
            logger.removeHandler(handler)
    logger.handlers = original


@pytest.fixture
def project(monkeypatch):
    """Pin the board's project detection to a known name."""
    monkeypatch.setattr("mait_code.tools.board.db.get_project", lambda: "p")
    return "p"


def _seed_reminder(what: str, *, overdue: bool) -> None:
    from mait_code.tools.reminders.db import get_connection

    due = datetime.now(timezone.utc) + timedelta(hours=-1 if overdue else 1)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
            (what, due.isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_card(project: str, status: str | None = None) -> None:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection

    conn = get_connection()
    try:
        card_id = service.add_card(conn, project=project, title="t")
        if status is not None:
            service.move_card(conn, card_id, status)
    finally:
        conn.close()


# --- reminders_section ---


def test_reminders_section_lists_overdue():
    _seed_reminder("walk Cody", overdue=True)
    _seed_reminder("future thing", overdue=False)

    out = reminders_section()
    assert "You have 1 overdue reminder(s):" in out
    assert "walk Cody" in out
    assert "future thing" not in out
    assert "dismiss" in out


def test_reminders_section_silent_when_none_overdue():
    _seed_reminder("future thing", overdue=False)
    assert reminders_section() == ""


# --- board_section ---


def test_board_section_summarises_live_columns(project):
    _seed_card(project)
    _seed_card(project, "refined")
    _seed_card(project, "in_progress")
    _seed_card(project, "done")

    out = board_section()
    assert out == "1 backlog · 1 refined · 1 in progress"
    assert "done" not in out  # done is not actionable at session start


def test_board_section_empty_when_only_done(project):
    _seed_card(project, "done")
    assert board_section() == ""


def test_board_section_empty_when_no_cards(project):
    assert board_section() == ""


def test_board_section_scoped_to_current_project(project):
    _seed_card("other-project")
    assert board_section() == ""


# --- inbox_section ---


def test_inbox_section_counts_items():
    from mait_code.tools.inbox import service
    from mait_code.tools.inbox.db import get_connection

    conn = get_connection()
    try:
        service.add_item(conn, body="captured thought")
    finally:
        conn.close()

    assert inbox_section() == "1 inbox"


def test_inbox_section_silent_when_empty():
    assert inbox_section() == ""


# --- build_session_context ---


def test_build_session_context_assembles_sections(project):
    _seed_reminder("walk Cody", overdue=True)
    _seed_card(project, "refined")

    context = build_session_context()
    assert context.startswith("# Session Context\n")
    assert "## Reminders" in context
    assert "## Board" in context
    assert "## Inbox" not in context  # empty sections stay silent


def test_build_session_context_empty_when_all_silent(project):
    assert build_session_context() == ""


def test_build_session_context_survives_a_broken_section(monkeypatch, project):
    def boom():
        raise RuntimeError("store on fire")

    monkeypatch.setattr(ctx_mod, "reminders_section", boom)
    _seed_card(project, "refined")

    context = build_session_context()
    assert "## Board" in context
    assert "## Reminders" not in context


# --- main() integration ---


def test_main_includes_board_section(monkeypatch, capsys, project):
    _seed_card(project, "refined")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    main()

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "## Board" in context
    assert "1 refined" in context


def test_main_silent_when_nothing(monkeypatch, capsys, project):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    main()

    assert capsys.readouterr().out == ""


# --- card ↔ session bindings ---


def _bound_card(title: str, session_id: str, pid: int) -> int:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import connection
    from mait_code.tools.board.sessions import SessionRef

    with connection() as conn:
        cid = service.add_card(conn, project="p", title=title)
        service.move_card(conn, cid, "in_progress")
        service.bind_session(conn, cid, SessionRef(session_id, pid))
    return cid


def _bindings() -> list[tuple]:
    from mait_code.tools.board.db import connection

    with connection() as conn:
        return conn.execute(
            "SELECT card_id, session_id, pid FROM card_sessions ORDER BY card_id"
        ).fetchall()


def _start(monkeypatch, source: str, session_id: str, *, pid: int | None) -> None:
    if pid is None:
        monkeypatch.delenv("CLAUDE_PID", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PID", str(pid))
    event = {"session_id": session_id, "source": source}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    main()


def test_session_section_names_bound_cards(project):
    import os

    cid = _bound_card("Bind board cards", "s1", os.getpid())
    _bound_card("Someone else's", "s2", os.getpid())
    assert (
        session_section("s1") == f"This session is working on #{cid} — Bind board cards"
    )
    assert session_section("nobody") == ""


def test_build_session_context_adds_the_session_section(project):
    import os

    _bound_card("Bound card", "s1", os.getpid())
    context = build_session_context(session_id="s1")
    assert context.index("## Session") < context.index("## Board")
    assert "working on #" in context
    # The home TUI's preview has no session: no section.
    assert "## Session" not in build_session_context()


def test_resume_moves_bindings_to_the_new_process(monkeypatch, capsys, project):
    import os
    import subprocess
    import sys

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    cid = _bound_card("Resumed card", "kept-id", proc.pid)

    _start(monkeypatch, "resume", "kept-id", pid=os.getpid())

    assert _bindings() == [(cid, "kept-id", os.getpid())]
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert f"working on #{cid}" in context["additionalContext"]


def test_clear_moves_this_process_bindings_to_the_new_id(monkeypatch, capsys, project):
    import os

    cid = _bound_card("Cleared card", "old-id", os.getpid())

    _start(monkeypatch, "clear", "new-id", pid=os.getpid())

    assert _bindings() == [(cid, "new-id", os.getpid())]
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert f"working on #{cid}" in context["additionalContext"]


@pytest.mark.parametrize("source", ["startup", "compact"])
def test_other_sources_leave_bindings_alone(monkeypatch, project, source):
    import os

    cid = _bound_card("Card", "old-id", os.getpid())
    _start(monkeypatch, source, "new-id", pid=os.getpid())
    assert _bindings() == [(cid, "old-id", os.getpid())]


def test_binding_sync_needs_claude_pid(monkeypatch, project):
    import os

    cid = _bound_card("Card", "old-id", os.getpid())
    _start(monkeypatch, "clear", "new-id", pid=None)
    assert _bindings() == [(cid, "old-id", os.getpid())]


def test_binding_sync_failure_never_breaks_session_start(monkeypatch, capsys, project):
    from mait_code.tools.board import service

    def boom(*_args, **_kwargs):
        raise RuntimeError("board on fire")

    monkeypatch.setattr(service, "rebind_pid", boom)
    _seed_card(project, "refined")
    _start(monkeypatch, "clear", "new-id", pid=12345)
    out = json.loads(capsys.readouterr().out)
    assert "## Board" in out["hookSpecificOutput"]["additionalContext"]
