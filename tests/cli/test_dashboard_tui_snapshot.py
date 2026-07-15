"""Snapshot tests locking the start-page setup editor's visual output.

Environment-dependent chrome is pinned (version via the shared banner module,
the config path at a per-test file) and the stores are seeded through the same
connections the app reads, so the widget preview renders stable content.

Regenerate intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_dashboard_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mait_code.cli._dashboard as dashboard_mod
import mait_code.tui.banner as banner_mod
from mait_code.cli._dashboard_tui import DashboardSetupApp


@pytest.fixture(autouse=True)
def _pin_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")
    path = tmp_path / "dashboard.toml"
    path.write_text(
        "columns = 2\n"
        '[[tile]]\nwidget = "board"\ntitle = "What\'s cooking"\n'
        '[[tile]]\ncommand = "uptime"\ntitle = "Home server"\nspan = 2\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_mod, "dashboard_path", lambda: path)


def _seed_board() -> None:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection

    conn = get_connection()
    try:
        wid = service.add_card(conn, project="demo", title="Work the thing")
        service.move_card(conn, wid, "in_progress")
        service.add_card(conn, project="demo", title="Wire up the widget")
    finally:
        conn.close()


def test_setup_widget_tile_snapshot(snap_compare) -> None:
    """Lock the editor on a widget tile: the tile list, the form with the
    widget picker shown (command input hidden), and the live board preview."""
    _seed_board()
    assert snap_compare(DashboardSetupApp(), terminal_size=(120, 40))


def test_setup_command_tile_snapshot(snap_compare) -> None:
    """Lock the editor on a command tile: the command input shown, and the
    preview holding the run-it-yourself hint rather than any output."""
    _seed_board()

    async def run_before(pilot) -> None:
        await pilot.pause()
        pilot.app._select(1)
        await pilot.pause()

    assert snap_compare(
        DashboardSetupApp(), run_before=run_before, terminal_size=(120, 40)
    )
