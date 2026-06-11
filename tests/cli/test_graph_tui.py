"""Tests for the Textual ``mait-code graph`` TUI.

Driven by Textual's headless pilot (``App.run_test()`` wrapped in
``asyncio.run`` — no pytest-asyncio), mirroring the logs TUI tests. The app
takes a ``db_path`` so each scenario points at an isolated seeded database;
the query layer is covered directly in ``test_entities.py``, so here we check
the interaction wiring on top of it: re-centring, the graph ⇄ table toggle,
the deferred graph application, and the zoom workaround.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from netext.textual_widget.widget import GraphView

from mait_code.cli._graph_tui import GraphApp
from tests.cli.test_graph_tui_snapshot import _seed_graph


def test_boot_lands_on_top_hub(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = GraphApp(db_path=_seed_graph(tmp_path), deterministic=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._centre_name() == "alpha"  # top by mention count
            assert app._graph_applied

    asyncio.run(scenario())


def test_filter_and_enter_recentres(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = GraphApp(db_path=_seed_graph(tmp_path), deterministic=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.press(*"wiktor")
            await pilot.pause()
            assert [e["name"] for e in app._entities] == ["wiktor"]
            await pilot.press("enter")
            await pilot.pause()
            assert app._centre_name() == "wiktor"
            assert app._ego is not None
            assert len(app._ego["relationships"]) == 4

    asyncio.run(scenario())


def test_table_row_select_recentres(tmp_path: Path) -> None:
    """Enter on a table row walks the graph to the row's other entity."""

    async def scenario() -> None:
        app = GraphApp(db_path=_seed_graph(tmp_path), deterministic=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._centre_name() == "alpha"
            await pilot.press("t")
            await pilot.pause()
            app.query_one("#table").focus()
            await pilot.press("enter")  # first row: alpha ─depends_on─▶ forge
            await pilot.pause()
            assert app._centre_name() == "forge"

    asyncio.run(scenario())


def test_graph_reapplies_after_hidden_recentre(tmp_path: Path) -> None:
    """A re-centre issued while the table hides the graph still lands.

    netext drops ``set_graph()`` on a zero-sized widget; the app must
    re-apply the held graph when the view becomes visible again.
    """

    async def scenario() -> None:
        app = GraphApp(db_path=_seed_graph(tmp_path), deterministic=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._graph_applied
            await pilot.press("t")  # hide the graph behind the table
            await pilot.pause()
            await pilot.press("slash")
            await pilot.press(*"acme")
            await pilot.pause()
            await pilot.press("enter")  # submit: re-centres and focuses the list
            await pilot.pause()
            assert not app._graph_applied
            await pilot.press("t")  # back to the graph
            await pilot.pause()
            await pilot.pause()
            assert app._graph_applied

    asyncio.run(scenario())


def test_zoom_from_autofit_does_not_crash(tmp_path: Path) -> None:
    """Zoom keys work from the AutoZoom.FIT startup state.

    ``GraphView.zoom`` holds the AutoZoom enum until first numeric
    assignment; a naive ``float(view.zoom)`` zoom step crashes on it.
    """

    async def scenario() -> None:
        # Interactive mode: force layout + auto-fit, like a real launch.
        app = GraphApp(db_path=_seed_graph(tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("plus")
            await pilot.press("minus")
            await pilot.pause()
            assert isinstance(app.query_one(GraphView).zoom, float)

    asyncio.run(scenario())


def test_toggle_all_reveals_orphans(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = GraphApp(db_path=_seed_graph(tmp_path), deterministic=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            names = {e["name"] for e in app._entities}
            assert "dust" not in names  # single mention + orphan
            await pilot.press("a")
            await pilot.pause()
            names = {e["name"] for e in app._entities}
            assert "dust" in names

    asyncio.run(scenario())


def test_list_scroll_recentres_after_debounce(tmp_path: Path) -> None:
    """Resting the list cursor on an entity re-centres without Enter."""

    async def scenario() -> None:
        app = GraphApp(db_path=_seed_graph(tmp_path), deterministic=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._centre_name() == "alpha"
            await pilot.press("down")  # rest on the second entity (wiktor)
            await asyncio.sleep(0.5)  # outlast the debounce
            await pilot.pause()
            assert app._centre_name() == "wiktor"

    asyncio.run(scenario())
