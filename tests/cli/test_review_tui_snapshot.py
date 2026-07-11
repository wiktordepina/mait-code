"""Snapshot tests locking the review TUI's visual output.

Renders a seeded store at a fixed terminal size against accepted SVG baselines
under ``__snapshots__/``. Entries are seeded with direct SQL inserts at fixed
review anchors, and the app is given a pinned ``now``, so the due set, its
ordering and its recall figures never drift; the theme is the ``mait-dark``
default applied by :class:`~mait_code.tui.app.MaitApp`.

These baselines feed ``docs/gen_review_screenshots.py`` — regenerate them
intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_review_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import mait_code.tui.banner as banner_mod
from mait_code.cli._review_tui import ReviewApp
from mait_code.tools.memory.db import get_connection

#: The pinned clock the queue's recall is measured against.
NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def _seed_due(db_path: Path) -> None:
    """A handful of due memories spanning types, classes and scopes.

    Review anchors are old enough (against ``NOW``) that each has decayed past
    the 0.5 threshold, so all appear in the queue; the mix of importances,
    classes and one project scope keeps the detail pane representative.
    """
    conn = get_connection(db_path)
    try:
        rows = [
            # (content, entry_type, importance, memory_class, scope, project, reviewed_at)
            (
                "Fixed a race condition in the observation cursor handling",
                "event",
                6,
                "episodic",
                "global",
                None,
                "2026-06-20 00:00:00",
            ),
            (
                "Prefers explicit tolerance comparisons over pytest.approx in "
                "typed code, to keep pyright happy.",
                "preference",
                8,
                "semantic",
                "global",
                None,
                "2026-01-05 00:00:00",
            ),
            (
                "To debug a failing pages deploy: check the env protection "
                "rules first, then the tag ref.",
                "procedure",
                7,
                "procedural",
                "global",
                None,
                "2025-11-01 00:00:00",
            ),
            (
                "Chose install.sh + symlinks over plugin packaging for "
                "distribution — keeps the multi-harness door open.",
                "decision",
                9,
                "semantic",
                "project",
                "mait-code",
                "2026-02-10 00:00:00",
            ),
        ]
        for content, etype, importance, mclass, scope, project, reviewed in rows:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, scope,
                    project, created_at, reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    content,
                    etype,
                    importance,
                    mclass,
                    scope,
                    project,
                    reviewed,
                    reviewed,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_review_snapshot(snap_compare, tmp_path: Path) -> None:
    """Boot view: the due queue with recall badges, first memory's detail."""
    db_path = tmp_path / "memory.db"
    _seed_due(db_path)
    assert snap_compare(ReviewApp(db_path=db_path, now=NOW), terminal_size=(120, 40))


def test_review_refine_snapshot(snap_compare, tmp_path: Path) -> None:
    """The refine modal: the highlighted memory prefilled in the editor."""
    db_path = tmp_path / "memory.db"
    _seed_due(db_path)

    async def run_before(pilot) -> None:
        await pilot.press("e")  # open the refine editor on the first memory
        await pilot.pause()

    assert snap_compare(
        ReviewApp(db_path=db_path, now=NOW),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_review_empty_snapshot(snap_compare, tmp_path: Path) -> None:
    """Nothing due: the all-caught-up empty state."""
    db_path = tmp_path / "memory.db"
    get_connection(db_path).close()  # schema only, no entries
    assert snap_compare(ReviewApp(db_path=db_path, now=NOW), terminal_size=(120, 40))


def test_review_help_snapshot(snap_compare, tmp_path: Path) -> None:
    """The key cheat-sheet."""
    db_path = tmp_path / "memory.db"
    _seed_due(db_path)
    assert snap_compare(
        ReviewApp(db_path=db_path, now=NOW),
        press=["question_mark"],
        terminal_size=(120, 40),
    )
