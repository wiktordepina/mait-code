"""Snapshot tests locking the memory browser's visual output.

Renders a seeded store at a fixed terminal size against accepted SVG baselines
under ``__snapshots__/``. Entries are seeded with direct SQL inserts (fixed
timestamps, no embedding path), so ordering and dates never drift; the theme is
the ``mait-dark`` default applied by :class:`~mait_code.tui.app.MaitApp`.

Regenerate the baselines intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_memory_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

from mait_code.cli._memory_tui import MemoryApp
from mait_code.tools.memory.db import get_connection


def _seed_store(db_path: Path) -> None:
    """A small store spanning several types for the shots.

    The newest fact carries markdown (heading, list, inline code) so the boot
    shot — which lands on it — doubles as the markdown-rendering shot.
    """
    conn = get_connection(db_path)
    try:
        rows = [
            # (content, entry_type, importance, memory_class, scope, project, created_at)
            (
                "## Home server\n\n"
                "The CI/CD pipeline runs on the home server:\n\n"
                "- builds in `Docker`, deployed with **Ansible**\n"
                "- state lives in Terraform Cloud\n",
                "fact",
                7,
                "semantic",
                "global",
                None,
                "2026-06-01 09:00:00",
            ),
            (
                "Cody's morning walk comes before the first coffee.",
                "fact",
                4,
                "semantic",
                "global",
                None,
                "2026-05-28 08:00:00",
            ),
            (
                "Prefers Textual TUIs over questionary prompt sequences "
                "for interactive CLI surfaces.",
                "preference",
                8,
                "semantic",
                "global",
                None,
                "2026-05-30 10:00:00",
            ),
            (
                "British English spelling in docs and commit messages.",
                "preference",
                6,
                "semantic",
                "global",
                None,
                "2026-05-21 12:00:00",
            ),
            (
                "Moved the board's blocked column to a tags system.",
                "decision",
                7,
                "semantic",
                "project",
                "mait-code",
                "2026-05-26 15:00:00",
            ),
            (
                "Released 0.43.0 — removed the tasks subsystem.",
                "event",
                5,
                "episodic",
                "project",
                "mait-code",
                "2026-06-04 17:00:00",
            ),
        ]
        for content, entry_type, importance, memory_class, scope, project, ts in rows:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, scope,
                    project, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (content, entry_type, importance, memory_class, scope, project, ts),
            )
        conn.commit()
    finally:
        conn.close()


def test_memory_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the boot view: grouped tree with counts (first group expanded,
    the rest collapsed), the newest memory's markdown body in the detail
    pane, and the count subtitle."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)
    assert snap_compare(MemoryApp(db_path=db_path), terminal_size=(120, 40))


def test_memory_filter_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the filtered view: ``/`` → type — groups expand to the matches and
    the subtitle reports the narrowed count."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)

    async def run_before(pilot) -> None:
        await pilot.press("slash")
        await pilot.press(*"prefers")
        await pilot.pause()

    assert snap_compare(
        MemoryApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_memory_help_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the shared help screen over the browser (keys + descriptions)."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)
    assert snap_compare(
        MemoryApp(db_path=db_path),
        press=["question_mark"],
        terminal_size=(120, 40),
    )
