"""Snapshot tests for the board's Initiatives view and relationship surfaces.

Same harness as ``test_board_tui_snapshot.py``: a fixed seed rendered at a
fixed terminal size against accepted SVG baselines. Regenerate intentionally
(and eyeball the diff) with::

    uv run pytest tests/cli/test_initiatives_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mait_code.tui.banner as banner_mod
from mait_code.cli._board_tui import INITIATIVES, BoardApp
from mait_code.tools.board import service
from mait_code.tools.board.db import get_connection


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def _seed(db_path: Path) -> dict[str, int]:
    """Two epics across three projects: ready, waiting, tagged, in flight, done."""
    conn = get_connection(db_path)
    try:
        voice = service.add_card(
            conn, project=None, title="Voice and agent integration", kind="epic"
        )
        service.add_card(conn, project=None, title="Workstation [VM 218]", kind="epic")

        def card(title, project, status=None, **kw):
            cid = service.add_card(
                conn, project=project, title=title, parent_id=voice, **kw
            )
            if status:
                service.move_card(conn, cid, status)
            return cid

        wake = card("Wake-word daemon", "homelab", "refined", priority="high")
        router = card("Intent router", "homelab")
        companion = card("Companion voice", "maitre-d", "in_progress")
        spike = card("Mic array spike", "homelab", "done")
        tagged = card("Tagged thing", "mait-code", "refined")
        service.block_card(conn, tagged)
        service.add_link(conn, wake, router)
        service.add_link(conn, router, companion)
        service.add_link(conn, spike, wake)
        return {"voice": voice, "router": router, "companion": companion}
    finally:
        conn.close()


def test_initiatives_snapshot(snap_compare, tmp_path: Path) -> None:
    db_path = tmp_path / "board.db"
    _seed(db_path)
    assert snap_compare(
        BoardApp(db_path=db_path, initial_view=INITIATIVES), terminal_size=(130, 40)
    )


def test_initiatives_ready_only_snapshot(snap_compare, tmp_path: Path) -> None:
    db_path = tmp_path / "board.db"
    _seed(db_path)
    assert snap_compare(
        BoardApp(db_path=db_path, initial_view=INITIATIVES),
        press=["R"],
        terminal_size=(130, 40),
    )


def test_initiatives_empty_snapshot(snap_compare, tmp_path: Path) -> None:
    assert snap_compare(
        BoardApp(db_path=tmp_path / "board.db", initial_view=INITIATIVES),
        terminal_size=(130, 40),
    )


def test_card_relationships_snapshot(snap_compare, tmp_path: Path) -> None:
    """The card screen's Epic / Blocked by / Unblocks rows (#4 Intent router:
    waiting on #3, unblocks #5)."""
    db_path = tmp_path / "board.db"
    ids = _seed(db_path)

    async def run_before(pilot) -> None:
        pilot.app.run_worker(pilot.app.open_card(ids["router"]))
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path), run_before=run_before, terminal_size=(130, 40)
    )


def test_kanban_waiting_marker_snapshot(snap_compare, tmp_path: Path) -> None:
    """Waiting cards carry the blocked border and a ``waiting on #N`` line."""
    db_path = tmp_path / "board.db"
    _seed(db_path)
    assert snap_compare(BoardApp(db_path=db_path), terminal_size=(130, 40))
