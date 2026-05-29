"""Tests for the Textual ``mait-code board`` TUI.

Driven by Textual's headless pilot (``App.run_test()`` wrapped in
``asyncio.run`` — no pytest-asyncio), mirroring ``test_settings_tui.py``. The
app takes a ``db_path`` so each scenario points at an isolated temp board; the
shared service layer is covered directly in ``test_service.py``, so here we
only check the TUI wiring on top of it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Input, Label, Static

from mait_code.cli._board_tui import BoardApp, CommentScreen, DetailScreen
from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED,
    DONE,
    IN_PROGRESS,
    REFINED,
)
from mait_code.tools.board.db import get_connection


def _run(coro_factory):
    return asyncio.run(coro_factory())


@pytest.fixture
def board_path(tmp_path: Path) -> Path:
    """An empty temp board database path."""
    return tmp_path / "board.db"


def _seed(db_path: Path, cards: list[dict]) -> dict[str, int]:
    """Create cards (each a dict of overrides) and return title→id."""
    conn = get_connection(db_path)
    ids: dict[str, int] = {}
    try:
        for spec in cards:
            cid = service.add_card(
                conn,
                project=spec.get("project", "demo"),
                title=spec["title"],
                priority=spec.get("priority", "medium"),
            )
            status = spec.get("status", BACKLOG)
            if status != BACKLOG:
                service.move_card(conn, cid, status)
            ids[spec["title"]] = cid
    finally:
        conn.close()
    return ids


class TestBoot:
    def test_renders_columns_with_counts(self, board_path: Path) -> None:
        _seed(
            board_path,
            [
                {"title": "a", "status": BACKLOG},
                {"title": "b", "status": REFINED},
                {"title": "c", "status": REFINED},
            ],
        )

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                backlog = str(app.query_one("#head-backlog", Label).render())
                refined = str(app.query_one("#head-refined", Label).render())
                return backlog, refined

        backlog, refined = _run(scenario)
        assert "(1)" in backlog
        assert "(2)" in refined

    def test_archived_pane_hidden_by_default(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "old", "status": ARCHIVED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                from textual.containers import Vertical

                return app.query_one("#col-archived", Vertical).display

        assert _run(scenario) is False

    def test_empty_board_boots(self, board_path: Path) -> None:
        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                return app.query_one("#head-backlog", Label).render()

        assert "(0)" in str(_run(scenario))


class TestMoving:
    def test_move_right_advances_and_follows(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("greater_than_sign")
                await pilot.pause()
                status = service.get_card(app._conn, ids["card"])["status"]
                # Cursor followed the card into the in_progress pane.
                followed = app._visible_statuses()[app._focused_col]
                return status, followed

        status, followed = _run(scenario)
        assert status == IN_PROGRESS
        assert followed == IN_PROGRESS

    def test_move_left_retreats(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": IN_PROGRESS}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(IN_PROGRESS)
                await pilot.press("less_than_sign")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])["status"]

        assert _run(scenario) == REFINED

    def test_move_past_end_is_noop(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": DONE}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(DONE)
                await pilot.press("greater_than_sign")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])["status"]

        assert _run(scenario) == DONE

    def test_move_to_done_sets_completed_at(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": IN_PROGRESS}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(IN_PROGRESS)
                await pilot.press("greater_than_sign")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])

        card = _run(scenario)
        assert card["status"] == DONE
        assert card["completed_at"] is not None


class TestBlocking:
    def test_block_moves_to_blocked_pane(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("b")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])["status"]

        assert _run(scenario) == BLOCKED

    def test_blocked_card_not_on_move_line(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": BLOCKED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(BLOCKED)
                await pilot.press("greater_than_sign")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])["status"]

        # A blocked card is a side-state: > does not move it.
        assert _run(scenario) == BLOCKED

    def test_unblock_returns_to_refined(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": BLOCKED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(BLOCKED)
                await pilot.press("u")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])["status"]

        assert _run(scenario) == REFINED


class TestProjectFilter:
    def test_cycle_filters_to_one_project(self, board_path: Path) -> None:
        _seed(
            board_path,
            [
                {"title": "a", "status": REFINED, "project": "alpha"},
                {"title": "b", "status": REFINED, "project": "beta"},
            ],
        )

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                # all projects → both refined cards visible
                before = app.query_one("#tbl-refined").row_count
                await pilot.press("p")  # → first project (alpha, sorted)
                await pilot.pause()
                after = app.query_one("#tbl-refined").row_count
                return before, after, app._project_filter

        before, after, filt = _run(scenario)
        assert before == 2
        assert after == 1
        assert filt == "alpha"


class TestArchivedToggle:
    def test_toggle_reveals_archived(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "old", "status": ARCHIVED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                from textual.containers import Vertical

                shown = app.query_one("#col-archived", Vertical).display
                count = app.query_one("#tbl-archived").row_count
                return shown, count

        shown, count = _run(scenario)
        assert shown is True
        assert count == 1


class TestComment:
    def test_comment_modal_writes_a_row(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("c")
                await pilot.pause()
                assert isinstance(app.screen, CommentScreen)
                app.screen.query_one("#comment-input", Input).value = "looks good"
                await pilot.click("#comment-add")
                await pilot.pause()
                await pilot.pause()
                return service.get_comments(app._conn, ids["card"])

        comments = _run(scenario)
        assert [c["body"] for c in comments] == ["looks good"]

    def test_comment_cancel_writes_nothing(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("c")
                await pilot.pause()
                app.screen.query_one("#comment-input", Input).value = "nope"
                await pilot.click("#comment-cancel")
                await pilot.pause()
                return service.get_comments(app._conn, ids["card"])

        assert _run(scenario) == []


class TestDetail:
    def test_detail_renders_comment_thread(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])
        conn = get_connection(board_path)
        service.add_comment(conn, ids["card"], "first note", author="claude")
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, DetailScreen)
                rendered = " ".join(str(s.render()) for s in app.screen.query(Static))
                return rendered

        rendered = _run(scenario)
        assert "first note" in rendered
        assert "claude" in rendered


class TestLayout:
    """Guards against the panes rendering at zero height (cards invisible)."""

    def test_panes_have_nonzero_height(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "card", "status": BACKLOG}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                from textual.containers import Vertical

                return app.query_one("#col-backlog", Vertical).size.height

        # Before the CSS height fix this was 0, so no card ever painted.
        assert _run(scenario) > 0

    def test_card_text_is_rendered(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "Find me", "status": BACKLOG}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                # Join the compositor's rendered line strips — a real paint of
                # the live screen, so a zero-height/blank column would not
                # contain the card text.
                strips = app.screen._compositor.render_strips()
                painted = "\n".join(
                    "".join(seg.text for seg in strip) for strip in strips
                )
                return "Find me" in painted

        assert _run(scenario) is True
