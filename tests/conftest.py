"""Root test configuration. Fixtures live in tool-specific conftest files."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_mait_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop tests from reading the developer's real mait-code settings file.

    ``config.resolve`` / ``collect_settings`` read ``$XDG_CONFIG_HOME/
    mait-code/settings.toml`` (cached at module level). Without isolation a
    real settings file on the dev's machine bleeds in, so "unset → default"
    assertions flip to ``source == "settings"``. Point ``XDG_CONFIG_HOME`` at
    a throwaway dir and clear the cache before every test; tests that need a
    settings file (e.g. ``fake_home``) override this afterwards.
    """
    import mait_code.config as _config

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setattr(_config, "_settings_cache", None)
