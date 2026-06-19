"""Tests for the shared filter modals in :mod:`mait_code.tui.filters`.

:class:`~mait_code.tui.filters.ChoiceFilterScreen` is the generic pick-one
``Select`` modal (the log viewer's tool/day filters);
:class:`~mait_code.tui.filters.ProjectFilterScreen` is its project-flavoured
subclass (the memory, observations and board browsers). The contract worth
pinning is the three-way outcome — a choice, the :data:`ALL_CHOICES` sentinel
that *clears* the filter, and the ``None`` that escape dismisses with — kept
distinct so "all" never collapses into "cancel".

Driven like ``test_app.py`` (``asyncio.run`` + headless pilot); each modal is
pushed onto a bare :class:`~mait_code.tui.app.MaitApp` host and resolved via
the ``push_screen`` callback. Selecting a value is done by assigning the
``Select`` value directly, as the board picker tests do.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from textual.pilot import Pilot
from textual.screen import ModalScreen
from textual.widgets import Label, Select

from mait_code.tui.app import MaitApp
from mait_code.tui.filters import (
    ALL_CHOICES,
    ALL_PROJECTS,
    ChoiceFilterScreen,
    ProjectFilterScreen,
)


def _run(coro_factory):
    return asyncio.run(coro_factory())


async def _drive(
    screen: ModalScreen, interact: Callable[[MaitApp, Pilot], Awaitable[None]]
) -> list[object]:
    """Push ``screen``, run ``interact``, return its resolution.

    The returned list is empty when the modal never dismissed (so the mount-echo
    case is observable), else holds the single resolved value.
    """
    app = MaitApp()
    box: list[object] = []
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.push_screen(screen, box.append)
        await pilot.pause()
        await interact(app, pilot)
        await pilot.pause()
    return box


async def _select(app: MaitApp, value: object) -> None:
    app.screen.query_one("#choice-select", Select).value = value


# --- ChoiceFilterScreen ---


def test_pick_choice_applies() -> None:
    async def scenario():
        return await _drive(
            ChoiceFilterScreen("Filter by tool", ["board", "memory"]),
            lambda app, pilot: _select(app, "memory"),
        )

    assert _run(scenario) == ["memory"]


def test_all_label_clears_to_sentinel() -> None:
    # Opened on a concrete value, picking "All …" resolves to ALL_CHOICES —
    # the clear signal — not to None.
    async def scenario():
        return await _drive(
            ChoiceFilterScreen("Filter by tool", ["board", "memory"], current="board"),
            lambda app, pilot: _select(app, ALL_CHOICES),
        )

    box = _run(scenario)
    assert box == [ALL_CHOICES]
    assert box[0] is ALL_CHOICES
    assert box[0] is not None


def test_escape_cancels_distinct_from_all() -> None:
    # The modal opens with its dropdown expanded, so the first escape collapses
    # it and the second reaches the screen's cancel binding — escape dismisses
    # with None (leave the filter as-is), never the ALL_CHOICES clear signal.
    async def _escape_twice(app: MaitApp, pilot: Pilot) -> None:
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")

    async def scenario():
        return await _drive(
            ChoiceFilterScreen("Filter by tool", ["board", "memory"]), _escape_twice
        )

    box = _run(scenario)
    assert box == [None]
    assert box[0] is not ALL_CHOICES


def test_mount_echo_does_not_dismiss() -> None:
    # Select posts a Changed for its initial value on mount; opening on a live
    # filter must not instantly dismiss it.
    async def scenario():
        async def noop(app: MaitApp, pilot: Pilot) -> None:
            return None

        return await _drive(
            ChoiceFilterScreen("Filter by tool", ["board", "memory"], current="board"),
            noop,
        )

    assert _run(scenario) == []


def test_title_and_all_label_render() -> None:
    async def scenario() -> tuple[str, list[str]]:
        app = MaitApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.push_screen(
                ChoiceFilterScreen(
                    "Narrow to a day", ["mon", "tue"], all_label="All days"
                )
            )
            await pilot.pause()
            title = str(app.screen.query_one(".modal-title", Label).render())
            select = app.screen.query_one("#choice-select", Select)
            labels = [str(prompt) for prompt, _ in select._options]
            return title, labels

    title, labels = _run(scenario)
    assert "Narrow to a day" in title
    assert labels[0] == "All days"  # the clear option leads the list


# --- ProjectFilterScreen ---


def test_project_pick_applies() -> None:
    async def scenario():
        return await _drive(
            ProjectFilterScreen(["alpha", "beta"]),
            lambda app, pilot: _select(app, "alpha"),
        )

    assert _run(scenario) == ["alpha"]


def test_project_screen_wires_project_labels() -> None:
    async def scenario() -> tuple[str, str]:
        app = MaitApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.push_screen(ProjectFilterScreen(["alpha", "beta"], current="alpha"))
            await pilot.pause()
            title = str(app.screen.query_one(".modal-title", Label).render())
            select = app.screen.query_one("#choice-select", Select)
            return title, str(select._options[0][0])

    title, all_label = _run(scenario)
    assert "Filter by project" in title
    assert all_label == "All projects"


def test_all_projects_aliases_all_choices() -> None:
    # The board, memory and observations browsers all compare against this
    # sentinel; it must stay the one shared object.
    assert ALL_PROJECTS is ALL_CHOICES
