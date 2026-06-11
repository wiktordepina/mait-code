"""Snapshot tests locking the log viewer's visual output.

Renders seeded log files at a fixed terminal size against accepted SVG
baselines under ``__snapshots__/``. The files carry fixed epoch timestamps and
the ``TZ`` fixture pins the process to UTC, so the rendered days and times
never drift; the theme is the ``mait-dark`` default applied by
:class:`~mait_code.tui.app.MaitApp`.

Regenerate the baselines intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_logs_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

import calendar
import json
import os
import time
from pathlib import Path

import pytest

import mait_code.tui.banner as banner_mod
from mait_code.cli._logs_tui import LogsApp


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


@pytest.fixture(autouse=True)
def _utc() -> object:
    """Pin the process to UTC so local-time rendering is deterministic."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


def _ts(d: int, hh: int, mm: int = 0, ss: int = 0) -> float:
    """A June 2026 UTC timestamp — the fixture's whole story is one week."""
    return float(calendar.timegm((2026, 6, d, hh, mm, ss, 0, 0, 0)))


_STACK = (
    "Traceback (most recent call last):\n"
    '  File "embeddings.py", line 42, in embed\n'
    "    response = client.invoke_model(body)\n"
    "ConnectionError: bedrock endpoint unreachable"
)


def _seed_logs(tmp_path: Path) -> Path:
    """Two days of logs: a rotated quiet day and an active day whose newest
    line is a failure with a stack trace (so boot's detail pane exercises the
    full record rendering). One malformed line proves the skip path."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    active = log_dir / "mait-code.jsonl"
    day4 = [
        {
            "ts": _ts(4, 8, 59, 1),
            "level": "debug",
            "logger": "config",
            "msg": "resolved settings file",
            "tool": "mait-code",
            "pid": 4242,
        },
        {
            "ts": _ts(4, 9, 0, 0),
            "level": "info",
            "logger": "invocation",
            "msg": "invoked: board",
            "tool": "mc-tool-board",
            "pid": 4301,
            "event": "invoked",
            "args": "action='list' json=True",
        },
        {
            "ts": _ts(4, 9, 0, 0),
            "level": "info",
            "logger": "invocation",
            "msg": "completed: board",
            "tool": "mc-tool-board",
            "pid": 4301,
            "event": "completed",
            "duration_ms": 12.3,
        },
        {
            "ts": _ts(4, 9, 30, 0),
            "level": "warning",
            "logger": "hooks.observe",
            "msg": "extraction returned no observations",
            "tool": "mc-hook-observe",
            "pid": 4350,
        },
        {
            "ts": _ts(4, 10, 0, 4),
            "level": "info",
            "logger": "invocation",
            "msg": "invoked: memory",
            "tool": "mc-tool-memory",
            "pid": 4400,
            "event": "invoked",
            "args": "action='search' query=\"keto recipes\"",
        },
        {
            "ts": _ts(4, 10, 0, 5),
            "level": "error",
            "logger": "invocation",
            "msg": "failed: memory",
            "tool": "mc-tool-memory",
            "pid": 4400,
            "event": "failed",
            "duration_ms": 1042.5,
            "error_type": "ConnectionError",
            "error_message": "bedrock endpoint unreachable",
            "stack": _STACK,
        },
    ]
    lines = [json.dumps(entry) for entry in day4]
    lines.insert(4, "not json {{{")  # malformed line — skipped, never rendered
    active.write_text("\n".join(lines) + "\n")

    day1 = [
        {
            "ts": _ts(1, 9, 0, 0),
            "level": "info",
            "logger": "invocation",
            "msg": "invoked: session_start",
            "tool": "mc-hook-session-start",
            "pid": 3100,
            "event": "invoked",
        },
        {
            "ts": _ts(1, 9, 0, 1),
            "level": "info",
            "logger": "invocation",
            "msg": "completed: session_start",
            "tool": "mc-hook-session-start",
            "pid": 3100,
            "event": "completed",
            "duration_ms": 88.1,
        },
        {
            "ts": _ts(1, 18, 0, 0),
            "level": "warning",
            "logger": "ssl",
            "msg": "TLS verify fell back to the OS trust store",
            "tool": "mc-tool-web-fetch",
            "pid": 3950,
        },
    ]
    (log_dir / "mait-code.jsonl.2026-06-01").write_text(
        "\n".join(json.dumps(entry) for entry in day1) + "\n"
    )
    return active


def test_logs_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the boot view: the newest day expanded with level-coloured rows
    and its error/warning tallies, the older day collapsed behind its counts,
    and the newest line's full record — fields, error message and stack trace
    — in the detail pane."""
    active = _seed_logs(tmp_path)
    assert snap_compare(LogsApp(log_path=active), terminal_size=(120, 40))


def test_logs_empty_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the empty state: no files renders the companion-voice placeholder
    and a zero subtitle, not a crash."""
    active = tmp_path / "logs" / "mait-code.jsonl"  # dir never created
    assert snap_compare(LogsApp(log_path=active), terminal_size=(120, 40))


def test_logs_filter_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the filtered view: ``/`` → board — every day expands to the
    matches and the subtitle reports the narrowed count."""
    active = _seed_logs(tmp_path)

    async def run_before(pilot) -> None:
        await pilot.press("slash")
        await pilot.press(*"board")
        await pilot.pause()

    assert snap_compare(
        LogsApp(log_path=active), run_before=run_before, terminal_size=(120, 40)
    )


def test_logs_level_filter_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the severity floor: four presses of ``l`` cycle to ≥ error, the
    quiet day drops out entirely, and the subtitle carries the floor."""
    active = _seed_logs(tmp_path)

    async def run_before(pilot) -> None:
        await pilot.pause()
        await pilot.press("l", "l", "l", "l")
        await pilot.pause()

    assert snap_compare(
        LogsApp(log_path=active), run_before=run_before, terminal_size=(120, 40)
    )


def test_logs_day_detail_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the day-group detail: cursor on the day node shows the day's
    shape — lines per level and per tool."""
    active = _seed_logs(tmp_path)

    async def run_before(pilot) -> None:
        # Boot lands the cursor on the first leaf via call_after_refresh, so
        # settle first — pressing immediately would race that deferred move.
        await pilot.pause()
        # One step up from the first leaf is its day node.
        await pilot.press("up")
        await pilot.pause()

    assert snap_compare(
        LogsApp(log_path=active), run_before=run_before, terminal_size=(120, 40)
    )
