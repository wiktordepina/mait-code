"""Unit tests for the start-page dashboard: loader, built-ins, command tiles.

The loader is tolerant by contract — every malformed input lands on a usable
layout with the problem recorded in ``warnings``, never an exception. The
root conftest points ``MAIT_CODE_DATA_DIR`` at a per-test tmp dir, so the
built-in collectors read the same isolated stores the behaviour tests seed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from mait_code.cli._dashboard import (
    BUILTIN_WIDGETS,
    MAX_COLUMNS,
    MAX_OUTPUT_LINES,
    builtin_tile_lines,
    dashboard_path,
    default_tiles,
    load_dashboard,
    run_command_tile,
)

# --- loading ---


def test_missing_file_gives_silent_defaults(tmp_path: Path) -> None:
    cfg = load_dashboard(tmp_path / "dashboard.toml")
    assert cfg.tiles == default_tiles()
    assert cfg.columns == 2
    assert cfg.warnings == ()
    assert not cfg.authored


def test_malformed_toml_falls_back_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text("columns = [broken", encoding="utf-8")
    cfg = load_dashboard(path)
    assert cfg.tiles == default_tiles()
    assert not cfg.authored
    assert any("could not be read" in w for w in cfg.warnings)


def test_authored_layout_parses_widgets_and_commands(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text(
        """
columns = 3

[[tile]]
widget = "reminders"

[[tile]]
widget = "board"
title = "What's cooking"
span = 2

[[tile]]
command = "df -h /"
title = "Disk"
""",
        encoding="utf-8",
    )
    cfg = load_dashboard(path)
    assert cfg.authored
    assert cfg.columns == 3
    assert cfg.warnings == ()
    assert [t.widget for t in cfg.tiles] == ["reminders", "board", None]
    assert cfg.tiles[1].title == "What's cooking"
    assert cfg.tiles[1].span == 2
    assert cfg.tiles[2].command == "df -h /"
    assert cfg.tiles[2].title == "Disk"


def test_unknown_widget_is_skipped_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text(
        '[[tile]]\nwidget = "reminders"\n[[tile]]\nwidget = "nope"\n',
        encoding="utf-8",
    )
    cfg = load_dashboard(path)
    assert cfg.authored
    assert [t.widget for t in cfg.tiles] == ["reminders"]
    assert any("unknown widget 'nope'" in w for w in cfg.warnings)


def test_tile_with_both_widget_and_command_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text('[[tile]]\nwidget = "board"\ncommand = "ls"\n', encoding="utf-8")
    cfg = load_dashboard(path)
    assert cfg.tiles == default_tiles()  # nothing usable → defaults
    assert not cfg.authored
    assert any("exactly one of widget or command" in w for w in cfg.warnings)
    assert any("no usable tiles" in w for w in cfg.warnings)


def test_columns_out_of_range_clamps_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text('columns = 9\n[[tile]]\nwidget = "inbox"\n', encoding="utf-8")
    cfg = load_dashboard(path)
    assert cfg.columns == MAX_COLUMNS
    assert any("columns must be" in w for w in cfg.warnings)


def test_columns_wrong_type_falls_back_to_two(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text('columns = "wide"\n[[tile]]\nwidget = "inbox"\n', encoding="utf-8")
    cfg = load_dashboard(path)
    assert cfg.columns == 2
    assert any("must be an integer" in w for w in cfg.warnings)


def test_span_is_clamped_to_the_column_count(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text(
        'columns = 2\n[[tile]]\nwidget = "inbox"\nspan = 5\n', encoding="utf-8"
    )
    cfg = load_dashboard(path)
    assert cfg.tiles[0].span == 2


def test_bad_span_warns_and_uses_one(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.toml"
    path.write_text('[[tile]]\nwidget = "inbox"\nspan = "wide"\n', encoding="utf-8")
    cfg = load_dashboard(path)
    assert cfg.tiles[0].span == 1
    assert any("span must be a positive integer" in w for w in cfg.warnings)


def test_dashboard_path_lives_under_the_data_dir() -> None:
    from mait_code.config import data_dir

    assert dashboard_path() == data_dir() / "dashboard.toml"


# --- built-in widgets ---


def test_every_builtin_renders_on_empty_stores() -> None:
    """Each widget copes with a fresh, empty data dir — no store, no crash."""
    for widget in BUILTIN_WIDGETS:
        lines = builtin_tile_lines(widget)
        assert lines, f"{widget} rendered nothing"
        assert all(isinstance(line.text, str) for line in lines)


def test_reminders_tile_flags_overdue() -> None:
    from mait_code.tools.reminders.db import get_connection

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
            (
                "water the plants",
                "2026-01-01T09:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    lines = builtin_tile_lines("reminders")
    assert lines[0].text == "1 overdue"
    assert lines[0].style == "warn"
    assert "water the plants" in lines[1].text


def test_board_tile_summarises_live_cards() -> None:
    from mait_code.tools.board import service
    from mait_code.tools.board.db import get_connection

    conn = get_connection()
    try:
        wid = service.add_card(conn, project="demo", title="Work the thing")
        service.move_card(conn, wid, "in_progress")
        service.add_card(conn, project="demo", title="Later thing")
    finally:
        conn.close()
    lines = builtin_tile_lines("board")
    assert "2 live" in lines[0].text and "1 in progress" in lines[0].text
    assert any("Work the thing" in line.text for line in lines)


def test_velocity_tile_buckets_this_week_against_last() -> None:
    from mait_code.tools.memory.db import get_connection

    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        for age_days in (1, 2, 9):  # two this week, one the week before
            stamp = (now - timedelta(days=age_days)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, created_at)
                   VALUES ('x', 'fact', 5, 'semantic', ?)""",
                (stamp,),
            )
        conn.commit()
    finally:
        conn.close()
    lines = builtin_tile_lines("velocity")
    memories = next(line.text for line in lines if line.text.startswith("memories"))
    assert "2 this week" in memories and "1 last" in memories and "↑" in memories


# --- command tiles ---


def test_command_tile_captures_stdout() -> None:
    result = run_command_tile("echo hello && echo world", timeout=5)
    assert result.ok
    assert result.output == "hello\nworld"


def test_command_tile_reports_failure_with_stderr_tail() -> None:
    result = run_command_tile("echo boom >&2; exit 3", timeout=5)
    assert not result.ok
    assert result.output == "exited 3: boom"


def test_command_tile_times_out() -> None:
    result = run_command_tile("sleep 5", timeout=1)
    assert not result.ok
    assert "timed out after 1s" in result.output


def test_command_tile_clips_long_output() -> None:
    result = run_command_tile(f"seq {MAX_OUTPUT_LINES + 10}", timeout=5)
    assert result.ok
    lines = result.output.splitlines()
    assert len(lines) == MAX_OUTPUT_LINES + 1
    assert lines[-1] == "… 10 more line(s)"


def test_command_tile_with_no_output_says_so() -> None:
    result = run_command_tile("true", timeout=5)
    assert result.ok
    assert result.output == "(no output)"


# --- editable model (the setup TUI's working copy) ---


def test_editable_load_missing_file_scaffolds_defaults(tmp_path: Path) -> None:
    from mait_code.cli._dashboard import EditableDashboard

    ed = EditableDashboard.load(tmp_path / "dashboard.toml")
    assert [t.widget for t in ed.tiles] == ["reminders", "board", "inbox", "memory"]
    assert ed.columns == 2
    assert ed.warnings == ()
    ed.save()
    text = (tmp_path / "dashboard.toml").read_text(encoding="utf-8")
    assert text.startswith("# mait-code start page")
    assert "columns" not in text  # the default stays implicit in a fresh file
    assert text.count("[[tile]]") == 4


def test_editable_save_preserves_hand_written_comments(tmp_path: Path) -> None:
    from mait_code.cli._dashboard import EditableDashboard

    path = tmp_path / "dashboard.toml"
    path.write_text(
        "# my precious header\n"
        "columns = 3\n"
        "\n"
        "[[tile]]\n"
        'widget = "board"\n'
        "# a note inside the disk tile\n"
        "[[tile]]\n"
        'command = "df -h /"\n',
        encoding="utf-8",
    )
    ed = EditableDashboard.load(path)
    ed.tiles[0].title = "Work"
    ed.save()
    text = path.read_text(encoding="utf-8")
    assert "# my precious header" in text
    assert "# a note inside the disk tile" in text
    assert 'title = "Work"' in text
    assert "columns = 3" in text
    # The edit round-trips: loading again sees exactly what was saved.
    again = load_dashboard(path)
    assert again.tiles[0].title == "Work"
    assert again.tiles[1].command == "df -h /"


def test_editable_reorder_remove_add_round_trip(tmp_path: Path) -> None:
    from mait_code.cli._dashboard import EditableDashboard, EditableTile

    path = tmp_path / "dashboard.toml"
    path.write_text(
        '[[tile]]\nwidget = "board"\n'
        '[[tile]]\nwidget = "inbox"\n'
        '[[tile]]\ncommand = "uptime"\n',
        encoding="utf-8",
    )
    ed = EditableDashboard.load(path)
    del ed.tiles[1]  # drop inbox
    ed.tiles.reverse()  # uptime first
    ed.tiles.append(EditableTile(widget="health", title="Doctor", span=2))
    ed.save()

    cfg = load_dashboard(path)
    assert [(t.widget, t.command) for t in cfg.tiles] == [
        (None, "uptime"),
        ("board", None),
        ("health", None),
    ]
    assert cfg.tiles[2].title == "Doctor"
    assert cfg.tiles[2].span == 2


def test_editable_clears_defaulted_fields_from_the_file(tmp_path: Path) -> None:
    from mait_code.cli._dashboard import EditableDashboard

    path = tmp_path / "dashboard.toml"
    path.write_text(
        '[[tile]]\nwidget = "board"\ntitle = "Old"\nspan = 2\n', encoding="utf-8"
    )
    ed = EditableDashboard.load(path)
    ed.tiles[0].title = ""
    ed.tiles[0].span = 1
    ed.save()
    text = path.read_text(encoding="utf-8")
    assert "title" not in text
    assert "span" not in text


def test_editable_malformed_file_warns_and_regenerates(tmp_path: Path) -> None:
    from mait_code.cli._dashboard import EditableDashboard

    path = tmp_path / "dashboard.toml"
    path.write_text("columns = [broken", encoding="utf-8")
    ed = EditableDashboard.load(path)
    assert any("could not be read" in w for w in ed.warnings)
    assert [t.widget for t in ed.tiles] == ["reminders", "board", "inbox", "memory"]
    ed.save()
    cfg = load_dashboard(path)
    assert cfg.authored
    assert cfg.warnings == ()


def test_editable_type_switch_swaps_the_keys(tmp_path: Path) -> None:
    from mait_code.cli._dashboard import EditableDashboard

    path = tmp_path / "dashboard.toml"
    path.write_text('[[tile]]\nwidget = "board"\n', encoding="utf-8")
    ed = EditableDashboard.load(path)
    ed.tiles[0].widget = None
    ed.tiles[0].command = "uptime"
    ed.save()
    text = path.read_text(encoding="utf-8")
    assert "widget" not in text
    assert 'command = "uptime"' in text
