"""Snapshot test locking the settings TUI's visual output (A1 retrofit).

Renders the settings editor at a fixed terminal size against an accepted SVG
baseline under ``__snapshots__/``.

Determinism matters here: the settings list shows each value's *source*
(env / default / derived). A dev shell exports ``MAIT_CODE_*`` vars that a clean
CI runner doesn't, which would flip the Source column. The root
``_isolate_mait_settings`` autouse fixture clears every ``MAIT_CODE_*`` var,
pinning each row to its ``default`` (or ``derived``) source. ``fake_home`` keeps
the value column on the literal ``~/…`` defaults rather than expanded tmp paths.

Regenerate the baseline intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_settings_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mait_code.config as config
import mait_code.tui.banner as banner_mod
from mait_code.cli._settings_tui import SettingsApp


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def test_settings_snapshot(
    snap_compare, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The root ``_isolate_mait_settings`` autouse fixture already clears every
    # inherited ``MAIT_CODE_*`` var, pinning each row to its default source.
    monkeypatch.setattr(config, "_settings_cache", None)
    assert snap_compare(SettingsApp(), terminal_size=(120, 40))


def test_settings_editor_snapshot(
    snap_compare, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adaptive editor on an enum setting: one step down from ``data-dir``
    lands on ``theme``, whose editor is a radio set of the installed themes."""
    monkeypatch.setattr(config, "_settings_cache", None)
    assert snap_compare(SettingsApp(), press=["down"], terminal_size=(120, 40))
