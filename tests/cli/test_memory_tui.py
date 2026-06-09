"""Tests for the Textual ``mait-code memory`` browser.

Driven by Textual's headless pilot (``App.run_test()`` wrapped in
``asyncio.run`` — no pytest-asyncio), mirroring ``test_board_tui.py``. The app
takes a ``db_path`` so each scenario points at an isolated temp store. Entries
are seeded with direct SQL inserts — not ``store_memory`` — so the tests never
touch the embedding path and timestamps stay fixed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rich.text import Text
from textual.widgets import Input, Label, Markdown, Static, Tree

from mait_code.cli._memory_tui import (
    MemoryApp,
    _group_entries,
    _leaf_label,
    _scope_label,
)
from mait_code.tools.memory.db import get_connection


def _run(coro_factory):
    return asyncio.run(coro_factory())


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """An empty temp memory database path."""
    return tmp_path / "memory.db"


def _seed(db_path: Path, entries: list[dict]) -> None:
    """Insert entries (each a dict of overrides) with fixed timestamps.

    Deliberately bypasses ``store_memory``: a direct insert skips dedup and
    embeddings (slow, environment-dependent) and pins ``created_at`` so
    ordering never drifts.
    """
    conn = get_connection(db_path)
    try:
        for spec in entries:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, scope,
                    project, branch, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    spec["content"],
                    spec.get("entry_type", "fact"),
                    spec.get("importance", 5),
                    spec.get("memory_class", "semantic"),
                    spec.get("scope", "global"),
                    spec.get("project"),
                    spec.get("branch"),
                    spec.get("created_at", "2026-06-01 09:00:00"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _group_labels(app: MemoryApp) -> list[str]:
    tree = app.query_one("#list", Tree)
    return [str(node.label) for node in tree.root.children]


def _banner_subtitle(app: MemoryApp) -> str:
    """The masthead's view-name line — where the live match count now lives."""
    return str(app.query_one("#brand-subtitle", Static).render())


class TestUnits:
    def test_leaf_label_uses_first_line_and_date(self) -> None:
        label = _leaf_label(
            {"content": "first line\nsecond line", "created_at": "2026-05-30 10:00:00"}
        )
        assert isinstance(label, Text)
        assert "2026-05-30" in label.plain
        assert "first line" in label.plain
        assert "second line" not in label.plain

    def test_leaf_label_truncates_long_lines(self) -> None:
        label = _leaf_label({"content": "x" * 200, "created_at": "2026-05-30"})
        assert label.plain.endswith("…")
        assert len(label.plain) < 200

    def test_scope_label_variants(self) -> None:
        assert _scope_label({"scope": "global", "project": None, "branch": None}) == (
            "global"
        )
        assert (
            _scope_label({"scope": "project", "project": "demo", "branch": None})
            == "demo"
        )
        assert (
            _scope_label({"scope": "branch", "project": "demo", "branch": "main"})
            == "demo:main"
        )

    def test_group_entries_orders_known_types_then_unknown(self) -> None:
        entries = [
            {"entry_type": "zz-novel", "content": "n"},
            {"entry_type": "event", "content": "e"},
            {"entry_type": "fact", "content": "f"},
        ]
        assert list(_group_entries(entries)) == ["fact", "event", "zz-novel"]


class TestBoot:
    def test_groups_with_counts_in_type_order(self, store_path: Path) -> None:
        _seed(
            store_path,
            [
                {"content": "an event", "entry_type": "event"},
                {"content": "fact one", "entry_type": "fact"},
                {"content": "fact two", "entry_type": "fact"},
                {"content": "likes tea", "entry_type": "preference"},
            ],
        )

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                return _group_labels(app), _banner_subtitle(app)

        labels, sub_title = _run(scenario)
        assert labels == ["fact (2)", "preference (1)", "event (1)"]
        assert "Memory — 4" in sub_title

    def test_first_memory_detail_shown_on_boot(self, store_path: Path) -> None:
        _seed(
            store_path,
            [
                {"content": "older fact", "created_at": "2026-05-01 09:00:00"},
                {"content": "newest fact", "created_at": "2026-06-01 09:00:00"},
            ],
        )

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                body = app.query_one("#detail Markdown", Markdown)
                title = str(app.query_one("#detail .title", Label).render())
                return body.source, title

        body, title = _run(scenario)
        assert body == "newest fact"
        assert "fact" in title

    def test_empty_store_boots_with_message(self, store_path: Path) -> None:
        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                return str(app.query_one("#detail Static", Static).render())

        assert "✦ Nothing remembered yet — we're just getting started." in _run(
            scenario
        )

    def test_detail_metadata_line(self, store_path: Path) -> None:
        _seed(
            store_path,
            [
                {
                    "content": "scoped insight",
                    "entry_type": "insight",
                    "importance": 8,
                    "scope": "project",
                    "project": "demo",
                    "created_at": "2026-05-20 12:00:00",
                }
            ],
        )

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                return str(app.query_one("#detail .help", Label).render())

        meta = _run(scenario)
        assert "created 2026-05-20" in meta
        assert "importance 8" in meta
        assert "scope demo" in meta


class TestFiltering:
    def _seed_mixed(self, store_path: Path) -> None:
        _seed(
            store_path,
            [
                {"content": "uses Terraform for infra", "entry_type": "fact"},
                {"content": "prefers dark themes", "entry_type": "preference"},
                {"content": "Terraform state moved to S3", "entry_type": "decision"},
            ],
        )

    def test_filter_narrows_live_and_expands_groups(self, store_path: Path) -> None:
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("slash")
                await pilot.press(*"terraform")
                await pilot.pause()
                tree = app.query_one("#list", Tree)
                expanded = [n.is_expanded for n in tree.root.children]
                return _group_labels(app), expanded, _banner_subtitle(app)

        labels, expanded, sub_title = _run(scenario)
        assert labels == ["fact (1)", "decision (1)"]
        assert all(expanded)
        assert "Memory — 2/3 match" in sub_title

    def test_filter_is_case_insensitive(self, store_path: Path) -> None:
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#filter", Input).value = "TERRAFORM"
                await pilot.pause()
                return _group_labels(app)

        assert _run(scenario) == ["fact (1)", "decision (1)"]

    def test_filter_refreshes_detail_pane(self, store_path: Path) -> None:
        """The detail pane must follow a rebuild even when the cursor lands on
        the same line index — Tree emits no NodeHighlighted then, so the pane
        went stale (showed the pre-filter memory) until the explicit render."""
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#filter", Input).value = "dark themes"
                await pilot.pause()
                return app.query_one("#detail Markdown", Markdown).source

        assert _run(scenario) == "prefers dark themes"

    def test_no_match_shows_empty_message(self, store_path: Path) -> None:
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one("#filter", Input).value = "kubernetes"
                await pilot.pause()
                return str(app.query_one("#detail Static", Static).render())

        assert "✦ I don't remember anything matching 'kubernetes'." in _run(scenario)

    def test_clearing_filter_restores_all_groups(self, store_path: Path) -> None:
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                filter_input = app.query_one("#filter", Input)
                filter_input.value = "terraform"
                await pilot.pause()
                filter_input.value = ""
                await pilot.pause()
                return _group_labels(app), _banner_subtitle(app)

        labels, sub_title = _run(scenario)
        assert labels == ["fact (1)", "preference (1)", "decision (1)"]
        assert "Memory — 3" in sub_title

    def test_enter_in_filter_moves_focus_to_list(self, store_path: Path) -> None:
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("slash")
                await pilot.press(*"terraform")
                await pilot.press("enter")
                await pilot.pause()
                return app.focused is app.query_one("#list", Tree)

        assert _run(scenario) is True

    def test_escape_from_filter_returns_to_list(self, store_path: Path) -> None:
        self._seed_mixed(store_path)

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("slash")  # focus the filter
                await pilot.pause()
                await pilot.press("escape")  # steps back to the list, not quit
                await pilot.pause()
                return app.focused is app.query_one("#list", Tree), app.is_running

        on_list, running = _run(scenario)
        assert on_list and running

    def test_escape_on_list_quits(self, store_path: Path, monkeypatch) -> None:
        self._seed_mixed(store_path)
        calls: list[bool] = []

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()  # the tree holds focus on boot
                monkeypatch.setattr(app, "exit", lambda *a, **k: calls.append(True))
                await pilot.press("escape")  # nothing to back out of → quit
                await pilot.pause()

        _run(scenario)
        assert calls == [True]


class TestReload:
    def test_reload_picks_up_new_entries(self, store_path: Path) -> None:
        _seed(store_path, [{"content": "first"}])

        async def scenario():
            app = MemoryApp(db_path=store_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                before = _group_labels(app)
                _seed(store_path, [{"content": "second"}])
                await pilot.press("r")
                await pilot.pause()
                return before, _group_labels(app)

        before, after = _run(scenario)
        assert before == ["fact (1)"]
        assert after == ["fact (2)"]
