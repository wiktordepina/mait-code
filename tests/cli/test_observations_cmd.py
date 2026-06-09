"""Tests for the ``mait-code observations`` command's non-TTY fallback.

The TUI itself is covered by the snapshot tests; here we only check the
routing — a non-TTY invocation (which is what ``CliRunner`` provides) prints
the day-grouped summary instead of launching Textual.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import mait_code.config as config
from mait_code.cli import app
from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.reflect import update_watermark

runner = CliRunner()


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the data dir at the test tmp path, bypassing the settings cache."""
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings_cache", None)


def _seed(db_path: Path, rows: list[tuple[str, str, str]]) -> None:
    """Insert (content, entry_type, created_at) rows directly."""
    conn = get_connection(db_path)
    try:
        for content, entry_type, created_at in rows:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, created_at)
                   VALUES (?, ?, 5, 'episodic', ?)""",
                (content, entry_type, created_at),
            )
        conn.commit()
    finally:
        conn.close()


def test_observations_empty_store() -> None:
    result = runner.invoke(app, ["observations"])
    assert result.exit_code == 0
    assert "No observations yet." in result.output


def test_observations_day_grouped_summary(tmp_path: Path) -> None:
    _seed(
        tmp_path / "memory.db",
        [
            ("reflected fact", "fact", "2026-06-01 09:00:00"),
            ("pending decision", "decision", "2026-06-02 10:00:00"),
            ("synthesised insight", "insight", "2026-06-02 11:00:00"),
        ],
    )
    conn = get_connection(tmp_path / "memory.db")
    try:
        first_id = conn.execute("SELECT MIN(id) FROM memory_entries").fetchone()[0]
        update_watermark(conn, first_id)
    finally:
        conn.close()

    result = runner.invoke(app, ["observations"])
    assert result.exit_code == 0
    assert "Observations: 1 pending of 2" in result.output
    # Newest day first, pending marked distinctly from reflected.
    assert result.output.index("2026-06-02") < result.output.index("2026-06-01")
    assert "● " in result.output and "· " in result.output
    assert "pending decision" in result.output
    # Insights are reflection output, not observations.
    assert "synthesised insight" not in result.output
