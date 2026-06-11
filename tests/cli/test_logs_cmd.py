"""Tests for the ``mait-code logs`` command's non-TTY fallback.

The TUI itself is covered by the snapshot tests; here we only check the
routing — a non-TTY invocation (which is what ``CliRunner`` provides) prints
the day-grouped summary instead of launching Textual. The root conftest pins
``XDG_STATE_HOME`` under ``tmp_path``, so the summary reads exactly the file
seeded there.
"""

from __future__ import annotations

import calendar
import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mait_code.cli import app

runner = CliRunner()


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


def _ts(y: int, m: int, d: int, hh: int = 0) -> float:
    return float(calendar.timegm((y, m, d, hh, 0, 0, 0, 0, 0)))


def test_logs_empty() -> None:
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "No logs yet." in result.output


def test_logs_day_grouped_summary(tmp_path: Path) -> None:
    log_dir = tmp_path / "xdg-state" / "mait-code"
    log_dir.mkdir(parents=True)
    lines = [
        {"ts": _ts(2026, 6, 1, 9), "level": "info", "msg": "invoked: board"},
        {
            "ts": _ts(2026, 6, 4, 10),
            "level": "error",
            "msg": "failed: memory",
            "tool": "mc-tool-memory",
        },
        {"ts": _ts(2026, 6, 4, 11), "level": "warning", "msg": "slow embed"},
    ]
    (log_dir / "mait-code.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n"
    )

    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "Logs: 3 lines · 1 error" in result.output
    # Newest day first, with its level tallies and the error line surfaced.
    assert result.output.index("2026-06-04") < result.output.index("2026-06-01")
    assert "2026-06-04: 2 lines · 1 warning · 1 error" in result.output
    assert "✗ mc-tool-memory failed: memory" in result.output
