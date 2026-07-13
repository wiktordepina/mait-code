"""Tests for the Textual ``mait-code review`` TUI.

Driven by Textual's headless pilot (``App.run_test()`` wrapped in
``asyncio.run`` — no pytest-asyncio), mirroring ``test_memory_tui.py``. The app
takes a ``db_path`` (an isolated temp store) and an injected ``now`` so the due
set and its recall figures are deterministic — never drifting with wall-clock.
Entries are seeded with direct SQL inserts, so the tests never touch the
embedding path and timestamps stay fixed.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mait_code.cli._review_tui import RefineScreen, ReviewApp, _scope_label
from mait_code.tools.memory.db import get_connection
from mait_code.tui.banner import BrandBanner

#: A fixed clock the queue's recall is measured against, so the due set is
#: stable regardless of when the suite runs.
NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def _run(coro_factory):
    return asyncio.run(coro_factory())


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refine supersedes through the real writer — but not the slow,
    environment-dependent embedding model. Stub it out: the writer's own
    contract is to store without a vector when embedding is unavailable, so
    this exercises exactly that documented fallback, fast and deterministically.
    """
    import mait_code.tools.memory.writer as writer

    monkeypatch.setattr(writer, "_store_embedding", lambda *a, **k: None)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """An empty temp memory database path."""
    return tmp_path / "memory.db"


def _subtitle(app: ReviewApp) -> str:
    """The banner's current view subtitle — carries the live queue state."""
    return app.query_one(BrandBanner)._subtitle


def _seed(db_path: Path, entries: list[dict]) -> None:
    """Insert entries (each a dict of overrides) with explicit review anchors.

    Bypasses ``store_memory`` — a direct insert skips dedup and embeddings and
    pins ``reviewed_at``/``created_at`` so the due order never drifts.
    """
    conn = get_connection(db_path)
    try:
        for spec in entries:
            reviewed = spec["reviewed_at"]
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, scope,
                    project, branch, created_at, reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    spec["content"],
                    spec.get("entry_type", "fact"),
                    spec.get("importance", 8),
                    spec.get("memory_class", "episodic"),
                    spec.get("scope", "global"),
                    spec.get("project"),
                    spec.get("branch"),
                    spec.get("created_at", reviewed),
                    reviewed,
                ),
            )
        conn.commit()
    finally:
        conn.close()


#: Three episodic facts reviewed ~40 days before NOW — far past the 3-day
#: half-life, so all three are due (recall well below the 0.5 threshold).
_THREE_DUE = [
    {"content": "alpha fact still true", "reviewed_at": "2026-06-01 00:00:00"},
    {"content": "beta fact needs refining", "reviewed_at": "2026-06-02 00:00:00"},
    {"content": "gamma fact is stale", "reviewed_at": "2026-06-03 00:00:00"},
]


def _open(db_path: Path):
    return get_connection(db_path)


def _field(db_path: Path, entry_id: int, column: str):
    conn = _open(db_path)
    try:
        row = conn.execute(
            f"SELECT {column} FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# -- loading -------------------------------------------------------------------


def test_queue_loads_most_decayed_first(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test():
            recalls = [e["recall"] for e in app._due]
            assert len(app._due) == 3
            assert recalls == sorted(recalls)  # lowest recall (most decayed) first

    _run(scenario)


def test_below_min_importance_is_excluded(store_path: Path) -> None:
    _seed(
        store_path,
        [
            {
                "content": "important and stale",
                "importance": 8,
                "reviewed_at": "2026-06-01 00:00:00",
            },
            {
                "content": "trivia, let it decay",
                "importance": 2,
                "reviewed_at": "2026-06-01 00:00:00",
            },
        ],
    )

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test():
            contents = [e["content"] for e in app._due]
            assert contents == ["important and stale"]

    _run(scenario)


# -- confirm -------------------------------------------------------------------


def test_confirm_marks_reviewed_and_drops(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            await pilot.press("c")
            await pilot.pause()
            assert len(app._due) == 2
            assert all(e["id"] != target for e in app._due)
            # reviewed_at advanced off its seeded 2026-06 anchor.
            assert not str(_field(store_path, target, "reviewed_at")).startswith(
                "2026-06"
            )

    _run(scenario)


# -- retire --------------------------------------------------------------------


def test_retire_confirmed_drops_and_marks(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            app.action_retire()
            await pilot.pause()
            await pilot.click("#yes")  # accept the guard
            await pilot.pause()
            assert all(e["id"] != target for e in app._due)
            # retired = superseded_at set, superseded_by still null.
            assert _field(store_path, target, "superseded_at") is not None
            assert _field(store_path, target, "superseded_by") is None

    _run(scenario)


def test_retire_cancelled_keeps_the_memory(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            app.action_retire()
            await pilot.pause()
            await pilot.press("escape")  # decline the guard
            await pilot.pause()
            assert any(e["id"] == target for e in app._due)
            assert _field(store_path, target, "superseded_at") is None

    _run(scenario)


# -- refine --------------------------------------------------------------------


def test_refine_supersedes_with_new_content(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            app.action_refine()
            await pilot.pause()
            assert isinstance(app.screen, RefineScreen)
            app.screen.query_one("#refine-input").text = "the refined, current fact"
            app.screen.action_save()
            await pilot.pause()
            # supersede embeds inline on a worker thread — give it a beat.
            for _ in range(20):
                if all(e["id"] != target for e in app._due):
                    break
                await asyncio.sleep(0.05)
                await pilot.pause()
            assert all(e["id"] != target for e in app._due)
            assert _field(store_path, target, "superseded_by") is not None

    _run(scenario)


def test_refine_cancelled_keeps_the_memory(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            app.action_refine()
            await pilot.pause()
            app.screen.action_cancel()
            await pilot.pause()
            assert any(e["id"] == target for e in app._due)
            assert _field(store_path, target, "superseded_by") is None

    _run(scenario)


def test_refine_unchanged_content_is_a_noop(store_path: Path) -> None:
    _seed(store_path, [_THREE_DUE[0]])

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            app.action_refine()
            await pilot.pause()
            # Save without editing → no supersede.
            app.screen.action_save()
            await pilot.pause()
            await asyncio.sleep(0.1)
            await pilot.pause()
            assert any(e["id"] == target for e in app._due)
            assert _field(store_path, target, "superseded_by") is None

    _run(scenario)


# -- skip / empty --------------------------------------------------------------


def test_navigation_does_not_write(store_path: Path) -> None:
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            before = [e["id"] for e in app._due]
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("up")
            await pilot.pause()
            assert [e["id"] for e in app._due] == before  # skipping writes nothing

    _run(scenario)


def test_empty_store_shows_all_caught_up(store_path: Path) -> None:
    get_connection(store_path).close()  # create schema, seed nothing

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._due == []
            assert "all caught up" in _subtitle(app).lower()

    _run(scenario)


def test_draining_the_queue_reaches_empty_state(store_path: Path) -> None:
    _seed(store_path, [_THREE_DUE[0]])

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")  # confirm the only item
            await pilot.pause()
            assert app._due == []
            assert "all caught up" in _subtitle(app).lower()

    _run(scenario)


# -- helpers -------------------------------------------------------------------


def test_scope_label_formats() -> None:
    assert _scope_label({"scope": "global"}) == "global"
    assert _scope_label({"scope": "project", "project": "mait-code"}) == "mait-code"
    assert (
        _scope_label({"scope": "branch", "project": "mait-code", "branch": "feat"})
        == "mait-code:feat"
    )
    # A project scope with no project falls back to global rather than blank.
    assert _scope_label({"scope": "project", "project": None}) == "global"


def test_gone_memory_resyncs(store_path: Path) -> None:
    """Confirming a row deleted underneath us recovers rather than desyncs."""
    _seed(store_path, _THREE_DUE)

    async def scenario():
        app = ReviewApp(db_path=store_path, now=NOW)
        async with app.run_test() as pilot:
            await pilot.pause()
            target = app._due[0]["id"]
            # Delete it out from under the app, then confirm it.
            conn: sqlite3.Connection = get_connection(store_path)
            conn.execute("DELETE FROM memory_entries WHERE id = ?", (target,))
            conn.commit()
            conn.close()
            await pilot.press("c")
            await pilot.pause()
            # The stale row is gone and the queue re-read cleanly.
            assert all(e["id"] != target for e in app._due)

    _run(scenario)
