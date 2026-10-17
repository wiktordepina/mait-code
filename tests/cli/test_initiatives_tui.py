"""Tests for the board's Initiatives view and the card screen's relationships.

Driven by Textual's headless pilot, like ``test_board_tui.py``. The service
layer behind epics and links is covered in ``tests/tools/board/``; here we
check the TUI wiring: switching views, the member table's order and filters,
the relationship rows, the link and epic modals, and refused edits surfacing
as toasts rather than crashes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, Label, OptionList, Select

from mait_code.cli._board_tui import (
    INITIATIVES,
    BoardApp,
    CardScreen,
    EpicScreen,
    LinkScreen,
    _card_box,
)
from mait_code.cli._initiatives_tui import InitiativesScreen
from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    DONE,
    EPIC_PROJECT,
    IN_PROGRESS,
    IN_REVIEW,
    REFINED,
)
from mait_code.tools.board.db import get_connection


def _run(coro_factory):
    return asyncio.run(coro_factory())


@pytest.fixture
def board_path(tmp_path: Path) -> Path:
    return tmp_path / "board.db"


def _connect(board_path: Path):
    return get_connection(board_path)


def _card(conn, title: str, *, status: str | None = None, **kw) -> int:
    cid = service.add_card(conn, project=kw.pop("project", "demo"), title=title, **kw)
    if status:
        service.move_card(conn, cid, status)
    return cid


def _epic(conn, title: str = "Voice") -> int:
    return service.add_card(conn, project=None, title=title, kind="epic")


def _member_ids(app: BoardApp) -> list[int]:
    table = app.screen.query_one("#members", DataTable)
    if not table.display:
        return []
    return [int(row.value) for row in table.rows if row.value is not None]


# --- switching views ---


class TestSwitching:
    def test_i_toggles_between_kanban_and_initiatives(self, board_path: Path) -> None:
        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("i")
                await pilot.pause()
                there = isinstance(app.screen, InitiativesScreen)
                await pilot.press("i")
                await pilot.pause()
                return there, len(app.screen_stack)

        assert _run(scenario) == (True, 1)

    def test_escape_returns_to_the_kanban_not_quit(self, board_path: Path) -> None:
        """Opened straight on Initiatives, escape still lands on the kanban."""

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                started = isinstance(app.screen, InitiativesScreen)
                await pilot.press("escape")
                await pilot.pause()
                return started, len(app.screen_stack), app.is_running

        assert _run(scenario) == (True, 1, True)

    def test_i_does_nothing_inside_the_card_screen(self, board_path: Path) -> None:
        conn = _connect(board_path)
        _card(conn, "a")
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("i")
                await pilot.pause()
                return type(app.screen).__name__

        assert _run(scenario) == "CardScreen"


# --- epics and members ---


class TestInitiatives:
    def test_epics_show_progress_and_done_toggle(self, board_path: Path) -> None:
        conn = _connect(board_path)
        voice = _epic(conn, "Voice")
        done_epic = _epic(conn, "Shipped")
        service.complete_card(conn, done_epic)
        _card(conn, "a", parent_id=voice, status=DONE)
        _card(conn, "b", parent_id=voice)
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                epics = app.screen.query_one("#epics", OptionList)
                first = (epics.option_count, str(epics.get_option_at_index(0).prompt))
                await pilot.press("d")
                await pilot.pause()
                return first, epics.option_count

        (count, prompt), with_done = _run(scenario)
        assert count == 1 and "Voice" in prompt and "1/2 done" in prompt
        assert with_done == 2

    def test_members_span_projects_in_bucket_order(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        done = _card(conn, "done", parent_id=eid, status=DONE)
        backlog = _card(conn, "backlog", parent_id=eid, project="homelab")
        refined_blocked = _card(conn, "tagged", parent_id=eid, status=REFINED)
        service.block_card(conn, refined_blocked)
        review = _card(conn, "review", parent_id=eid, status=IN_REVIEW)
        progress = _card(conn, "progress", parent_id=eid, status=IN_PROGRESS)
        ready = _card(conn, "ready", parent_id=eid, status=REFINED, project="maitre-d")
        waiting = _card(conn, "waiting", parent_id=eid, status=REFINED)
        service.add_link(conn, backlog, waiting)
        archived = _card(conn, "archived", parent_id=eid)
        service.archive_card(conn, archived)
        _card(conn, "outsider", status=REFINED)
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                return _member_ids(app)

        assert _run(scenario) == [
            ready,
            progress,
            review,
            refined_blocked,
            waiting,
            backlog,
            done,
        ]

    def test_ready_only_matches_the_service(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        blocker = _card(conn, "blocker", parent_id=eid, status=REFINED)
        waiting = _card(conn, "waiting", parent_id=eid, status=REFINED)
        service.add_link(conn, blocker, waiting)
        _card(conn, "backlog", parent_id=eid)
        expected = [
            c["id"] for c in service.list_cards(conn, parent_id=eid, ready=True)
        ]
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("R")
                await pilot.pause()
                return _member_ids(app)

        assert _run(scenario) == expected == [blocker]

    def test_project_filter_does_not_apply(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        a = _card(conn, "a", parent_id=eid, project="one")
        b = _card(conn, "b", parent_id=eid, project="two")
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                app._project_filter = "one"
                await pilot.press("i")
                await pilot.pause()
                return sorted(_member_ids(app))

        assert _run(scenario) == sorted([a, b])

    def test_empty_states(self, board_path: Path) -> None:
        async def no_epics():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                empty = app.screen.query_one("#members-empty", Label)
                return empty.display, str(empty.render())

        shown, text = _run(no_epics)
        assert shown and "--epic" in text

        conn = _connect(board_path)
        _epic(conn)
        conn.close()

        async def no_members():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                empty = app.screen.query_one("#members-empty", Label)
                return empty.display, str(empty.render())

        shown, text = _run(no_members)
        assert shown and "No members yet" in text

    def test_selecting_a_member_opens_it_and_refreshes_on_close(
        self, board_path: Path
    ) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        cid = _card(conn, "member", parent_id=eid)
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("right")
                await pilot.press("enter")
                await pilot.pause()
                opened = app.screen
                assert isinstance(opened, CardScreen)
                # Clear its epic from the card screen, then close it.
                opened.post_message(CardScreen.Mutate(cid, "set_parent", None))
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                return opened.card_id, _member_ids(app)

        assert _run(scenario) == (cid, [])

    def test_selecting_the_epic_opens_it(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        conn.close()

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                screen = app.screen
                return isinstance(screen, CardScreen) and screen.card_id

        assert _run(scenario) == eid

    def test_live_poll_refreshes_the_view(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)

        async def scenario():
            app = BoardApp(db_path=board_path, initial_view=INITIATIVES)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                before = _member_ids(app)
                added = _card(conn, "from the CLI", parent_id=eid)
                await app._poll_external_changes()
                await pilot.pause()
                return before, _member_ids(app), added

        before, after, added = _run(scenario)
        conn.close()
        assert before == [] and after == [added]


# --- the card screen ---


def _open_card(board_path: Path, card_id: int, steps):
    """Open *card_id* in the card screen and run *steps(app, pilot, screen)*."""

    async def scenario():
        app = BoardApp(db_path=board_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.run_worker(app.open_card(card_id))
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, CardScreen)
            return await steps(app, pilot, screen)

    return _run(scenario)


def _relations_text(screen: CardScreen) -> str:
    """The relationship rows as plain text, or ``""`` when none are shown."""
    import io

    from rich.console import Console

    if not screen.query(".relations"):
        return ""
    grid = CardScreen._relations(screen._card)
    console = Console(file=io.StringIO(), width=100, record=True)
    console.print(grid)
    return console.export_text()


class TestCardRelationships:
    def test_rows_list_every_blocker_with_its_state(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn, "Voice")
        finished = _card(conn, "finished")
        open_ = _card(conn, "open")
        cid = _card(conn, "card", parent_id=eid)
        after = _card(conn, "after")
        for a, b in ((finished, cid), (open_, cid), (cid, after)):
            service.add_link(conn, a, b)
        service.complete_card(conn, finished)
        conn.close()

        async def steps(app, pilot, screen):
            return _relations_text(screen)

        text = _open_card(board_path, cid, steps)
        assert f"#{eid} Voice" in text
        assert f"#{finished} finished  done" in text
        assert f"#{open_} open  waiting" in text
        assert f"#{after} after  Backlog" in text

    def test_rows_hidden_when_empty(self, board_path: Path) -> None:
        conn = _connect(board_path)
        cid = _card(conn, "loner")
        conn.close()

        async def steps(app, pilot, screen):
            return _relations_text(screen)

        assert _open_card(board_path, cid, steps) == ""

    def test_link_add_and_remove(self, board_path: Path) -> None:
        conn = _connect(board_path)
        cid = _card(conn, "card")
        other = _card(conn, "other")
        conn.close()

        async def steps(app, pilot, screen):
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, LinkScreen)
            app.screen.query_one("#link-target", Input).value = str(other)
            await pilot.press("enter")
            await pilot.pause()
            added = [b["id"] for b in service.get_card(app.conn, cid)["blocks"]]
            await pilot.press("l")
            await pilot.pause()
            await pilot.click(f"#link-rm-out-{other}")
            await pilot.pause()
            removed = service.get_card(app.conn, cid)["blocks"]
            return added, removed

        assert _open_card(board_path, cid, steps) == ([other], [])

    def test_link_the_other_way(self, board_path: Path) -> None:
        conn = _connect(board_path)
        cid = _card(conn, "card")
        other = _card(conn, "other")
        conn.close()

        async def steps(app, pilot, screen):
            await pilot.press("l")
            await pilot.pause()
            await pilot.click("#link-dir-blocked-by")
            app.screen.query_one("#link-target", Input).value = str(other)
            await pilot.click("#link-add")
            await pilot.pause()
            return service.get_card(app.conn, cid)["waiting_on"]

        assert _open_card(board_path, cid, steps) == [other]

    def test_a_cycle_is_a_toast_not_a_crash(self, board_path: Path) -> None:
        conn = _connect(board_path)
        a = _card(conn, "a")
        b = _card(conn, "b")
        service.add_link(conn, a, b)
        conn.close()

        async def steps(app, pilot, screen):
            screen.post_message(CardScreen.Mutate(b, "link_add", (b, a)))
            await pilot.pause()
            toasts = [n.message for n in app._notifications]
            return toasts, service.get_card(app.conn, a)["blocked_by"]

        toasts, blocked_by = _open_card(board_path, b, steps)
        assert any(
            "would close a loop" in t and f"#{b} → #{a} → #{b}" in t for t in toasts
        )
        assert blocked_by == []

    def test_removing_a_missing_link_toasts(self, board_path: Path) -> None:
        conn = _connect(board_path)
        a = _card(conn, "a")
        b = _card(conn, "b")
        conn.close()

        async def steps(app, pilot, screen):
            screen.post_message(CardScreen.Mutate(a, "link_remove", (a, b)))
            await pilot.pause()
            return [n.message for n in app._notifications]

        assert any("doesn't block" in t for t in _open_card(board_path, a, steps))

    def test_epic_modal_sets_and_clears(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn, "Voice")
        cid = _card(conn, "card")
        conn.close()

        async def steps(app, pilot, screen):
            await pilot.press("P")
            await pilot.pause()
            assert isinstance(app.screen, EpicScreen)
            app.screen.query_one("#epic-select", Select).value = eid
            await pilot.click("#epic-set")
            await pilot.pause()
            set_to = service.get_card(app.conn, cid)["parent_id"]
            await pilot.press("P")
            await pilot.pause()
            app.screen.query_one("#epic-select", Select).value = "none"
            await pilot.click("#epic-set")
            await pilot.pause()
            return set_to, service.get_card(app.conn, cid)["parent_id"]

        assert _open_card(board_path, cid, steps) == (eid, None)

    def test_epic_project_typed_into_a_card_is_a_toast(self, board_path: Path) -> None:
        conn = _connect(board_path)
        cid = _card(conn, "card")
        conn.close()

        async def steps(app, pilot, screen):
            await pilot.press("e")
            await pilot.pause()
            screen.query_one("#edit-project", Input).value = EPIC_PROJECT
            await pilot.press("ctrl+s")
            await pilot.pause()
            toasts = [n.message for n in app._notifications]
            return toasts, screen.is_editing, service.get_card(app.conn, cid)["project"]

        toasts, editing, project = _open_card(board_path, cid, steps)
        assert any("@epic" in t or "epic" in t for t in toasts)
        assert editing and project == "demo"


class TestEpicCardScreen:
    def test_card_only_actions_are_hidden(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        conn.close()

        async def steps(app, pilot, screen):
            return {
                a: screen.check_action(a, ())
                for a in ("link", "set_epic", "block", "unblock", "comment")
            }

        assert _open_card(board_path, eid, steps) == {
            "link": False,
            "set_epic": False,
            "block": False,
            "unblock": False,
            "comment": True,
        }

    def test_meta_shows_progress_and_form_locks_project(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        _card(conn, "m", parent_id=eid, status=DONE)
        _card(conn, "n", parent_id=eid)
        conn.close()

        async def steps(app, pilot, screen):
            meta = str(screen.query_one(".detail-meta").render())
            await pilot.press("e")
            await pilot.pause()
            project = screen.query_one("#edit-project", Input)
            return meta, project.disabled, bool(screen.query("#edit-tag-input"))

        meta, locked, has_tags = _open_card(board_path, eid, steps)
        assert meta.startswith("epic") and "1/2 done" in meta and "@epic" not in meta
        assert locked and not has_tags

    def test_saving_an_epic_edit_works(self, board_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        conn.close()

        async def steps(app, pilot, screen):
            app._project_filter = "demo"
            await pilot.press("e")
            await pilot.pause()
            screen.query_one("#edit-title", Input).value = "Renamed"
            await pilot.press("ctrl+s")
            await pilot.pause()
            toasts = [n.message for n in app._notifications]
            return toasts, service.get_card(app.conn, eid)["title"]

        toasts, title = _open_card(board_path, eid, steps)
        assert title == "Renamed"
        assert f"Updated card #{eid}" in toasts
        assert not any("hidden by" in t for t in toasts)

    def test_export_includes_members(self, board_path: Path, tmp_path: Path) -> None:
        conn = _connect(board_path)
        eid = _epic(conn)
        _card(conn, "member card", parent_id=eid)
        conn.close()
        out = tmp_path / "epic.md"

        async def steps(app, pilot, screen):
            await pilot.press("x")
            await pilot.pause()
            app.screen.query_one("#export-path", Input).value = str(out)
            await pilot.click("#export-save")
            await pilot.pause()

        _open_card(board_path, eid, steps)
        text = out.read_text()
        assert "## Members" in text and "member card" in text


# --- kanban marker ---


def test_waiting_card_box_carries_the_marker_and_reason() -> None:
    import io

    from rich.console import Console

    card = {
        "id": 5,
        "project": "demo",
        "title": "waits",
        "priority": "medium",
        "tags": ["blocked"],
        "waiting_on": [3, 4],
    }
    console = Console(file=io.StringIO(), width=40, record=True)
    console.print(_card_box(card, show_project=False))
    text = console.export_text()
    assert "⊘" in text and "waiting on #3, #4" in text and "#blocked" in text
