"""Tests for the shared :class:`~mait_code.tui.app.MaitApp` base.

Theme persistence: the active theme is read from the ``theme`` setting at
startup and written back on exit when it changed, so a Ctrl+P choice survives
restarts. Each test isolates the settings file under a temp ``XDG_CONFIG_HOME``
and resets the config cache (mirroring the ``fake_home`` fixture in
``tests/cli/conftest.py``, which isn't in scope here).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mait_code import config
from mait_code.cli._paths import settings_path
from mait_code.tui.app import MaitApp


def _run(coro_factory):
    return asyncio.run(coro_factory())


@pytest.fixture
def settings_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the settings file into a temp dir and clear the config cache."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("MAIT_CODE_THEME", raising=False)
    monkeypatch.setattr(config, "_settings_cache", None)
    return tmp_path


def _theme_after_boot() -> str:
    app = MaitApp()

    async def scenario() -> str:
        async with app.run_test() as pilot:
            await pilot.pause()
            return app.theme

    return _run(scenario)


def _boot_then_set(theme: str) -> None:
    app = MaitApp()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.theme = theme
            await pilot.pause()

    _run(scenario)


def test_defaults_to_house_theme(settings_home: Path) -> None:
    assert _theme_after_boot() == "mait-dark"


def test_saved_theme_applied_at_startup(settings_home: Path) -> None:
    config.write_settings_file({"theme": "mait-ember"})
    config.reset_cache()
    assert _theme_after_boot() == "mait-ember"


def test_unknown_saved_theme_falls_back(settings_home: Path) -> None:
    config.write_settings_file({"theme": "no-such-theme"})
    config.reset_cache()
    assert _theme_after_boot() == "mait-dark"


def test_house_theme_change_persists_on_exit(settings_home: Path) -> None:
    _boot_then_set("mait-syntax")
    config.reset_cache()
    assert config.read_settings_file().get("theme") == "mait-syntax"
    # And a fresh app restores it.
    assert _theme_after_boot() == "mait-syntax"


def test_builtin_theme_change_persists(settings_home: Path) -> None:
    # "Any registered theme" — a Textual built-in persists too, not just ours.
    _boot_then_set("gruvbox")
    config.reset_cache()
    assert config.read_settings_file().get("theme") == "gruvbox"


def test_unchanged_session_does_not_write_file(settings_home: Path) -> None:
    app = MaitApp()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()  # no theme change

    _run(scenario)
    # Nothing changed, so no settings file should have been created.
    assert not settings_path().exists()
