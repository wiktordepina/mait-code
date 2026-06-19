"""Tests for the shared :class:`~mait_code.tui.confirm.ConfirmScreen`.

The yes/no modal the settings editor and home hub open before a destructive
action (re-embed, data-dir move, reindex). Driven by Textual's headless pilot
(``asyncio.run`` + ``run_test``, mirroring ``test_app.py``); the modal is
pushed onto a bare :class:`~mait_code.tui.app.MaitApp` host so the shared
``.modal-dialog`` styling resolves, then dismissed by button or key. The
resolved bool is captured via the ``push_screen`` callback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from textual.pilot import Pilot
from textual.widgets import Label

from mait_code.tui.app import MaitApp
from mait_code.tui.confirm import ConfirmScreen


def _run(coro_factory):
    return asyncio.run(coro_factory())


async def _drive(
    question: str, interact: Callable[[Pilot], Awaitable[None]]
) -> list[bool]:
    """Push a ``ConfirmScreen``, run ``interact``, return its resolution.

    The returned list is empty if the modal never dismissed, else holds the
    single resolved bool — so a test can tell "didn't resolve" from "resolved
    ``False``".
    """
    app = MaitApp()
    box: list[bool] = []
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.push_screen(ConfirmScreen(question), box.append)
        await pilot.pause()
        await interact(pilot)
        await pilot.pause()
    return box


def test_yes_button_resolves_true() -> None:
    async def scenario():
        return await _drive("Reindex now?", lambda pilot: pilot.click("#yes"))

    assert _run(scenario) == [True]


def test_no_button_resolves_false() -> None:
    async def scenario():
        return await _drive("Reindex now?", lambda pilot: pilot.click("#no"))

    assert _run(scenario) == [False]


def test_escape_resolves_false() -> None:
    # Escape is the "No" binding — bailing is never an accidental "Yes".
    async def scenario():
        return await _drive("Reindex now?", lambda pilot: pilot.press("escape"))

    assert _run(scenario) == [False]


def test_question_shown_as_title() -> None:
    async def scenario() -> str:
        app = MaitApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.push_screen(ConfirmScreen("Delete the data dir?"))
            await pilot.pause()
            return str(app.screen.query_one(".modal-title", Label).render())

    assert "Delete the data dir?" in _run(scenario)
