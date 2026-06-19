"""Tests for the XDG-aware path helpers in ``cli._paths``.

The helpers honour ``$XDG_*`` overrides and otherwise fall back to the
spec defaults under ``~``. The fall-back branches only run when the env
var is absent, so these tests clear it explicitly (the autouse and
``fake_home`` fixtures normally set them).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mait_code.cli import _paths


class TestXdgFallbacks:
    def test_data_home_falls_back_to_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert _paths.xdg_data_home() == tmp_path / ".local" / "share"

    def test_data_home_falls_back_when_blank(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A whitespace-only override is treated as unset.
        monkeypatch.setenv("XDG_DATA_HOME", "   ")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert _paths.xdg_data_home() == tmp_path / ".local" / "share"

    def test_data_home_honours_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert _paths.xdg_data_home() == tmp_path / "xdg"

    def test_state_home_falls_back_to_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert _paths.xdg_state_home() == tmp_path / ".local" / "state"

    def test_state_home_honours_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
        assert _paths.xdg_state_home() == tmp_path / "xdg-state"
