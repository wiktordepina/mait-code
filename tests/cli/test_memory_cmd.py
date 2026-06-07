"""Tests for the ``mait-code memory`` command's non-TTY fallback.

The TUI itself is covered in ``test_memory_tui.py``; here we only check the
routing — a non-TTY invocation (which is what ``CliRunner`` provides) prints
the read-only grouped summary instead of launching Textual.
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


def _seed(db_path: Path, rows: list[tuple[str, str]]) -> None:
    """Insert (content, entry_type) rows directly — no embedding path."""
    conn = get_connection(db_path)
    try:
        for content, entry_type in rows:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, created_at)
                   VALUES (?, ?, 5, 'semantic', '2026-06-01 09:00:00')""",
                (content, entry_type),
            )
        conn.commit()
    finally:
        conn.close()


def test_memory_empty_store() -> None:
    result = runner.invoke(app, ["memory"])
    assert result.exit_code == 0
    assert "No memories stored yet." in result.output


def test_memory_grouped_summary(tmp_path: Path) -> None:
    _seed(
        tmp_path / "memory.db",
        [
            ("uses Terraform", "fact"),
            ("likes whippets", "fact"),
            ("dark themes", "preference"),
        ],
    )
    result = runner.invoke(app, ["memory"])
    assert result.exit_code == 0
    assert "fact (2):" in result.output
    assert "preference (1):" in result.output
    assert "uses Terraform" in result.output
