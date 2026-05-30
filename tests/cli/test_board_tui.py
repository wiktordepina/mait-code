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
from textual.widgets import Input, Label, Static, TextArea

from mait_code.cli._board_tui import (
    BoardApp,
    CommentScreen,
    CompleteScreen,
    DetailScreen,
    EditCardScreen,
    NewCardScreen,
    TagScreen,
    _card_row,
)
from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
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
    def test_block_tags_in_place(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("b")
                await pilot.pause()
                card = service.get_card(app._conn, ids["card"])
                # Cursor stayed in the refined pane (the card didn't move).
                pane = app._visible_statuses()[app._focused_col]
                return card, pane

        card, pane = _run(scenario)
        assert card["status"] == REFINED
        assert BLOCKED_TAG in card["tags"]
        assert pane == REFINED

    def test_blocked_card_still_moves(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("b")  # tag it blocked, in place
                await pilot.pause()
                await pilot.press("greater_than_sign")  # still on the flow line
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])

        card = _run(scenario)
        # A blocked card now has a real status, so > advances it normally...
        assert card["status"] == IN_PROGRESS
        # ...and keeps its tag through the move.
        assert BLOCKED_TAG in card["tags"]

    def test_unblock_removes_tag(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("b")
                await pilot.pause()
                await pilot.press("u")
                await pilot.pause()
                return service.get_card(app._conn, ids["card"])

        card = _run(scenario)
        assert card["status"] == REFINED
        assert BLOCKED_TAG not in card["tags"]


class TestTagging:
    def test_tag_gesture_toggles(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                # First toggle adds the tag.
                await pilot.press("t")
                await pilot.pause()
                assert isinstance(app.screen, TagScreen)
                app.screen.query_one("#tag-input", Input).value = "urgent"
                await pilot.click("#tag-apply")
                await pilot.pause()
                await pilot.pause()
                added = service.list_tags(app._conn, ids["card"])
                # Second toggle of the same tag removes it.
                await pilot.press("t")
                await pilot.pause()
                app.screen.query_one("#tag-input", Input).value = "urgent"
                await pilot.click("#tag-apply")
                await pilot.pause()
                await pilot.pause()
                removed = service.list_tags(app._conn, ids["card"])
                return added, removed

        added, removed = _run(scenario)
        assert added == ["urgent"]
        assert removed == []

    def test_blocked_tag_paints_on_row(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "x", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            # Wide terminal so the column is broad enough that the tag suffix
            # isn't truncated off the card row.
            async with app.run_test(size=(220, 30)) as pilot:
                await pilot.pause()
                service.block_card(app._conn, ids["x"])
                app._reload()
                await pilot.pause()
                strips = app.screen._compositor.render_strips()
                painted = "\n".join(
                    "".join(seg.text for seg in strip) for strip in strips
                )
                return painted

        assert f"#{BLOCKED_TAG}" in _run(scenario)


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

    def test_detail_renders_tags(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])
        conn = get_connection(board_path)
        service.add_tag(conn, ids["card"], "urgent")
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, DetailScreen)
                return " ".join(str(s.render()) for s in app.screen.query(Static))

        assert "urgent" in _run(scenario)


class TestCardRow:
    """Direct unit tests for the card-row renderer (truncation-proof signals)."""

    def _card(self, **over):
        base = {"id": 1, "priority": "high", "title": "x", "tags": []}
        base.update(over)
        return base

    def test_blocked_badge_uses_error_colour(self) -> None:
        # The blocked signal now rides on the leading marker plus a #blocked
        # badge in the error colour (a chip span), not a whole-row style.
        from mait_code.tui import palette as p

        row = _card_row(self._card(tags=[BLOCKED_TAG]), show_project=False)
        assert any(p.ERROR in str(span.style) for span in row.spans)

    def test_blocked_card_has_leading_marker(self) -> None:
        # Leading marker survives both truncation and the cursor-row highlight
        # (which overrides the red foreground on the selected row).
        row = _card_row(self._card(tags=[BLOCKED_TAG]), show_project=False)
        assert row.plain.startswith("⊘ ")

    def test_unblocked_card_unstyled_and_unmarked(self) -> None:
        row = _card_row(self._card(tags=[]), show_project=False)
        assert row.style != "bold red"
        assert not row.plain.startswith("⊘")

    def test_tags_appended_to_row(self) -> None:
        row = _card_row(self._card(tags=["urgent"]), show_project=False)
        assert "#urgent" in row.plain


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


class TestMutationModals:
    def test_new_card_creates_in_backlog(self, board_path: Path) -> None:
        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()
                assert isinstance(app.screen, NewCardScreen)
                app.screen.query_one("#new-title", Input).value = "Fresh card"
                app.screen.query_one("#new-project", Input).value = "demo"
                await pilot.click("#new-add")
                await pilot.pause()
                await pilot.pause()
                return service.list_cards(app._conn, project="demo")

        cards = _run(scenario)
        assert [c["title"] for c in cards] == ["Fresh card"]
        assert cards[0]["status"] == BACKLOG

    def test_new_card_empty_title_stays_open(self, board_path: Path) -> None:
        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()
                await pilot.click("#new-add")  # empty title
                await pilot.pause()
                still_open = isinstance(app.screen, NewCardScreen)
                count = len(service.list_cards(app._conn))
                return still_open, count

        still_open, count = _run(scenario)
        assert still_open is True
        assert count == 0

    def test_edit_card_updates_fields(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "old", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("e")
                await pilot.pause()
                assert isinstance(app.screen, EditCardScreen)
                app.screen.query_one("#edit-title", Input).value = "new title"
                app.screen.query_one("#edit-description", TextArea).text = "a desc"
                await pilot.click("#edit-save")
                await pilot.pause()
                await pilot.pause()
                return service.get_card(app._conn, ids["old"])

        card = _run(scenario)
        assert card["title"] == "new title"
        assert card["description"] == "a desc"

    def test_complete_with_summary_records_handoff(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "wip", "status": IN_PROGRESS}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                app._focus_status(IN_PROGRESS)
                await pilot.press("C")
                await pilot.pause()
                assert isinstance(app.screen, CompleteScreen)
                app.screen.query_one("#complete-input", Input).value = "shipped it"
                await pilot.click("#complete-ok")
                await pilot.pause()
                await pilot.pause()
                return service.get_card(app._conn, ids["wip"])

        card = _run(scenario)
        assert card["status"] == DONE
        assert card["completion_summary"] == "shipped it"


class TestHelp:
    def test_question_mark_opens_help_with_live_bindings(
        self, board_path: Path
    ) -> None:
        from mait_code.tui.help import HelpScreen

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("question_mark")
                await pilot.pause()
                is_help = isinstance(app.screen, HelpScreen)
                descs = [d for _, d in app.screen._rows] if is_help else []
                await pilot.press("escape")
                await pilot.pause()
                closed = not isinstance(app.screen, HelpScreen)
                return is_help, descs, closed

        is_help, descs, closed = _run(scenario)
        assert is_help
        assert "New" in descs and "Help" in descs
        assert closed


class TestPaletteAndJumps:
    def test_system_commands_expose_actions(self, board_path: Path) -> None:
        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                return [c.title for c in app.get_system_commands(app.screen)]

        titles = _run(scenario)
        assert "New card" in titles
        assert any(t.startswith("Jump to") for t in titles)

    def test_number_key_jumps_to_column(self, board_path: Path) -> None:
        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                await pilot.press("3")
                await pilot.pause()
                return app._focused_col

        assert _run(scenario) == 2
