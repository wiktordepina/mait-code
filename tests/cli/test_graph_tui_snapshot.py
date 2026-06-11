"""Snapshot tests locking the graph explorer's visual output.

Renders a seeded entity graph at a fixed terminal size against accepted SVG
baselines under ``__snapshots__/``. Entities and relationships are seeded with
direct SQL inserts (fixed timestamps), and the app runs in ``deterministic``
mode: the Sugiyama layout engine at a fixed zoom, because netext's
force-directed engine is unseeded and lays the same graph out differently on
every run.

Regenerate the baselines intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_graph_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mait_code.tui.banner as banner_mod
from mait_code.cli._graph_tui import GraphApp
from mait_code.tools.memory.db import get_connection


@pytest.fixture(autouse=True)
def _pin_banner_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the masthead version so the brand banner stays release-stable."""
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


_ENTITIES = [
    # (id, name, entity_type, mention_count) — wiktor is the hub.
    (1, "wiktor", "person", 9),
    (2, "alpha", "project", 12),
    (3, "beta", "project", 7),
    (4, "hammer", "tool", 5),
    (5, "forge", "service", 4),
    (6, "ontology", "concept", 3),
    (7, "acme", "org", 2),
    (8, "chisel", "tool", 2),
    (9, "dust", "concept", 1),  # single mention + orphan: hidden by default
]

_RELATIONSHIPS = [
    # (source, target, type, context)
    (1, 2, "owns", "wiktor owns and develops alpha"),
    (1, 3, "owns", "wiktor maintains beta on the side"),
    (1, 4, "uses", "hammer is the daily driver"),
    (2, 5, "depends_on", "alpha deploys onto forge"),
    (2, 6, "related_to", "alpha implements the ontology"),
    (3, 5, "depends_on", "beta shares the forge deployment"),
    (7, 1, "manages", "acme employs wiktor"),
    (8, 2, "contributes_to", "chisel carves alpha's assets"),
]


def _seed_graph(tmp_path: Path) -> Path:
    """A small, fixed graph: stable ids, types, and timestamps throughout."""
    db_path = tmp_path / "memory.db"
    conn = get_connection(db_path)
    conn.executemany(
        """INSERT INTO memory_entities
               (id, name, entity_type, mention_count, first_seen, last_seen)
           VALUES (?, ?, ?, ?, '2026-04-01 09:00:00', '2026-06-01 09:00:00')""",
        _ENTITIES,
    )
    conn.executemany(
        """INSERT INTO memory_relationships
               (source_entity_id, target_entity_id, relationship_type, context,
                first_seen, last_seen)
           VALUES (?, ?, ?, ?, '2026-04-01 09:00:00', '2026-06-01 09:00:00')""",
        _RELATIONSHIPS,
    )
    conn.commit()
    conn.close()
    return db_path


def test_graph_view_default(snap_compare, tmp_path: Path) -> None:
    """Boot view: list lands on the top hub, graph pane shows its ego graph."""
    db_path = _seed_graph(tmp_path)
    assert snap_compare(
        GraphApp(db_path=db_path, deterministic=True),
        terminal_size=(120, 40),
    )


def test_table_view(snap_compare, tmp_path: Path) -> None:
    """The flat relationship table: glyphs, arrows, clipped context."""
    db_path = _seed_graph(tmp_path)
    assert snap_compare(
        GraphApp(db_path=db_path, deterministic=True),
        press=["t"],
        terminal_size=(120, 40),
    )


def test_recentre_from_list(snap_compare, tmp_path: Path) -> None:
    """Filtering and selecting an entity re-centres both views on it."""
    db_path = _seed_graph(tmp_path)

    async def run_before(pilot) -> None:
        await pilot.press("slash")
        await pilot.press(*"wiktor")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        GraphApp(db_path=db_path, deterministic=True),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_show_all_reveals_noise(snap_compare, tmp_path: Path) -> None:
    """`a` lifts the noise filter: the orphan single-mention entity appears."""
    db_path = _seed_graph(tmp_path)
    assert snap_compare(
        GraphApp(db_path=db_path, deterministic=True),
        press=["a"],
        terminal_size=(120, 40),
    )


def test_empty_store(snap_compare, tmp_path: Path) -> None:
    """A fresh database renders the empty state, not a crash."""
    db_path = tmp_path / "memory.db"
    conn = get_connection(db_path)
    conn.close()
    assert snap_compare(
        GraphApp(db_path=db_path, deterministic=True),
        terminal_size=(120, 40),
    )
