"""Tests for ``mait-code home`` routing and the bare-invocation behaviour.

The TUI itself is covered in ``test_home_tui.py``; here we only check the
routing — a non-TTY invocation (which is what ``CliRunner`` provides) prints
the compact text summary, and bare ``mait-code`` off a TTY still prints help.
"""

from __future__ import annotations

from typer.testing import CliRunner

from mait_code.cli import app

runner = CliRunner()


def test_home_non_tty_prints_text_summary() -> None:
    result = runner.invoke(app, ["home"])
    assert result.exit_code == 0
    assert "Board:" in result.output
    assert "Reminders: 0 overdue · 0 upcoming" in result.output
    assert "Inbox: 0" in result.output
    assert "Memory: 0 entries" in result.output


def test_home_non_tty_reflects_seeded_stores() -> None:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection

    conn = get_connection()
    try:
        service.add_card(conn, project="demo", title="A card")
    finally:
        conn.close()

    result = runner.invoke(app, ["home"])
    assert result.exit_code == 0
    assert "demo: 1 backlog" in result.output


def test_bare_invocation_off_tty_prints_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.output
    assert "home" in result.output  # the new command is listed


def test_home_loop_relaunches_until_quit(monkeypatch) -> None:
    """The loop opens each chosen sibling TUI, re-entering home between them,
    and stops when home returns None (the user quit)."""
    import mait_code.cli as cli
    from mait_code.cli._home_tui import HomeTarget

    # Home is opened three times: board, then settings, then quit.
    targets = iter([HomeTarget.BOARD, HomeTarget.SETTINGS, None])
    launched: list[str] = []

    monkeypatch.setattr("mait_code.cli._home_tui.run_home_tui", lambda: next(targets))
    monkeypatch.setattr(
        "mait_code.cli._board_tui.run_board_tui",
        lambda: launched.append("board"),
    )
    monkeypatch.setattr(
        "mait_code.cli._settings_tui.run_interactive_editor",
        lambda: launched.append("settings"),
    )

    cli._run_home_loop()

    assert launched == ["board", "settings"]
