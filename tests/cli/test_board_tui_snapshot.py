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
    """A small board spanning every column, with a blocked card, for the shot.

    Note: the Done column is hidden by default, so the ``did`` card below does
    not appear in the board snapshot — that's intended, not a missing card.
    """
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


def _seed_detail(db_path: Path) -> None:
    """A content-rich card (long title, sections, tags, comments) for the modal.

    Comments are inserted with fixed timestamps so the snapshot is stable.
    """
    conn = get_connection(db_path)
    try:
        cid = service.add_card(
            conn,
            project="mait-code",
            title="Replace the blocked column with a tags system in the board TUI",
            priority="high",
        )
        service.move_card(conn, cid, "refined")
        service.edit_card(
            conn,
            cid,
            description=(
                "Drop blocked as a board column and introduce a general "
                "free-form tag system."
            ),
            acceptance_criteria="- tag/untag verbs\n- a TUI toggle\n- render on rows",
        )
        service.add_tag(conn, cid, "tui")
        for author, body, ts in (
            (
                "claude",
                "Research complete; recommends staying on Textual.",
                "2026-05-30T09:00:00+00:00",
            ),
            ("me", "Agreed — let's lock the approach.", "2026-05-30T10:30:00+00:00"),
        ):
            conn.execute(
                "INSERT INTO card_comments (card_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (cid, author, body, ts),
            )
        conn.commit()
    finally:
        conn.close()


def test_detail_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the redesigned card-detail modal (wrap, sections, comment blocks)."""
    db_path = tmp_path / "board.db"
    _seed_detail(db_path)

    async def run_before(pilot) -> None:
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )
