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
from textual.widgets import Button, Input, Label, Static, TextArea

from mait_code.cli._board_tui import (
    BoardApp,
    CardScreen,
    CommentScreen,
    CompleteScreen,
    NewCardScreen,
    TagScreen,
    _card_box,
)
from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    DONE,
    IN_PROGRESS,
    REFINED,
    label,
)
from mait_code.tools.board.db import get_connection
from mait_code.tui.render import PALETTE_CHIPS


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
                await pilot.press("d")  # Done is hidden by default — reveal it
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

    def test_current_tag_chip_removes_tag(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                service.add_tag(app._conn, ids["card"], "alpha")
                service.add_tag(app._conn, ids["card"], "beta")
                app._reload()
                app._focus_status(REFINED)
                # The tag modal lists current tags as removable chips.
                await pilot.press("t")
                await pilot.pause()
                assert isinstance(app.screen, TagScreen)
                labels = {
                    str(b.label)
                    for b in app.screen.query(Button)
                    if (b.id or "").startswith("tag-rm-")
                }
                # Click the chip for "alpha" (tags are sorted → tag-rm-0).
                await pilot.click("#tag-rm-0")
                await pilot.pause()
                await pilot.pause()
                return labels, service.list_tags(app._conn, ids["card"])

        labels, remaining = _run(scenario)
        assert labels == {"✕ alpha", "✕ beta"}
        assert remaining == ["beta"]

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
                before = app.query_one("#tbl-refined").option_count
                await pilot.press("p")  # → first project (alpha, sorted)
                await pilot.pause()
                after = app.query_one("#tbl-refined").option_count
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
                count = app.query_one("#tbl-archived").option_count
                return shown, count

        shown, count = _run(scenario)
        assert shown is True
        assert count == 1


class TestDoneToggle:
    def test_done_pane_hidden_by_default(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "shipped", "status": DONE}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                from textual.containers import Vertical

                # Hidden column, and dropped from the focus ring entirely.
                return (
                    app.query_one("#col-done", Vertical).display,
                    DONE in app._visible_statuses(),
                )

        displayed, in_ring = _run(scenario)
        assert displayed is False
        assert in_ring is False

    def test_toggle_reveals_done(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "shipped", "status": DONE}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
                from textual.containers import Vertical

                shown = app.query_one("#col-done", Vertical).display
                count = app.query_one("#tbl-done").option_count
                in_ring = DONE in app._visible_statuses()
                return shown, count, in_ring

        shown, count, in_ring = _run(scenario)
        assert shown is True
        assert count == 1
        assert in_ring is True

    def test_move_to_done_keeps_done_hidden(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "wip", "status": IN_PROGRESS}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(IN_PROGRESS)
                await pilot.press("greater_than_sign")  # → Done (hidden)
                await pilot.pause()
                from textual.containers import Vertical

                card = service.get_card(app._conn, ids["wip"])
                # Card moved, but Done stays hidden and focus didn't crash.
                return card["status"], app.query_one("#col-done", Vertical).display

        status, done_shown = _run(scenario)
        assert status == DONE
        assert done_shown is False


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
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, CardScreen)
                assert app.screen._mode == "view"
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
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, CardScreen)
                return " ".join(str(s.render()) for s in app.screen.query(Static))

        assert "urgent" in _run(scenario)

    def test_enter_then_e_switches_to_edit_in_place(self, board_path: Path) -> None:
        """Detail→edit without leaving the card screen (the headline gesture)."""
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, CardScreen)
                assert app.screen._mode == "view"
                await pilot.press("e")
                await pilot.pause()
                # Same screen, now in edit mode (no separate modal pushed).
                assert isinstance(app.screen, CardScreen)
                return app.screen._mode

        assert _run(scenario) == "edit"

    def test_escape_from_edit_returns_to_view_then_closes(
        self, board_path: Path
    ) -> None:
        """Esc backs an edit out to view first, and only then closes the card."""
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("e")  # straight into edit
                await pilot.pause()
                assert app.screen._mode == "edit"
                await pilot.press("escape")
                await pilot.pause()
                # First Esc: edit→view, screen still open.
                assert isinstance(app.screen, CardScreen)
                first = app.screen._mode
                await pilot.press("escape")
                await pilot.pause()
                # Second Esc: closed, back on the board.
                return first, isinstance(app.screen, CardScreen)

        mode_after_first, still_open = _run(scenario)
        assert mode_after_first == "view"
        assert still_open is False


class TestCardBox:
    """Direct unit tests for the boxed card renderer (the OptionList option)."""

    def _card(self, **over):
        base = {
            "id": 1,
            "project": "demo",
            "priority": "high",
            "title": "x",
            "tags": [],
        }
        base.update(over)
        return base

    def _plain(self, renderable) -> str:
        """Render the box to plain text at a card-width console."""
        from rich.console import Console

        console = Console(width=40, record=True)
        console.print(renderable)
        return console.export_text()

    def test_blocked_box_has_error_border(self) -> None:
        # The strongest blocked signal is now the box border in the error colour.
        from mait_code.tui import palette as p

        box = _card_box(self._card(tags=[BLOCKED_TAG]), show_project=False)
        assert box.border_style == p.ERROR

    def test_blocked_box_keeps_marker_and_badge(self) -> None:
        # The leading marker and the #blocked badge are redundant signals that
        # read without colour and survive the highlighted-option tint.
        text = self._plain(
            _card_box(self._card(tags=[BLOCKED_TAG]), show_project=False)
        )
        assert "⊘" in text
        assert f"#{BLOCKED_TAG}" in text

    def test_unblocked_box_has_no_error_border_or_marker(self) -> None:
        from mait_code.tui import palette as p

        box = _card_box(self._card(tags=[]), show_project=False)
        assert box.border_style != p.ERROR
        assert "⊘" not in self._plain(box)

    def test_tags_render_in_box(self) -> None:
        text = self._plain(_card_box(self._card(tags=["urgent"]), show_project=False))
        assert "#urgent" in text

    def test_project_shown_only_when_unfiltered(self) -> None:
        shown = self._plain(_card_box(self._card(project="acme"), show_project=True))
        hidden = self._plain(_card_box(self._card(project="acme"), show_project=False))
        assert "acme" in shown
        assert "acme" not in hidden


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

    def test_selected_card_id_stays_legible(self, board_path: Path) -> None:
        # Regression: the highlighted option's background was solid $primary
        # (cyan), the same hue as the #id and tag glyphs — they vanished on the
        # selected card. The fix tints the slab instead, so fg != bg.
        _seed(board_path, [{"title": "Pick me", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)  # focus + highlight the card
                await pilot.pause()
                strips = app.screen._compositor.render_strips()
                for strip in strips:
                    for seg in strip:
                        if "#1" in seg.text and seg.style and seg.style.color:
                            return seg.style.color.triplet, (
                                seg.style.bgcolor.triplet if seg.style.bgcolor else None
                            )
                return None

        fg, bg = _run(scenario)
        assert fg is not None and bg is not None
        assert fg != bg  # the id is not painted in its own background colour


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
                assert isinstance(app.screen, CardScreen)
                assert app.screen._mode == "edit"
                app.screen.query_one("#edit-title", Input).value = "new title"
                app.screen.query_one("#edit-description", TextArea).text = "a desc"
                await pilot.click("#edit-save")
                await pilot.pause()
                await pilot.pause()
                # Saving flips back to view in place (the round-trip), and the
                # refreshed view shows the new title.
                view_mode = (
                    app.screen._mode if isinstance(app.screen, CardScreen) else None
                )
                rendered = (
                    " ".join(str(s.render()) for s in app.screen.query(Static))
                    if isinstance(app.screen, CardScreen)
                    else ""
                )
                return service.get_card(app._conn, ids["old"]), view_mode, rendered

        card, view_mode, rendered = _run(scenario)
        assert card["title"] == "new title"
        assert card["description"] == "a desc"
        assert view_mode == "view"
        assert "new title" in rendered

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


class TestCardScreenActions:
    """#14 — acting on a card from inside the card screen, refreshed in place."""

    def _rendered(self, screen) -> str:
        return " ".join(str(s.render()) for s in screen.query(Static))

    def test_comment_from_card_screen_refreshes_in_place(
        self, board_path: Path
    ) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, CardScreen)
                # 'c' pushes the comment modal on top of the card screen.
                await pilot.press("c")
                await pilot.pause()
                assert isinstance(app.screen, CommentScreen)
                app.screen.query_one("#comment-input", Input).value = "in place"
                await pilot.click("#comment-add")
                await pilot.pause()
                await pilot.pause()
                # Back on the still-open card screen (view mode), comment shown.
                still_card = isinstance(app.screen, CardScreen)
                mode = app.screen._mode if still_card else None
                rendered = self._rendered(app.screen) if still_card else ""
                return (
                    service.get_comments(app._conn, ids["card"]),
                    still_card,
                    mode,
                    rendered,
                )

        comments, still_card, mode, rendered = _run(scenario)
        assert [c["body"] for c in comments] == ["in place"]
        assert still_card is True
        assert mode == "view"
        assert "in place" in rendered

    def test_move_from_card_screen_updates_in_place(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("greater_than_sign")  # advance along the flow
                await pilot.pause()
                await pilot.pause()
                still_card = isinstance(app.screen, CardScreen)
                rendered = self._rendered(app.screen) if still_card else ""
                return (
                    service.get_card(app._conn, ids["card"])["status"],
                    still_card,
                    rendered,
                )

        status, still_card, rendered = _run(scenario)
        assert status == IN_PROGRESS
        assert still_card is True
        # The meta line reflects the card's new status without leaving the screen.
        assert label(IN_PROGRESS) in rendered

    def test_block_from_card_screen_in_place(self, board_path: Path) -> None:
        ids = _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("b")
                await pilot.pause()
                await pilot.pause()
                still_card = isinstance(app.screen, CardScreen)
                # The open screen's card refreshed in place (its tag list updated).
                tags = app.screen._card.get("tags", []) if still_card else []
                return service.get_card(app._conn, ids["card"]), still_card, tags

        card, still_card, tags = _run(scenario)
        assert card["status"] == REFINED  # block tags in place, never moves
        assert BLOCKED_TAG in card["tags"]
        assert still_card is True
        assert BLOCKED_TAG in tags

    def test_complete_from_card_screen_stays_open_shows_done(
        self, board_path: Path
    ) -> None:
        ids = _seed(board_path, [{"title": "wip", "status": IN_PROGRESS}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(IN_PROGRESS)
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("C")
                await pilot.pause()
                assert isinstance(app.screen, CompleteScreen)
                app.screen.query_one("#complete-input", Input).value = "shipped here"
                await pilot.click("#complete-ok")
                await pilot.pause()
                await pilot.pause()
                still_card = isinstance(app.screen, CardScreen)
                rendered = self._rendered(app.screen) if still_card else ""
                return service.get_card(app._conn, ids["wip"]), still_card, rendered

        card, still_card, rendered = _run(scenario)
        assert card["status"] == DONE
        assert card["completion_summary"] == "shipped here"
        # Per the refinement: stay open and re-render to Done + summary in place.
        assert still_card is True
        assert "shipped here" in rendered
        assert label(DONE) in rendered

    def test_actions_inert_in_edit_mode(self, board_path: Path) -> None:
        """Edit-mode keystrokes go to the form, not the view actions."""
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("e")  # straight into edit
                await pilot.pause()
                assert app.screen._mode == "edit"
                # 'c' types into the title input — it must not open CommentScreen.
                await pilot.press("c")
                await pilot.pause()
                return isinstance(app.screen, CardScreen), app.screen._mode

        still_card, mode = _run(scenario)
        assert still_card is True  # never bounced to a CommentScreen
        assert mode == "edit"


class TestCardScreenFooter:
    """#15 — the contextual keybinding footer (check_action gating)."""

    def test_view_mode_advertises_actions(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                screen = app.screen
                view = {
                    a: screen.check_action(a, ())
                    for a in (
                        "edit",
                        "comment",
                        "tag",
                        "complete",
                        "move_left",
                        "move_right",
                    )
                }
                save = screen.check_action("save", ())
                # active_bindings is what the Footer renders.
                actions = {ab.binding.action for ab in screen.active_bindings.values()}
                return view, save, actions

        view, save, actions = _run(scenario)
        assert all(v is True for v in view.values())
        assert save is False  # Save is edit-only
        assert "comment" in actions and "save" not in actions

    def test_edit_mode_hides_view_actions_shows_save(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("e")
                await pilot.pause()
                screen = app.screen
                hidden = {
                    a: screen.check_action(a, ())
                    for a in ("comment", "tag", "complete", "edit")
                }
                save = screen.check_action("save", ())
                close = screen.check_action("close", ())
                actions = {ab.binding.action for ab in screen.active_bindings.values()}
                return hidden, save, close, actions

        hidden, save, close, actions = _run(scenario)
        assert all(v is False for v in hidden.values())
        assert save is True
        assert close is True
        assert "save" in actions
        assert "comment" not in actions and "tag" not in actions

    def test_block_unblock_mutual_exclusion(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                screen = app.screen
                unblocked = (
                    screen.check_action("block", ()),
                    screen.check_action("unblock", ()),
                )
                # Block in place — the footer flips (refresh_bindings via show_card).
                await pilot.press("b")
                await pilot.pause()
                await pilot.pause()
                screen = app.screen
                blocked = (
                    screen.check_action("block", ()),
                    screen.check_action("unblock", ()),
                )
                return unblocked, blocked

        unblocked, blocked = _run(scenario)
        assert unblocked == (True, False)  # unblocked card offers Block
        assert blocked == (False, True)  # blocked card offers Unblock


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


class TestTheming:
    """Chips are Rich text (no CSS $-vars), so they must be re-derived from the
    active theme and repainted on a switch."""

    def test_chip_colours_track_active_theme(self, board_path: Path) -> None:
        from mait_code.tui import palette as p

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                default = app._chip_colours()
                # Switch to a built-in theme with a different palette.
                app.theme = "nord"
                await pilot.pause()
                switched = app._chip_colours()
                return default, switched, app.current_theme

        default, switched, theme = _run(scenario)
        # Under mait-dark the tag hue is the house secondary…
        assert default.tag == p.SECONDARY
        # …and after the switch it tracks the new theme's secondary, not the old.
        assert switched.tag == (theme.secondary or theme.primary)
        assert switched.tag != default.tag

    def test_open_card_recolours_on_theme_switch(self, board_path: Path) -> None:
        _seed(board_path, [{"title": "card", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, CardScreen)
                before = screen._chip_colours
                app.theme = "nord"
                await pilot.pause()
                return before, screen._chip_colours, app._chip_colours()

        before, after, expected = _run(scenario)
        # The open card screen picked up the new theme's chip palette.
        assert after == expected
        assert after != before

    def test_ansi_theme_renders_card_without_crashing(self, board_path: Path) -> None:
        """ANSI themes set colours to named tokens ('ansi_blue', 'ansi_default')
        — valid in CSS but not as Rich-text styles, which Textual re-parses when
        the card screen paints (MissingStyle). Chips must fall back to the hex
        palette, so opening a card under an ANSI theme renders instead of crashing.
        """
        _seed(board_path, [{"title": "card", "priority": "low", "status": REFINED}])

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.theme = "ansi-dark"
                await pilot.pause()
                app._focus_status(REFINED)
                await pilot.press("enter")  # open the card screen — the crash site
                await pilot.pause()
                return type(app.screen).__name__, app._chip_colours(), app._exception

        screen, colours, exc = _run(scenario)
        assert exc is None  # the card screen painted without MissingStyle
        assert screen == "CardScreen"
        assert colours == PALETTE_CHIPS  # chips fell back to the hex palette
