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

from textual.widgets import Tree

import mait_code.config as config
import mait_code.tui.banner as banner_mod
from mait_code.cli import _permissions as perms
from mait_code.cli._settings_tui import SettingsApp


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


@pytest.fixture(autouse=True)
def _pin_repo_root(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the Tool approvals group at an empty throwaway repo.

    Two kinds of non-determinism to kill. Left alone, ``repo_root()`` resolves
    the checkout the suite is running in, so the group's on/off column would
    mirror whatever the developer has enabled in their own
    ``.claude/settings.local.json`` — green locally, red in CI. And the preset
    pane prints its target file, so the root has to render identically on every
    run: putting it under ``fake_home`` means ``_short_path`` collapses it to
    ``~/pinned-repo/…`` instead of baking in a per-run ``/tmp/pytest-N`` path.
    """
    root = fake_home / "pinned-repo"
    (root / ".git").mkdir(parents=True)
    monkeypatch.setattr(perms, "repo_root", lambda start=None: root)
    return root


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


def test_settings_env_snapshot(
    snap_compare, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Custom env group with a populated [env] table: the row selected,
    its editable value, provenance line, and Apply/Remove buttons."""
    config.write_settings_file({}, env={"AWS_PROFILE": "dev-bedrock"})
    monkeypatch.setattr(config, "_settings_cache", None)

    async def run_before(pilot) -> None:
        await pilot.pause()
        app = pilot.app
        tree = app.query_one("#list", Tree)
        tree.move_cursor(app._setting_nodes["env:AWS_PROFILE"])
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(SettingsApp(), run_before=run_before, terminal_size=(120, 40))


def test_settings_tool_approvals_snapshot(
    snap_compare, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Tool approvals group with a preset selected: its rules, the scope
    picker defaulting to the gitignored project file, and the Enable/Disable
    pair."""
    monkeypatch.setattr(config, "_settings_cache", None)

    async def run_before(pilot) -> None:
        await pilot.pause()
        app = pilot.app
        tree = app.query_one("#list", Tree)
        app._perm_group.expand()
        await pilot.pause()
        tree.move_cursor(app._setting_nodes["perm:git-status"])
        await pilot.pause()
        await pilot.pause()

    assert snap_compare(SettingsApp(), run_before=run_before, terminal_size=(120, 40))
