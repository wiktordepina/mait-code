"""Snapshot tests locking the observations browser's visual output.

Renders a seeded store at a fixed terminal size against accepted SVG baselines
under ``__snapshots__/``. Entries are seeded with direct SQL inserts (fixed
timestamps, no embedding path) and the reflection watermark is set explicitly,
so the pending/reflected split never drifts; the theme is the ``mait-dark``
default applied by :class:`~mait_code.tui.app.MaitApp`.

Regenerate the baselines intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_observations_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mait_code.tui.banner as banner_mod
from mait_code.cli._observations_tui import ObservationsApp
from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.reflect import update_watermark


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def _seed_store(db_path: Path) -> None:
    """Two capture days for the shots: a fully-reflected older day (collapses
    behind its count) and a newer day with a pending backlog (expands, cursor
    lands on its newest entry — whose markdown body doubles as the
    markdown-rendering shot)."""
    conn = get_connection(db_path)
    try:
        rows = [
            # (content, entry_type, importance, scope, project, created_at)
            (
                "Switched the home server's reverse proxy to Caddy.",
                "decision",
                6,
                "global",
                None,
                "2026-06-01 09:00:00",
            ),
            (
                "Prefers conventional commits with no attribution footer.",
                "preference",
                7,
                "global",
                None,
                "2026-06-01 12:00:00",
            ),
            (
                "Fixed the tilde-expansion bug in the reminders tool.",
                "event",
                5,
                "project",
                "mait-code",
                "2026-06-04 10:00:00",
            ),
            (
                "## Observations browser\n\n"
                "The fifth TUI surface makes the raw tier visible:\n\n"
                "- pending entries judged against the `reflection_watermark`\n"
                "- capture batches read from the daily **JSONL** logs\n",
                "fact",
                7,
                "project",
                "mait-code",
                "2026-06-04 15:00:00",
            ),
        ]
        for content, entry_type, importance, scope, project, ts in rows:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, scope,
                    project, created_at)
                   VALUES (?, ?, ?, 'episodic', ?, ?, ?)""",
                (content, entry_type, importance, scope, project, ts),
            )
        conn.commit()
        # Global watermark after the first day: 2026-06-01 reads reflected,
        # 2026-06-04 reads pending.
        second_id = conn.execute(
            "SELECT id FROM memory_entries ORDER BY id LIMIT 1 OFFSET 1"
        ).fetchone()[0]
        update_watermark(conn, second_id)
    finally:
        conn.close()


def test_observations_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the boot view: the pending day expanded with warning markers and a
    "2 pending" badge, the reflected day collapsed behind its count, the
    newest observation's markdown body in the detail pane, and the pending
    tally in the masthead subtitle."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)
    assert snap_compare(ObservationsApp(db_path=db_path), terminal_size=(120, 40))


def test_observations_empty_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the empty state: a fresh store renders the companion-voice
    placeholder and a zero subtitle, not a crash."""
    db_path = tmp_path / "memory.db"
    conn = get_connection(db_path)  # creates the schema, stores nothing
    conn.close()
    assert snap_compare(ObservationsApp(db_path=db_path), terminal_size=(120, 40))


def test_observations_filter_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the filtered view: ``/`` → type — every day expands to the matches
    and the subtitle reports the narrowed count."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)

    async def run_before(pilot) -> None:
        await pilot.press("slash")
        await pilot.press(*"reminders")
        await pilot.pause()

    assert snap_compare(
        ObservationsApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_observations_day_detail_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the day-group detail: cursor on the day node shows the observation
    count and the day's capture sessions read from its JSONL log (the root
    conftest pins ``MAIT_CODE_DATA_DIR`` to ``tmp_path/"data"``, so the log
    seeded there is exactly what the app reads)."""
    db_path = tmp_path / "memory.db"
    _seed_store(db_path)

    obs_dir = tmp_path / "data" / "memory" / "observations"
    obs_dir.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-04T09:42:00+00:00",
            "trigger": "precompact",
            "project": "mait-code",
            "branch": "main",
            "extraction": {
                "facts": [{"content": "a"}],
                "entities": [{"name": "x"}, {"name": "y"}],
            },
        },
        {
            "timestamp": "2026-06-04T17:05:00+00:00",
            "trigger": "session-end",
            "project": "mait-code",
            "branch": "main",
            "extraction": {
                "decisions": [{"content": "b"}, {"content": "c"}],
                "bugs_fixed": [{"content": "d"}],
            },
        },
    ]
    (obs_dir / "2026-06-04.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )

    async def run_before(pilot) -> None:
        # Boot lands the cursor on the first leaf via call_after_refresh, so
        # settle first — pressing immediately would race that deferred move.
        await pilot.pause()
        # One step up from the first leaf is its day node.
        await pilot.press("up")
        await pilot.pause()

    assert snap_compare(
        ObservationsApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )
