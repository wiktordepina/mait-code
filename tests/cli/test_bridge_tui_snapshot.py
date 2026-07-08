"""Snapshot test locking the Bridge editor's visual output.

Renders the Bridge form at a fixed terminal size against an accepted SVG
baseline under ``__snapshots__/``. The root ``_isolate_mait_settings`` autouse
fixture clears every ``MAIT_CODE_*`` var, so the gate renders in its default
(disabled) state and the ntfy fields show their placeholders.

Regenerate the baseline intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_bridge_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mait_code.tui.banner as banner_mod
from mait_code.cli._bridge_tui import BridgeApp


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def test_bridge_snapshot(snap_compare, fake_home: Path) -> None:
    assert snap_compare(BridgeApp(), terminal_size=(120, 40))
