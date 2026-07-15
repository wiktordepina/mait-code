"""Behaviour tests for the start-page setup TUI.

The root conftest points ``MAIT_CODE_DATA_DIR`` at a per-test tmp dir; each
test authors its own ``dashboard.toml`` and pins the loader at it. The two
safety contracts get their own tests: typing a command never executes it, and
quitting with unsaved changes asks first.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mait_code.cli._dashboard_tui import DashboardSetupApp
from mait_code.tui.confirm import ConfirmScreen


@pytest.fixture()
def config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An authored dashboard.toml the app under test loads and saves."""
    import mait_code.cli._dashboard as dashboard_mod

    path = tmp_path / "dashboard.toml"
    path.write_text(
        "columns = 2\n"
        '[[tile]]\nwidget = "board"\n'
        '[[tile]]\ncommand = "echo hi"\ntitle = "Hello"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_mod, "dashboard_path", lambda: path)
    return path


def _run(coro_factory):
    return asyncio.run(coro_factory())


def test_loads_tiles_and_fills_the_form(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Input, OptionList

            options = app.query_one("#tile-list", OptionList)
            first_form = app.query_one("#command", Input).display
            app._select(1)
            await pilot.pause()
            command_value = app.query_one("#command", Input).value
            title_value = app.query_one("#title", Input).value
            return options.option_count, first_form, command_value, title_value

    count, command_shown_for_widget, command_value, title_value = _run(scenario)
    assert count == 2
    assert not command_shown_for_widget  # widget tile hides the command input
    assert command_value == "echo hi"
    assert title_value == "Hello"


def test_typing_a_command_never_executes_it(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mait_code.cli._dashboard as dashboard_mod

    calls: list[str] = []
    monkeypatch.setattr(
        dashboard_mod,
        "run_command_tile",
        lambda command, timeout: calls.append(command),
    )

    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._select(1)
            await pilot.pause()
            from textual.widgets import Input, Static

            command = app.query_one("#command", Input)
            command.focus()
            await pilot.pause()
            await pilot.press("end", *"; rm -rf x")
            await pilot.pause()
            preview = str(app.query_one("#preview", Static).render())
            return app._model.tiles[1].command, preview

    value, preview = _run(scenario)
    assert value == "echo hi; rm -rf x"
    assert calls == []  # nothing ran while typing
    assert "Ctrl+R" in preview  # the preview stays a hint


def test_explicit_preview_runs_the_command(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._select(1)
            await pilot.pause()
            app.action_preview_command()
            await app.workers.wait_for_complete()
            await pilot.pause()
            from textual.widgets import Static

            return str(app.query_one("#preview", Static).render())

    assert _run(scenario) == "hi"


def test_edits_mark_dirty_and_save_writes_the_file(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Input

            app.query_one("#title", Input).value = "The board"
            await pilot.pause()
            dirty_before = app._dirty
            app.action_save()
            await pilot.pause()
            return dirty_before, app._dirty

    dirty_before, dirty_after = _run(scenario)
    assert dirty_before and not dirty_after
    text = config_file.read_text(encoding="utf-8")
    assert 'title = "The board"' in text


def test_add_remove_and_reorder_tiles(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_add_tile()  # inserts after the selection (index 1)
            await pilot.pause()
            added = [(t.widget, t.command) for t in app._model.tiles]
            app.action_move_up()  # new tile up to index 0
            await pilot.pause()
            moved = [(t.widget, t.command) for t in app._model.tiles]
            app.action_remove_tile()  # remove it again
            await pilot.pause()
            removed = [(t.widget, t.command) for t in app._model.tiles]
            return added, moved, removed

    added, moved, removed = _run(scenario)
    assert added == [("board", None), ("reminders", None), (None, "echo hi")]
    assert moved == [("reminders", None), ("board", None), (None, "echo hi")]
    assert removed == [("board", None), (None, "echo hi")]


def test_remove_refuses_the_last_tile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import mait_code.cli._dashboard as dashboard_mod

    path = tmp_path / "dashboard.toml"
    path.write_text('[[tile]]\nwidget = "board"\n', encoding="utf-8")
    monkeypatch.setattr(dashboard_mod, "dashboard_path", lambda: path)

    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_remove_tile()
            await pilot.pause()
            return len(app._model.tiles)

    assert _run(scenario) == 1


def test_columns_change_clamps_span_options(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Select

            app._tile().span = 2
            app.query_one("#columns", Select).value = 1
            await pilot.pause()
            return app._model.columns, app._tile().span

    columns, span = _run(scenario)
    assert columns == 1
    assert span == 1  # clamped down with the grid


def test_quit_with_unsaved_changes_asks_first(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Input

            app.query_one("#title", Input).value = "dirty now"
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            modal_shown = isinstance(app.screen, ConfirmScreen)
            await pilot.press("escape")  # dismiss as "No" — stay in the app
            await pilot.pause()
            still_running = app.is_running
            return modal_shown, still_running

    modal_shown, still_running = _run(scenario)
    assert modal_shown
    assert still_running


def test_clean_quit_needs_no_confirm(config_file: Path) -> None:
    async def scenario():
        app = DashboardSetupApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("q")
            # The quit action runs in a worker; give the loop a few beats to
            # process it (waiting on the worker after exit would deadlock).
            for _ in range(10):
                if not app.is_running:
                    break
                await pilot.pause()
            return app.is_running

    assert not _run(scenario)
