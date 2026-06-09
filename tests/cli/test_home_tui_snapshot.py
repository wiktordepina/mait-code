"""Snapshot tests locking the home hub's visual output.

Renders the hub against accepted SVG baselines under ``__snapshots__/``.
Everything environment- or time-dependent is pinned: stores are seeded with
fixed timestamps (overdue in the past, upcoming far in the future), the doctor
report and version are stubbed, and the theme is the ``mait-dark`` default.

Regenerate the baselines intentionally (and eyeball the diff) with::

    uv run pytest tests/cli/test_home_tui_snapshot.py --snapshot-update
"""

from __future__ import annotations

import pytest

import mait_code.cli._doctor as doctor_mod
import mait_code.tui.banner as banner_mod
from mait_code.cli._doctor import Check, DoctorReport
from mait_code.cli._home_tui import HomeApp


@pytest.fixture(autouse=True)
def _pin_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the doctor report and the version string for stable chrome."""
    report = DoctorReport(
        checks=[
            Check("settings", "ok", "fine"),
            Check("symlinks", "ok", "fine"),
            Check("data-dir", "warn", "meh"),
        ],
        fixes_applied=[],
    )
    monkeypatch.setattr(doctor_mod, "run_doctor", lambda **_kw: report)
    # The banner masthead renders the version; pin it so the chrome stays
    # release-stable (it's read through the shared banner module now).
    monkeypatch.setattr(banner_mod, "installed_version", lambda: "0.0.0")


def _seed_all_stores() -> None:
    """Fixed seeds across every store the dashboard reads."""
    from mait_code.tools.board import service as board_service
    from mait_code.tools.board.db import get_connection as board_connection
    from mait_code.tools.inbox import service as inbox_service
    from mait_code.tools.inbox.db import get_connection as inbox_connection
    from mait_code.tools.memory.db import get_connection as memory_connection
    from mait_code.tools.reminders.db import get_connection as reminders_connection

    conn = board_connection()
    try:
        board_service.add_card(conn, project="demo", title="Wire up the widget")
        wid = board_service.add_card(
            conn, project="demo", title="Work the thing", priority="high"
        )
        board_service.move_card(conn, wid, "in_progress")
        rid = board_service.add_card(conn, project="other", title="Refine the spec")
        board_service.move_card(conn, rid, "refined")
    finally:
        conn.close()

    conn = reminders_connection()
    try:
        for what, due in (
            ("water the plants", "2026-01-01T09:00:00+00:00"),
            ("renew the domain", "2099-01-01T09:00:00+00:00"),
        ):
            conn.execute(
                "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
                (what, due, "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    conn = inbox_connection()
    try:
        inbox_service.add_item(conn, body="look into that flaky deploy")
    finally:
        conn.close()

    conn = memory_connection()
    try:
        for content, entry_type in (
            ("The CI/CD pipeline runs on the home server.", "fact"),
            ("Cody's walk comes before the first coffee.", "fact"),
            ("Moved the blocked column to a tags system.", "decision"),
        ):
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, created_at)
                   VALUES (?, ?, 5, 'semantic', '2026-06-01 09:00:00')""",
                (content, entry_type),
            )
        conn.execute(
            "INSERT INTO reflection_watermark "
            "(project, last_reflected_id, last_reflected_at) "
            "VALUES ('', 1, '2026-06-05 12:00:00')"
        )
        conn.commit()
    finally:
        conn.close()


def _seed_identity() -> None:
    """Write the identity stack so the system-prompt pane has content to weigh."""
    from mait_code.config import data_dir

    ddir = data_dir()
    (ddir / "memory").mkdir(parents=True, exist_ok=True)
    (ddir / "soul_document.md").write_text(
        "# Soul document\n\n"
        "I'm a coding companion, not a generic assistant. I hold opinions, "
        "push back when an approach looks wrong, and explain my reasoning. I "
        "match my length to the task — concise by default, fuller when the "
        "problem earns it.\n\n"
        "## Core values\n\n"
        "- **Empathy** — read the intent before acting.\n"
        "- **Assertiveness** — advocate for the better approach.\n"
        "- **Integrity** — never harmful, never deceptive.\n"
    )
    (ddir / "user_context.md").write_text(
        "# User context\n\n"
        "**Name:** Wiktor. **Role:** Senior DevOps Engineer in the UK.\n\n"
        "Works in Python, Go and shell across AWS, Docker and Terraform. "
        "Casual, direct, British spelling. Prefers deep focus and proper TUIs "
        "over questionnaire-style prompts.\n"
    )
    (ddir / "memory" / "MEMORY.md").write_text(
        "# Memory\n\n"
        "## Feedback\n\n"
        "- All changes go through a topic branch and a PR — never commit "
        "straight to main.\n"
        "- Run installed `mc-tool-*` binaries directly, not via `uv run`.\n"
    )


def test_home_empty_snapshot(snap_compare) -> None:
    """Lock the empty hub: the tree sidebar, the home overview speaking in the
    companion voice, the wordmark, tagline, version, and pinned health line."""
    assert snap_compare(HomeApp(), terminal_size=(120, 40))


def test_home_populated_snapshot(snap_compare) -> None:
    """Lock the populated hub: tree badges (live counts, overdue in alarm) and
    the home overview over every seeded store."""
    _seed_all_stores()
    assert snap_compare(HomeApp(), terminal_size=(120, 40))


def test_home_board_detail_snapshot(snap_compare) -> None:
    """Lock a section detail pane: pressing down lands on Board (the first
    section), rendering its full live-card breakdown beside the tree."""
    _seed_all_stores()
    assert snap_compare(HomeApp(), press=["down"], terminal_size=(120, 40))


def test_home_sysprompt_snapshot(snap_compare) -> None:
    """Lock the system-prompt pane: the identity stack and live session context,
    each carrying its ~token estimate, with the budget total in the header."""
    _seed_all_stores()
    _seed_identity()

    async def run_before(pilot) -> None:
        await pilot.pause()
        await pilot.app._show_detail("identity:sysprompt")
        await pilot.pause()

    assert snap_compare(HomeApp(), run_before=run_before, terminal_size=(120, 48))
