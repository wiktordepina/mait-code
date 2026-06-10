"""Snapshot tests locking the memory browser's visual output.

Renders a seeded store at a fixed terminal size against accepted SVG baselines
under ``__snapshots__/``. Entries are seeded with direct SQL inserts (fixed
timestamps, no embedding path), so ordering and dates never drift; the theme is
the ``mait-dark`` default applied by :class:`~mait_code.tui.app.MaitApp`.

Regenerate the baselines intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_memory_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import mait_code.cli._memory_tui as memory_tui_mod
import mait_code.tui.banner as banner_mod
from mait_code.cli._memory_tui import MemoryApp
from mait_code.tools.memory import native as native_mod
from mait_code.tools.memory.db import get_connection

#: Fixed mtime for seeded native files: 2026-06-01 00:00 UTC.
_NATIVE_MTIME = 1780272000


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def _seed_native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake Claude Code projects tree spanning two projects.

    Builds munged slug dirs with memory files *and* the matching source
    directories under ``tmp_path/src``, then points the TUI's scan at that
    root so labels resolve — ``beta-tui`` exercises the dashed-leaf
    backtracking. File mtimes are pinned so the date column never drifts.
    """
    src = tmp_path / "src"
    projects_dir = tmp_path / "claude-projects"
    seeds = {
        "alpha": {
            "MEMORY.md": (
                "# Memory — alpha\n\n"
                "## Project\n\n"
                "- Auth service signs JWTs with `RS256`\n"
                "- Deploys ride the **home server** pipeline\n"
            ),
            "auth-flow.md": "Token refresh runs every 15 minutes.\n",
        },
        "beta-tui": {
            "MEMORY.md": "# Memory — beta-tui\n\nPalette lives in `theme.py`.\n",
            "palette.md": "Drive colours off theme $-variables.\n",
            "snapshot-testing.md": "Eyeball SVG baselines before accepting.\n",
        },
    }
    for rel, files in seeds.items():
        source = src / rel
        source.mkdir(parents=True)
        slug = "-" + str(source.relative_to(src)).replace("/", "-")
        memory_dir = projects_dir / slug / "memory"
        memory_dir.mkdir(parents=True)
        for name, content in files.items():
            target = memory_dir / name
            target.write_text(content)
            os.utime(target, (_NATIVE_MTIME, _NATIVE_MTIME))
    monkeypatch.setattr(
        memory_tui_mod,
        "list_native_memories",
        lambda projects: native_mod.list_native_memories(projects, root=src),
    )
    return projects_dir


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
                "To regenerate reference docs: run `docs/gen_ref_pages.py`, "
                "then commit the result alongside the code.",
                "procedure",
                6,
                "procedural",
                "project",
                "mait-code",
                "2026-05-29 11:00:00",
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


def test_memory_project_filter_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the store view narrowed by ``p``: the Select picks ``mait-code``,
    the tree keeps that project's entries plus globals, the subtitle carries
    the project name."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)

    async def run_before(pilot) -> None:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        # The Select opens expanded on "All projects"; one step down lands on
        # the sole project and enter applies it, dismissing the modal.
        await pilot.press("down", "enter")
        await pilot.pause()

    assert snap_compare(
        MemoryApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_memory_native_snapshot(
    snap_compare, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock the native view's boot shot: ``n`` → projects grouped with file
    counts (first expanded, cursor on its MEMORY.md), the file's markdown in
    the detail pane, the native subtitle, and the footer's Store binding."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)
    projects_dir = _seed_native(tmp_path, monkeypatch)

    async def run_before(pilot) -> None:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

    assert snap_compare(
        MemoryApp(db_path=db_path, native_dir=projects_dir),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_memory_native_project_filter_snapshot(
    snap_compare, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock the native view narrowed to one project via ``p``: only
    ``beta-tui`` survives, expanded, with the subtitle carrying its name."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)
    projects_dir = _seed_native(tmp_path, monkeypatch)

    async def run_before(pilot) -> None:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        # Options run All projects → alpha → beta-tui; two steps + enter.
        await pilot.press("down", "down", "enter")
        await pilot.pause()

    assert snap_compare(
        MemoryApp(db_path=db_path, native_dir=projects_dir),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_memory_native_empty_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the native view's empty state: no projects dir at all — the tree
    empties and the detail pane explains rather than crashes."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)
    assert snap_compare(
        MemoryApp(db_path=db_path, native_dir=tmp_path / "nowhere"),
        press=["n"],
        terminal_size=(120, 40),
    )
