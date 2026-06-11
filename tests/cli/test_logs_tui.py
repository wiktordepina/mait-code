"""Tests for the Textual ``mait-code logs`` TUI.

Driven by Textual's headless pilot (``App.run_test()`` wrapped in
``asyncio.run`` — no pytest-asyncio), mirroring the board TUI tests. The app
takes a ``log_path`` so each scenario points at isolated temp files; the
parsing layer is covered directly in ``test_logs.py``, so here we only check
the filter wiring on top of it.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import os
import time
from pathlib import Path

import pytest
from textual.widgets import Select, Tree

from mait_code.cli._logs_tui import LogsApp


def _run(coro_factory):
    return asyncio.run(coro_factory())


@pytest.fixture(autouse=True)
def _utc() -> object:
    """Pin the process to UTC so day grouping is deterministic."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


def _ts(d: int, hh: int) -> float:
    return float(calendar.timegm((2026, 6, d, hh, 0, 0, 0, 0, 0)))


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    """Two days across two files: three board lines, one memory error."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    active = log_dir / "mait-code.jsonl"
    active.write_text(
        "\n".join(
            json.dumps(line)
            for line in [
                {
                    "ts": _ts(4, 9),
                    "level": "debug",
                    "msg": "resolved settings",
                    "tool": "mait-code",
                },
                {
                    "ts": _ts(4, 10),
                    "level": "info",
                    "msg": "invoked: board",
                    "tool": "mc-tool-board",
                },
                {
                    "ts": _ts(4, 11),
                    "level": "error",
                    "msg": "failed: memory",
                    "tool": "mc-tool-memory",
                },
            ]
        )
        + "\n"
    )
    (log_dir / "mait-code.jsonl.2026-06-01").write_text(
        json.dumps(
            {
                "ts": _ts(1, 9),
                "level": "info",
                "msg": "completed: board",
                "tool": "mc-tool-board",
            }
        )
        + "\n"
    )
    return active


def _leaf_count(app: LogsApp) -> int:
    """Entry leaves currently in the tree (folded-note rows carry ``None``)."""
    tree = app.query_one("#list", Tree)
    return sum(
        1
        for day in tree.root.children
        for leaf in day.children
        if isinstance(leaf.data, dict)
    )


def test_tool_filter_narrows_to_one_tool(log_path: Path) -> None:
    async def scenario() -> None:
        app = LogsApp(log_path=log_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert _leaf_count(app) == 4
            await pilot.press("t")
            await pilot.pause()
            app.screen.query_one("#choice-select", Select).value = "mc-tool-board"
            await pilot.pause()
            assert _leaf_count(app) == 2  # one per day, both days expanded

    _run(scenario)


def test_day_filter_narrows_to_one_day(log_path: Path) -> None:
    async def scenario() -> None:
        app = LogsApp(log_path=log_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            app.screen.query_one("#choice-select", Select).value = "2026-06-01"
            await pilot.pause()
            tree = app.query_one("#list", Tree)
            assert len(tree.root.children) == 1
            assert _leaf_count(app) == 1

    _run(scenario)


def test_level_cycle_raises_the_severity_floor(log_path: Path) -> None:
    async def scenario() -> None:
        app = LogsApp(log_path=log_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("l", "l")  # all → debug → info
            await pilot.pause()
            assert _leaf_count(app) == 3  # the debug line drops out
            await pilot.press("l", "l")  # → warning → error
            await pilot.pause()
            assert _leaf_count(app) == 1
            await pilot.press("l")  # → back to all
            await pilot.pause()
            assert _leaf_count(app) == 4

    _run(scenario)


def test_escape_steps_back_to_the_list(log_path: Path) -> None:
    async def scenario() -> None:
        app = LogsApp(log_path=log_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            assert app.query_one("#filter").has_focus
            await pilot.press("escape")
            assert app.query_one("#list", Tree).has_focus

    _run(scenario)


def test_filter_cancel_keeps_the_active_filter(log_path: Path) -> None:
    async def scenario() -> None:
        app = LogsApp(log_path=log_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            app.screen.query_one("#choice-select", Select).value = "mc-tool-board"
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            await pilot.press("escape")  # cancel the modal
            await pilot.pause()
            assert _leaf_count(app) == 2  # still narrowed to the board tool

    _run(scenario)
