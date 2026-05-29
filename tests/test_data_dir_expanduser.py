"""Regression tests for ``data_dir()`` tilde expansion.

A ``MAIT_CODE_DATA_DIR`` value with a leading ``~`` (e.g. a literal,
unexpanded ``~/.claude/mait-code-data`` from the environment) must resolve to
``$HOME``-relative — not to a stray ``~`` directory under the current working
directory. Before the fix, ``Path(override)`` left the tilde literal, so data
scattered into ``<cwd>/~/.claude/mait-code-data`` and the board/CLI read an
empty database.
"""

from __future__ import annotations

from pathlib import Path

from mait_code import config
from mait_code.cli import _paths


def test_data_dir_expands_leading_tilde(monkeypatch) -> None:
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", "~/.claude/mait-code-data")
    resolved = config.data_dir()
    assert resolved == Path.home() / ".claude" / "mait-code-data"
    assert "~" not in str(resolved)


def test_data_dir_expands_bare_tilde(monkeypatch) -> None:
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", "~")
    assert config.data_dir() == Path.home()


def test_data_dir_absolute_override_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path


def test_paths_data_dir_delegates_and_expands(monkeypatch) -> None:
    # _paths.data_dir() delegates to config.data_dir(), so the fix flows through
    # the single source of truth.
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", "~/.claude/mait-code-data")
    assert _paths.data_dir() == Path.home() / ".claude" / "mait-code-data"


def test_xdg_data_home_expands_tilde(monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "~/somewhere/share")
    assert _paths.xdg_data_home() == Path.home() / "somewhere" / "share"


def test_xdg_config_home_expands_tilde(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "~/somewhere/config")
    assert _paths.xdg_config_home() == Path.home() / "somewhere" / "config"


def test_xdg_state_home_expands_tilde(monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", "~/somewhere/state")
    assert _paths.xdg_state_home() == Path.home() / "somewhere" / "state"
