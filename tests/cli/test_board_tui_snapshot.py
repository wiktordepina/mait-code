"""Snapshot test locking the board TUI's visual output (A1 retrofit).

Renders a seeded board at a fixed terminal size and compares it against an
accepted SVG baseline under ``__snapshots__/``. The seed is fixed so card
ordering never drifts; the theme is the ``mait-dark`` default applied by
:class:`~mait_code.tui.app.MaitApp`.

Regenerate the baseline intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_board_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

from mait_code.cli._board_tui import BoardApp
from mait_code.tools.board import service
from mait_code.tools.board.db import get_connection


def _seed_demo(db_path: Path) -> None:
    """A small board spanning every column, with a blocked card, for the shot."""
    conn = get_connection(db_path)
    try:
        service.add_card(
            conn, project="demo", title="Wire up the widget", priority="high"
        )
        rid = service.add_card(
            conn, project="demo", title="Refine the spec", priority="medium"
        )
        service.move_card(conn, rid, "refined")
        bid = service.add_card(
            conn, project="demo", title="Awaiting review", priority="low"
        )
        service.move_card(conn, bid, "in_progress")
        service.block_card(conn, bid)
        did = service.add_card(
            conn, project="demo", title="Ship the thing", priority="medium"
        )
        service.move_card(conn, did, "done")
    finally:
        conn.close()


def test_board_snapshot(snap_compare, tmp_path: Path) -> None:
    db_path = tmp_path / "board.db"
    _seed_demo(db_path)
    assert snap_compare(BoardApp(db_path=db_path), terminal_size=(120, 40))


def test_help_screen_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the shared help screen's rendered look (keys + descriptions)."""
    db_path = tmp_path / "board.db"
    _seed_demo(db_path)
    assert snap_compare(
        BoardApp(db_path=db_path),
        press=["question_mark"],
        terminal_size=(120, 40),
    )
