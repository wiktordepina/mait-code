"""Tests for :mod:`mait_code.cli._logs` — the JSONL log read-side helpers.

Timestamps are written and asserted in UTC (the ``TZ`` fixture pins the
process zone), since :func:`entry_day` / :func:`entry_time` render local time.
"""

from __future__ import annotations

import calendar
import json
import os
import time
from pathlib import Path

import pytest

from mait_code.cli._logs import (
    entry_day,
    entry_time,
    group_by_day,
    level_at_least,
    level_counts,
    log_files,
    read_log_entries,
)


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


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> float:
    """An epoch timestamp for a UTC wall-clock moment."""
    return float(calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0)))


def _line(**fields: object) -> str:
    return json.dumps(fields)


def _entry(ts: float, level: str = "info", **fields: object) -> dict:
    entry: dict = {
        "ts": ts,
        "level": level,
        "logger": "",
        "msg": "",
        "tool": "",
        "pid": None,
    }
    entry.update(fields)
    return entry


# -- log_files -------------------------------------------------------------


def test_log_files_nothing_on_disk(tmp_path: Path) -> None:
    assert log_files(tmp_path / "mait-code.jsonl") == []


def test_log_files_active_plus_rotated_newest_first(tmp_path: Path) -> None:
    active = tmp_path / "mait-code.jsonl"
    active.write_text("")
    old = tmp_path / "mait-code.jsonl.2026-06-01"
    old.write_text("")
    new = tmp_path / "mait-code.jsonl.2026-06-03"
    new.write_text("")
    assert log_files(active) == [active, new, old]


def test_log_files_ignores_non_rotation_suffixes(tmp_path: Path) -> None:
    active = tmp_path / "mait-code.jsonl"
    active.write_text("")
    (tmp_path / "mait-code.jsonl.bak").write_text("")
    (tmp_path / "mait-code.jsonl.2026-06-01").mkdir()  # a dir, not a log
    assert log_files(active) == [active]


def test_log_files_rotated_survive_missing_active(tmp_path: Path) -> None:
    """After a midnight rotation with nothing yet written today, the rotated
    files are still the history."""
    active = tmp_path / "mait-code.jsonl"
    rotated = tmp_path / "mait-code.jsonl.2026-06-01"
    rotated.write_text("")
    assert log_files(active) == [rotated]


# -- read_log_entries --------------------------------------------------------


def test_read_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text(
        "\n".join(
            [
                _line(ts=_ts(2026, 6, 4), level="info", msg="good"),
                "",
                "not json {{{",
                '"a scalar"',
                "[1, 2]",
                '{"ts": "not-a-number", "msg": "still kept"}',
            ]
        )
    )
    entries, clipped = read_log_entries([path])
    assert [e["msg"] for e in entries] == ["good", "still kept"]
    assert entries[1]["ts"] == 0.0  # unparseable ts coerced, line kept
    assert clipped is False


def test_read_normalises_missing_core_fields(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text("{}")
    entries, _ = read_log_entries([path])
    assert entries == [
        {"ts": 0.0, "level": "info", "logger": "", "msg": "", "tool": "", "pid": None}
    ]


def test_read_keeps_extra_fields_and_sorts_newest_first(tmp_path: Path) -> None:
    active = tmp_path / "log.jsonl"
    active.write_text(
        _line(ts=_ts(2026, 6, 4, 10), msg="new", event="invoked", duration_ms=1.5)
    )
    rotated = tmp_path / "log.jsonl.2026-06-01"
    rotated.write_text(_line(ts=_ts(2026, 6, 1, 9), msg="old"))
    entries, _ = read_log_entries([active, rotated])
    assert [e["msg"] for e in entries] == ["new", "old"]
    assert entries[0]["event"] == "invoked"
    assert entries[0]["duration_ms"] == 1.5


def test_read_clips_to_the_file_tail(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(_line(ts=float(i), msg=f"line {i}") for i in range(5)))
    entries, clipped = read_log_entries([path], max_lines_per_file=2)
    assert clipped is True
    assert [e["msg"] for e in entries] == ["line 4", "line 3"]  # the newest tail


def test_read_missing_file_is_skipped(tmp_path: Path) -> None:
    assert read_log_entries([tmp_path / "gone.jsonl"]) == ([], False)


# -- grouping & levels ---------------------------------------------------------


def test_entry_day_and_time_render_local_time() -> None:
    entry = _entry(_ts(2026, 6, 4, 9, 30, 5))
    assert entry_day(entry) == "2026-06-04"
    assert entry_time(entry) == "09:30:05"


def test_group_by_day_newest_day_first() -> None:
    old = _entry(_ts(2026, 6, 1, 8))
    new = _entry(_ts(2026, 6, 4, 9))
    grouped = group_by_day([new, old])
    assert list(grouped) == ["2026-06-04", "2026-06-01"]
    assert grouped["2026-06-04"] == [new]


def test_level_at_least_orders_severities() -> None:
    assert level_at_least("error", "warning")
    assert level_at_least("warning", "warning")
    assert not level_at_least("debug", "info")


def test_level_at_least_unknown_levels_read_as_info() -> None:
    assert level_at_least("trace", "info")
    assert not level_at_least("trace", "warning")
    assert level_at_least("warning", "bogus-minimum")


def test_level_counts_includes_zeros_and_buckets_unknown_as_info() -> None:
    entries = [
        _entry(0.0, "error"),
        _entry(0.0, "trace"),
        _entry(0.0, "info"),
    ]
    assert level_counts(entries) == {
        "debug": 0,
        "info": 2,
        "warning": 0,
        "error": 1,
    }
