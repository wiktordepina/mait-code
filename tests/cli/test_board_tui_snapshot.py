"""Snapshot test locking the board TUI's visual output (A1 retrofit).

Renders a seeded board at a fixed terminal size and compares it against an
accepted SVG baseline under ``__snapshots__/``. The seed is fixed so card
ordering never drifts; the theme is the ``mait-dark`` default applied by
:class:`~mait_code.tui.app.MaitApp`.

Regenerate the baseline intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_board_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

from pathlib import Path

from mait_code.cli._board_tui import BoardApp
from mait_code.tools.board import service
from mait_code.tools.board.db import get_connection


def _seed_demo(db_path: Path) -> None:
    """A small board spanning every column, with a blocked card, for the shot.

    Note: the Done column is hidden by default, so the ``did`` card below does
    not appear in the board snapshot — that's intended, not a missing card.
    """
    conn = get_connection(db_path)
    try:
        service.add_card(
            conn, project="demo", title="Wire up the widget", priority="high"
        )
        rid = service.add_card(
            conn, project="demo", title="Refine the spec", priority="medium"
        )
        service.move_card(conn, rid, "refined")
        bid = service.add_card(
            conn, project="demo", title="Awaiting review", priority="low"
        )
        service.move_card(conn, bid, "in_progress")
        service.block_card(conn, bid)
        did = service.add_card(
            conn, project="demo", title="Ship the thing", priority="medium"
        )
        service.move_card(conn, did, "done")
    finally:
        conn.close()


def test_board_snapshot(snap_compare, tmp_path: Path) -> None:
    db_path = tmp_path / "board.db"
    _seed_demo(db_path)
    assert snap_compare(BoardApp(db_path=db_path), terminal_size=(120, 40))


def test_help_screen_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the shared help screen's rendered look (keys + descriptions)."""
    db_path = tmp_path / "board.db"
    _seed_demo(db_path)
    assert snap_compare(
        BoardApp(db_path=db_path),
        press=["question_mark"],
        terminal_size=(120, 40),
    )


def _seed_board_rich(db_path: Path) -> None:
    """A busy, multi-project board for the docs board shots.

    Spans three projects with long titles that wrap, several tags per card, a
    blocked card, and cards in every column — Done and Archived included, so the
    expanded view has content in all five panes.
    """
    conn = get_connection(db_path)
    try:
        # (project, title, priority, status, tags, blocked, summary)
        cards = [
            (
                "mait-code",
                "Persist the board's collapsed / expanded layout across sessions",
                "high",
                "backlog",
                ["tui", "enhancement"],
                False,
                None,
            ),
            (
                "homelab",
                "Rotate the Restic backup encryption keys and document the runbook",
                "medium",
                "backlog",
                ["infra", "security"],
                False,
                None,
            ),
            (
                "dotfiles",
                "Switch the Neovim config over to the lazy.nvim plugin loader",
                "low",
                "backlog",
                ["chore"],
                False,
                None,
            ),
            (
                "mait-code",
                "Add a shortcut to jump straight to a card by its ID number",
                "medium",
                "refined",
                ["tui"],
                False,
                None,
            ),
            (
                "homelab",
                "Migrate the Prometheus scrape configs to the node-exporter v2 layout",
                "high",
                "refined",
                ["infra", "urgent"],
                False,
                None,
            ),
            (
                "mait-code",
                "Render card references as a collapsible section in the detail view",
                "high",
                "in_progress",
                ["tui"],
                True,
                None,
            ),
            (
                "homelab",
                "Debug intermittent DNS resolution failures on the Pi-hole container",
                "medium",
                "in_progress",
                ["bug", "infra"],
                False,
                None,
            ),
            (
                "mait-code",
                "Persist the chosen theme across TUI sessions",
                "medium",
                "done",
                ["tui"],
                False,
                "Saved on unmount, restored on launch.",
            ),
            (
                "homelab",
                "Set up nightly off-site backup sync to Backblaze B2",
                "low",
                "done",
                ["infra"],
                False,
                "Cron + Restic to B2, alerting on failure.",
            ),
            (
                "dotfiles",
                "Spike: experiment with a fish-shell prompt",
                "low",
                "archived",
                ["spike"],
                False,
                None,
            ),
        ]
        for project, title, priority, status, tags, blocked, summary in cards:
            cid = service.add_card(
                conn, project=project, title=title, priority=priority
            )
            if status == "done":
                service.complete_card(conn, cid, summary=summary)
            elif status == "archived":
                service.archive_card(conn, cid)
            elif status != "backlog":
                service.move_card(conn, cid, status)
            for tag in tags:
                service.add_tag(conn, cid, tag)
            if blocked:
                service.block_card(conn, cid)
        conn.commit()
    finally:
        conn.close()


def test_board_rich_snapshot(snap_compare, tmp_path: Path) -> None:
    """A busy multi-project board in the default collapsed view — the docs hero
    shot: wrapping titles, multiple tags, a blocked card, per-card project
    labels (shown because the filter is on ``all``)."""
    db_path = tmp_path / "board.db"
    _seed_board_rich(db_path)

    assert snap_compare(
        BoardApp(db_path=db_path),
        terminal_size=(132, 46),
    )


def test_board_search_snapshot(snap_compare, tmp_path: Path) -> None:
    """The busy board filtered to a title query via ``/`` → type → submit.

    ``config`` matches a backlog card (Neovim config) and a refined card
    (Prometheus scrape configs); the other panes empty out, and the subtitle
    shows the active query."""
    db_path = tmp_path / "board.db"
    _seed_board_rich(db_path)

    async def run_before(pilot) -> None:
        await pilot.press("slash")  # open the search modal
        await pilot.pause()
        await pilot.press(*"config")
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(132, 46),
    )


def test_board_project_filter_snapshot(snap_compare, tmp_path: Path) -> None:
    """The project filter picker open over the busy board via ``p``.

    The ``Select`` auto-expands on mount, so the dropdown lists "All projects"
    plus every seeded project — the gesture that replaced round-robin cycling."""
    db_path = tmp_path / "board.db"
    _seed_board_rich(db_path)

    async def run_before(pilot) -> None:
        await pilot.press("p")  # open the project picker (auto-expands)
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(132, 46),
    )


def test_board_rich_expanded_snapshot(snap_compare, tmp_path: Path) -> None:
    """The same busy board uncollapsed — all five columns revealed via ``d`` and
    ``a`` — the docs review-layout shot."""
    db_path = tmp_path / "board.db"
    _seed_board_rich(db_path)

    async def run_before(pilot) -> None:
        await pilot.press("d")  # reveal Done
        await pilot.press("a")  # reveal Archived
        await pilot.pause()

    # Wider than the three-column shot: five panes need the extra columns.
    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(176, 46),
    )


def _seed_detail(db_path: Path) -> None:
    """A content-rich card (long title, sections, tags, comments) for the modal.

    Comments are inserted with fixed timestamps so the snapshot is stable.
    """
    conn = get_connection(db_path)
    try:
        cid = service.add_card(
            conn,
            project="mait-code",
            title="Replace the blocked column with a tags system in the board TUI",
            priority="high",
        )
        service.move_card(conn, cid, "refined")
        service.edit_card(
            conn,
            cid,
            description=(
                "Drop blocked as a board column and introduce a general "
                "free-form tag system."
            ),
            acceptance_criteria="- tag/untag verbs\n- a TUI toggle\n- render on rows",
        )
        service.add_tag(conn, cid, "tui")
        for author, body, ts in (
            (
                "claude",
                "Research complete; recommends staying on Textual.",
                "2026-05-30T09:00:00+00:00",
            ),
            ("me", "Agreed — let's lock the approach.", "2026-05-30T10:30:00+00:00"),
        ):
            conn.execute(
                "INSERT INTO card_comments (card_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (cid, author, body, ts),
            )
        conn.commit()
    finally:
        conn.close()


def test_detail_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the near-fullscreen card screen in view mode (wrap, sections,
    capped content column, comment blocks)."""
    db_path = tmp_path / "board.db"
    _seed_detail(db_path)

    async def run_before(pilot) -> None:
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_detail_snapshot_bubblegum(snap_compare, tmp_path: Path) -> None:
    """Lock the card screen under the mait-bubblegum theme.

    Proves a theme switch recolours the whole screen — including the Rich-text
    chips (priority/tags), which are baked at render time and don't read CSS
    variables, so they'd otherwise stay on the default palette.
    """
    db_path = tmp_path / "board.db"
    _seed_detail(db_path)

    async def run_before(pilot) -> None:
        pilot.app.theme = "mait-bubblegum"
        await pilot.pause()
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_detail_snapshot_syntax(snap_compare, tmp_path: Path) -> None:
    """Lock the card screen under the mait-syntax theme (the screenshot-derived
    palette), so its look is captured alongside bubblegum."""
    db_path = tmp_path / "board.db"
    _seed_detail(db_path)

    async def run_before(pilot) -> None:
        pilot.app.theme = "mait-syntax"
        await pilot.pause()
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def _show_toasts(pilot) -> None:
    """Fire one toast per severity so the snapshot captures all three styles."""
    pilot.app.notify("Card #3 created", severity="information")
    pilot.app.notify("Card #3 blocked", severity="warning")
    pilot.app.notify("Could not reach the board", severity="error")


def test_toast_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the house toast styling: a rounded, severity-keyed border with a
    leading glyph per severity (information / warning / error), under the
    mait-dark default."""
    db_path = tmp_path / "board.db"
    _seed_demo(db_path)

    async def run_before(pilot) -> None:
        _show_toasts(pilot)
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def test_toast_snapshot_ember(snap_compare, tmp_path: Path) -> None:
    """Lock the toast styling under mait-ember, proving severity colours track
    a theme switch (amber primary, gold warning, red error)."""
    db_path = tmp_path / "board.db"
    _seed_demo(db_path)

    async def run_before(pilot) -> None:
        pilot.app.theme = "mait-ember"
        await pilot.pause()
        _show_toasts(pilot)
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def _seed_detail_with_refs(db_path: Path) -> None:
    """A refined card carrying a mix of reference kinds for the detail shot:
    a linkable URL, a file:// path, and a bare ID (rendered plain)."""
    conn = get_connection(db_path)
    try:
        cid = service.add_card(
            conn, project="mait-code", title="Card with references", priority="medium"
        )
        service.move_card(conn, cid, "refined")
        service.edit_card(conn, cid, description="Has a References section.")
        service.add_reference(conn, cid, "PR", "https://github.com/example/pr/1")
        service.add_reference(conn, cid, "Plan", "file:///home/me/plan.html")
        service.add_reference(conn, cid, "JIRA", "WIKTOR-2342")
    finally:
        conn.close()


def test_detail_references_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the References section in the card detail view — links vs the plain
    bare ID, positions shown."""
    db_path = tmp_path / "board.db"
    _seed_detail_with_refs(db_path)

    async def run_before(pilot) -> None:
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )


def _seed_detail_full(db_path: Path) -> None:
    """A fully-populated card for the docs hero shot: title, two tags,
    description, acceptance criteria, a mix of references, and a comment thread.

    Comments use fixed timestamps so the snapshot is stable.
    """
    conn = get_connection(db_path)
    try:
        cid = service.add_card(
            conn,
            project="mait-code",
            title="Add a References field to cards",
            priority="high",
        )
        service.move_card(conn, cid, "refined")
        service.edit_card(
            conn,
            cid,
            description=(
                "Cards accumulate links — PRs, tickets, specs — buried in the "
                "description. Give each card a structured, ordered list of "
                "label → value references instead."
            ),
            acceptance_criteria=(
                "- ref add/remove/list CLI verbs\n"
                "- an `r` key on the detail screen\n"
                "- URLs render as clickable links, bare IDs stay plain"
            ),
        )
        service.add_tag(conn, cid, "tui")
        service.add_tag(conn, cid, "enhancement")
        service.add_reference(conn, cid, "PR", "https://github.com/example/pr/66")
        service.add_reference(conn, cid, "Plan", "file:///home/me/plan.html")
        service.add_reference(conn, cid, "JIRA", "WIKTOR-2342")
        for author, body, ts in (
            (
                "claude",
                "Drafted the schema migration — references live in their own "
                "table, ordered by position.",
                "2026-05-31T09:00:00+00:00",
            ),
            ("me", "Looks good — ship it.", "2026-05-31T10:15:00+00:00"),
        ):
            conn.execute(
                "INSERT INTO card_comments (card_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (cid, author, body, ts),
            )
        conn.commit()
    finally:
        conn.close()


def test_detail_full_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the card detail view with every section populated at once — title,
    tags, description, acceptance criteria, references, and comments. Doubles as
    the docs screenshot for a fully-filled card."""
    db_path = tmp_path / "board.db"
    _seed_detail_full(db_path)

    async def run_before(pilot) -> None:
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()

    # A taller terminal than the other shots: this card fills every section, so
    # the extra rows keep the whole thread above the fold for the docs image.
    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 50),
    )


def test_card_edit_snapshot(snap_compare, tmp_path: Path) -> None:
    """Lock the edit mode of the card screen (form fields on the same frame),
    reached in-place from view via ``e``."""
    db_path = tmp_path / "board.db"
    _seed_detail(db_path)

    async def run_before(pilot) -> None:
        pilot.app._focus_status("refined")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()

    assert snap_compare(
        BoardApp(db_path=db_path),
        run_before=run_before,
        terminal_size=(120, 40),
    )
