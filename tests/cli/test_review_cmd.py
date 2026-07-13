"""Tests for the ``mait-code review`` command's non-TTY fallback.

The TUI itself is covered in ``test_review_tui.py``; here we only check the
routing — a non-TTY invocation (which is what ``CliRunner`` provides) prints
the due-for-review list as text instead of launching Textual.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import mait_code.config as config
from mait_code.cli import app
from mait_code.tools.memory.db import get_connection

runner = CliRunner()


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the data dir at the test tmp path, bypassing the settings cache."""
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings_cache", None)


def _seed(db_path: Path, rows: list[tuple[str, int, str, str]]) -> None:
    """Insert (content, importance, memory_class, reviewed_at) rows directly."""
    conn = get_connection(db_path)
    try:
        for content, importance, mclass, reviewed in rows:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class,
                    created_at, reviewed_at)
                   VALUES (?, 'fact', ?, ?, ?, ?)""",
                (content, importance, mclass, reviewed, reviewed),
            )
        conn.commit()
    finally:
        conn.close()


def test_review_empty_store() -> None:
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0
    assert "Nothing due for review" in result.output


def test_review_lists_due(tmp_path: Path) -> None:
    _seed(
        tmp_path / "memory.db",
        [
            # Episodic, reviewed long ago → far past the 3-day half-life → due.
            ("stale but important fact", 8, "episodic", "2020-01-01 00:00:00"),
            # Trivia below the importance floor → must not surface.
            ("trivia that can decay", 2, "episodic", "2020-01-01 00:00:00"),
        ],
    )
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0
    assert "Due for review:" in result.output
    assert "stale but important fact" in result.output
    assert "trivia that can decay" not in result.output
