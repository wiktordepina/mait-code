"""Behaviour tests for the home hub TUI.

The root conftest points ``MAIT_CODE_DATA_DIR`` at a per-test tmp dir, so every
store the hub reads is seeded through the same connections the app uses. The
doctor and version are pinned — the health line and brand header must not
depend on the developer's real ``~/.claude`` or the package version.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import mait_code.cli._doctor as doctor_mod
import mait_code.tui.banner as banner_mod
from mait_code.cli._doctor import Check, DoctorReport
from mait_code.cli._home_tui import HomeApp, HomeTarget

OVERDUE_AT = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
UPCOMING_AT = datetime(2099, 1, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _pin_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the doctor report and version so tests see fixed chrome."""
    report = DoctorReport(
        checks=[Check("a", "ok", "fine"), Check("b", "warn", "meh")],
        fixes_applied=[],
    )
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda **_kw: report)
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "1.2.3")


def _seed_board() -> None:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection

    conn = get_connection()
    try:
        service.add_card(conn, project="demo", title="Wire up the widget")
        wid = service.add_card(conn, project="demo", title="Work the thing")
        service.move_card(conn, wid, "in_progress")
        rid = service.add_card(conn, project="other", title="Refine the spec")
        service.move_card(conn, rid, "refined")
    finally:
        conn.close()


def _seed_reminder(what: str, due: datetime) -> None:
    from mait_code.tools.reminders.db import get_connection

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
            (what, due.isoformat(), OVERDUE_AT.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_inbox(body: str) -> None:
    from mait_code.tools.inbox import service
    from mait_code.tools.inbox.db import get_connection

    conn = get_connection()
    try:
        service.add_item(conn, body=body)
    finally:
        conn.close()


def _seed_memory(*entries: tuple[str, str]) -> None:
    from mait_code.tools.memory.db import get_connection

    conn = get_connection()
    try:
        for content, entry_type in entries:
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, created_at)
                   VALUES (?, ?, 5, 'semantic', '2026-06-01 09:00:00')""",
                (content, entry_type),
            )
        conn.commit()
    finally:
        conn.close()


def _run(coro_factory):
    return asyncio.run(coro_factory())


def _detail_text(app: HomeApp) -> str:
    """The rendered text of the detail pane (labels and markdown bodies)."""
    parts: list[str] = []
    for widget in app.query("#detail *"):
        render = getattr(widget, "render", None)
        if render is not None:
            parts.append(str(render()))
    return "\n".join(parts)


def _tree_labels(app: HomeApp) -> list[str]:
    from textual.widgets import Tree

    tree = app.query_one("#tree", Tree)
    return [str(child.label) for child in tree.root.children]


async def _show(app, pilot, key: str) -> str:
    await app._show_detail(key)
    await pilot.pause()
    return _detail_text(app)


# --- empty stores ---


def test_empty_details_speak_with_the_companion_voice() -> None:
    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return {
                key: await _show(app, pilot, key)
                for key in ("board", "memory", "reminders", "inbox")
            }

    details = _run(scenario)
    assert "board is clear" in details["board"]
    assert "Nothing remembered yet" in details["memory"]
    assert "Nothing pending" in details["reminders"]
    assert "Inbox zero" in details["inbox"]
    for text in details.values():
        assert "✦ " in text  # glyph-led voice, not a bare "no data"


# --- populated detail panes ---


def test_board_detail_lists_live_cards_and_launch_hint() -> None:
    _seed_board()

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "board")

    text = _run(scenario)
    assert "In progress" in text and "Work the thing" in text
    assert "Next up" in text and "Refine the spec" in text
    # The launch hint now points at the dedicated "↗ Open board" leaf.
    assert "Open board" in text and "launch the full board" in text


def test_board_by_project_breakdown() -> None:
    _seed_board()

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "board:by_project")

    text = _run(scenario)
    assert "demo" in text and "other" in text
    assert "1 backlog" in text and "1 in progress" in text


def test_reminders_detail_splits_overdue_and_upcoming() -> None:
    _seed_reminder("water the plants", OVERDUE_AT)
    _seed_reminder("renew the domain", UPCOMING_AT)

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "reminders")

    text = _run(scenario)
    assert "Overdue (1)" in text and "water the plants" in text
    assert "Upcoming" in text and "renew the domain" in text


def test_inbox_detail_counts_and_guides() -> None:
    _seed_inbox("first thought")
    _seed_inbox("second thought")

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "inbox")

    text = _run(scenario)
    assert "2 captured items" in text
    assert "first thought" in text and "second thought" in text
    assert "/triage" in text  # non-launchable: it points at the skill


def test_memory_by_type_detail() -> None:
    _seed_memory(("a", "fact"), ("b", "fact"), ("c", "decision"))

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "memory:by_type")

    text = _run(scenario)
    assert "fact (2)" in text and "decision (1)" in text


def _seed_memory_reviewed_at(
    content: str, reviewed_at: str, *, importance: int = 8
) -> None:
    """Seed a semantic memory with an explicit review anchor.

    ``recency_score`` uses the real wall-clock, so tests pass absolute
    timestamps (far-past → robustly due, now → robustly fresh) to stay
    time-independent.
    """
    from mait_code.tools.memory.db import get_connection

    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, created_at, reviewed_at)
               VALUES (?, 'fact', ?, 'semantic', ?, ?)""",
            (content, importance, reviewed_at, reviewed_at),
        )
        conn.commit()
    finally:
        conn.close()


def test_memory_review_detail_lists_due_items() -> None:
    _seed_memory_reviewed_at(
        "an ageing but important decision", "2020-01-01T00:00:00+00:00"
    )

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "memory:review")

    text = _run(scenario)
    assert "Due for review" in text
    assert "ageing but important decision" in text


def test_memory_review_detail_empty_when_fresh() -> None:
    _seed_memory_reviewed_at(
        "a freshly reviewed fact", datetime.now(timezone.utc).isoformat()
    )

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "memory:review")

    text = _run(scenario)
    assert "Nothing due" in text


def test_memory_reflection_detail() -> None:
    _seed_memory(("a", "fact"))

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "memory:reflection")

    text = _run(scenario)
    assert "awaiting" in text and "observation(s)" in text and "never" in text


def test_doctor_detail_lists_every_check() -> None:
    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "system:doctor")

    text = _run(scenario)
    assert "a" in text and "fine" in text
    assert "b" in text and "meh" in text


# --- tree badges ---


def test_tree_badges_reflect_live_counts() -> None:
    _seed_board()
    _seed_reminder("water the plants", OVERDUE_AT)
    _seed_inbox("a thought")
    _seed_memory(("a", "fact"))

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return _tree_labels(app)

    labels = "\n".join(_run(scenario))
    assert "Board" in labels and "active" in labels
    assert "1 overdue!" in labels
    assert "Inbox" in labels


# --- chrome ---


def test_health_line_renders_pinned_doctor_verdict() -> None:
    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return str(app.query_one("#health").render())

    text = _run(scenario)
    assert "1 warning" in text and "1 passed" in text and "doctor" in text


def test_rich_colour_normalises_theme_colours() -> None:
    from mait_code.tui.palette import rich_colour

    assert rich_colour("#abcdef", "#000") == "#abcdef"  # hex passes through
    assert rich_colour("ansi_yellow", "#000") == "yellow"  # ansi → Rich name
    assert rich_colour("ansi_bright_red", "#000") == "bright_red"
    assert rich_colour(None, "#000") == "#000"  # unset → fallback
    assert rich_colour("", "#000") == "#000"


def test_home_renders_under_ansi_theme() -> None:
    """The ansi themes store colour names Rich can't parse (e.g. ``ansi_yellow``);
    the health line and tree must render under them, not raise ``MissingStyle``."""

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.theme = "ansi-dark"
            await pilot.pause()
            # Reload re-renders the health line and rebuilds the tree (launch
            # leaves carry the accent) with the active theme's colours — the
            # exact path that crashed on mount under an ansi theme.
            app.action_reload()
            await pilot.pause()
            return str(app.query_one("#health").render())

    assert "passed" in _run(scenario)  # rendered, not crashed


def test_wordmark_falls_back_when_narrow() -> None:
    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(24, 36)) as pilot:
            await pilot.pause()
            return str(app.query_one("#wordmark").render())

    assert _run(scenario) == "mait-code"


def _banner_state(width: int, height: int) -> tuple[str, bool]:
    """Render the home banner at *size* and report (wordmark, is-compact)."""

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(width, height)) as pilot:
            await pilot.pause()
            banner = app.query_one(banner_mod.BrandBanner)
            return str(app.query_one("#wordmark").render()), banner.has_class(
                "-compact"
            )

    return _run(scenario)


def test_banner_full_on_a_tall_terminal() -> None:
    from mait_code.tui.brand import WORDMARK

    wordmark, compact = _banner_state(120, 40)
    assert wordmark == WORDMARK
    assert compact is False


def test_banner_goes_compact_on_a_short_terminal() -> None:
    from mait_code.tui.brand import WORDMARK_COMPACT

    # 28 rows is at/below COMPACT_MAX_HEIGHT, so the half-height art stands in.
    wordmark, compact = _banner_state(120, 28)
    assert wordmark == WORDMARK_COMPACT
    assert compact is True


def test_broken_store_shows_snag_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    import mait_code.tools.inbox.db as inbox_db

    def boom(*_a, **_kw):
        raise RuntimeError("store on fire")

    monkeypatch.setattr(inbox_db, "get_connection", boom)

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            return await _show(app, pilot, "inbox")

    text = _run(scenario)
    assert "hit a snag" in text
    assert "store on fire" in text


# --- system prompt node ---


def test_system_prompt_node_renders_identity_and_context() -> None:
    from mait_code.config import data_dir

    ddir = data_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "soul_document.md").write_text("# Soul\n\nBe kind.\n")

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            text = await _show(app, pilot, "identity:sysprompt")
            docs = len(app.query("#detail Markdown"))
            return text, docs

    text, docs = _run(scenario)
    assert "Soul document" in text
    assert "User context" in text
    assert "isn't written yet" in text  # missing files speak, not error
    assert "Session context" in text
    assert "A quiet start" in text  # empty stores → silent context, voiced
    assert docs == 1  # only the soul document exists in this data dir


# --- launch + reload ---


def test_selecting_a_launch_leaf_sets_the_target() -> None:
    from textual.widgets import Tree

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            board = tree.root.children[0]  # Board section (expands, no launch)
            open_board = board.children[0]  # "↗ Open board" launch leaf
            app.on_tree_node_selected(Tree.NodeSelected(open_board))
            await pilot.pause()
            return app.target

    assert _run(scenario) is HomeTarget.BOARD


def test_selecting_a_category_toggles_without_launching() -> None:
    from textual.widgets import Tree

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            board = tree.root.children[0]  # Board section
            was_expanded = board.is_expanded
            app.on_tree_node_selected(Tree.NodeSelected(board))
            await pilot.pause()
            return app.target, was_expanded, board.is_expanded

    target, was_expanded, now_expanded = _run(scenario)
    assert target is None  # the category never launches
    assert was_expanded and not now_expanded  # Enter toggled it closed


def test_escape_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "action_quit", lambda: called.append(True))
            await pilot.press("escape")
            await pilot.pause()

    _run(scenario)
    assert called == [True]


def test_reload_refreshes_detail_and_badges() -> None:
    async def scenario():
        app = HomeApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            before_detail = _detail_text(app)  # home overview, cursor on root
            before_labels = "\n".join(_tree_labels(app))
            _seed_inbox("captured mid-session")
            app.action_reload()  # re-reads stores: refreshes detail + badges
            await pilot.pause()
            await pilot.pause()
            return (
                before_detail,
                before_labels,
                _detail_text(app),
                "\n".join(_tree_labels(app)),
            )

    before_detail, before_labels, after_detail, after_labels = _run(scenario)
    assert "inbox zero" in before_detail  # the overview's Inbox line
    assert "1 waiting" in after_detail  # detail re-rendered with fresh count
    assert "Inbox\n" in before_labels or before_labels.rstrip().endswith("Inbox")
    assert "Inbox  1" in after_labels  # badge picked up the new item


# --- reindex ---


def test_reindex_confirm_yes_runs_suspended_reindex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def fake_suspended_reindex() -> tuple[str, bool]:
        calls.append(True)
        return "Embedded 2 entries", False

    async def scenario():
        # Unembedded entries (the seed helper stores no vectors), so the
        # action reaches the confirm modal instead of the all-clear exit.
        _seed_memory(("a fact", "fact"), ("a decision", "decision"))
        app = HomeApp()
        monkeypatch.setattr(app, "_run_reindex_suspended", fake_suspended_reindex)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()  # confirm modal is up
            await pilot.click("#yes")
            await pilot.pause()
            await pilot.pause()  # worker finishes, hub refreshes

    _run(scenario)
    assert calls == [True]


def test_reindex_confirm_no_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    async def scenario():
        _seed_memory(("a fact", "fact"))
        app = HomeApp()
        monkeypatch.setattr(app, "_run_reindex_suspended", lambda: calls.append(True))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            await pilot.press("escape")  # dismisses the modal as "No"
            await pilot.pause()
            await pilot.pause()

    _run(scenario)
    assert calls == []


def test_reindex_skips_modal_when_nothing_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing missing a vector the action notifies and never confirms."""
    calls: list[bool] = []

    async def scenario():
        app = HomeApp()  # empty store: zero entries means zero missing
        monkeypatch.setattr(app, "_run_reindex_suspended", lambda: calls.append(True))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            return len(app.screen_stack)

    depth = _run(scenario)
    assert depth == 1  # no ConfirmScreen was pushed
    assert calls == []
