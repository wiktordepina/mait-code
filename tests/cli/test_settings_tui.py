"""Tests for the Textual ``mait-code settings`` editor.

Textual ships a real headless harness (``App.run_test()`` → pilot), so unlike
the old questionary glue these drive the actual app: navigate the list, edit a
widget, apply, and assert the settings file changed. Each test wraps an async
scenario in ``asyncio.run`` so no pytest-asyncio plugin is needed.

The shared write path (`apply_setting`) is covered exhaustively in
``test_settings_edit``; here we only check the TUI wiring on top of it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, DataTable, Input, RadioButton, RadioSet, Static

from mait_code import config
from mait_code.cli._settings_tui import _WEIGHTS_KEY, SettingsApp, _row_cells


def _run(coro_factory):
    return asyncio.run(coro_factory())


def _select_radio(app: SettingsApp, label: str) -> None:
    """Set the RadioSet selection to the button with the given label."""
    rs = app.query_one("#editor", RadioSet)
    for rb in rs.query(RadioButton):
        if str(rb.label) == label:
            rb.value = True


async def _goto(pilot, app: SettingsApp, key: str) -> None:
    """Move the table cursor to *key*'s row and let the detail panel build."""
    table = app.query_one("#list", DataTable)
    table.move_cursor(row=app._row_order.index(key))
    await pilot.pause()
    await pilot.pause()


class TestNavigation:
    def test_boot_shows_first_setting(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._current_key == "data-dir"
                # data-dir is free text → an Input editor.
                assert app.query_one("#editor", Input) is not None

        _run(scenario)

    def test_enum_setting_uses_radioset(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "log-level")
                rs = app.query_one("#editor", RadioSet)
                assert len(list(rs.query(RadioButton))) == 4

        _run(scenario)

    def test_theme_setting_uses_a_theme_picker(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "theme")
                rs = app.query_one("#editor", RadioSet)
                labels = {str(rb.label) for rb in rs.query(RadioButton)}
                return labels, set(app.available_themes)

        labels, themes = _run(scenario)
        # The picker lists every registered theme, house and built-in alike.
        assert labels == themes
        assert {"mait-dark", "mait-ember", "gruvbox"} <= labels

    def test_apply_theme_persists_and_applies_live(self, fake_home: Path) -> None:
        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "theme")
                _select_radio(app, "mait-ember")
                await pilot.pause()
                app.action_apply()
                await pilot.pause()
                await pilot.pause()
                config.reset_cache()
                return app.theme, config.read_settings_file().get("theme")

        live, saved = _run(scenario)
        assert live == "mait-ember"  # applied to the running app
        assert saved == "mait-ember"  # and persisted to the settings file

    def test_enter_focuses_editor(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "bedrock-region")
                app.query_one("#list", DataTable).focus()
                await pilot.press("enter")
                await pilot.pause()
                return type(app.focused).__name__, getattr(app.focused, "id", None)

        name, widget_id = _run(scenario)
        assert (name, widget_id) == ("Input", "editor")

    def test_escape_returns_focus_to_list(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "bedrock-region")
                app.query_one("#list", DataTable).focus()
                await pilot.press("enter")  # focus the editor
                await pilot.pause()
                in_editor = getattr(app.focused, "id", None)
                await pilot.press("escape")  # back to the list
                await pilot.pause()
                return in_editor, type(app.focused).__name__

        assert _run(scenario) == ("editor", "DataTable")

    def test_single_tab_reaches_editor(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "bedrock-region")
                app.query_one("#list", DataTable).focus()
                await pilot.press("tab")
                await pilot.pause()
                return getattr(app.focused, "id", None)

        assert _run(scenario) == "editor"

    def test_derived_row_is_read_only(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "embedding-dim")
                # No editor widget for a derived value.
                assert not app.query("#editor")
                assert "derived" in str(app.query_one("#source", Static).render())

        _run(scenario)


class TestMigrationMarker:
    def test_marker_on_setting_not_source(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        setting_cell, _value, source_cell = _row_cells("embedding-provider")
        assert "⚠" in str(setting_cell)
        assert "⚠" not in str(source_cell)

    def test_no_marker_on_plain_setting(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        setting_cell, _value, _source = _row_cells("log-level")
        assert "⚠" not in str(setting_cell)

    def test_detail_explains_marker(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "embedding-provider")
                notes = app.query(".warn-note")
                return bool(notes) and "re-embed" in str(notes.first().render())

        assert _run(scenario) is True

    def test_no_note_for_plain_setting(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "log-level")
                return len(app.query(".warn-note"))

        assert _run(scenario) == 0


class TestEditing:
    def test_text_edit_persists(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "bedrock-region")
                app.query_one("#editor", Input).value = "us-east-1"
                await pilot.press("ctrl+s")
                await pilot.pause()
                await pilot.pause()

        _run(scenario)
        config._settings_cache = None
        assert config.read_settings_file()["bedrock-region"] == "us-east-1"

    def test_invalid_value_blocks_apply(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "git-timeout")
                app.query_one("#editor", Input).value = "soon"
                await pilot.press("ctrl+s")
                await pilot.pause()
                assert "✗" in str(app.query_one("#msg", Static).render())

        _run(scenario)
        config._settings_cache = None
        assert "git-timeout" not in config.read_settings_file()

    def test_enum_edit_persists(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "log-level")
                _select_radio(app, "DEBUG")
                await pilot.press("ctrl+s")
                await pilot.pause()
                await pilot.pause()

        _run(scenario)
        config._settings_cache = None
        assert config.read_settings_file()["log-level"] == "DEBUG"


class TestFollowups:
    def test_migration_confirm_yes_runs_reindex(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            with patch.object(SettingsApp, "_run_reindex_suspended") as reindex:
                async with app.run_test() as pilot:
                    await _goto(pilot, app, "embedding-provider")
                    _select_radio(app, "bedrock")
                    await pilot.press("ctrl+s")
                    await pilot.pause()
                    await pilot.click("#yes")
                    await pilot.pause()
                    await pilot.pause()
                return reindex.call_count

        called = _run(scenario)
        config._settings_cache = None
        assert called == 1
        assert config.read_settings_file()["embedding-provider"] == "bedrock"

    def test_migration_confirm_no_defers_reindex(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            with patch.object(SettingsApp, "_run_reindex_suspended") as reindex:
                async with app.run_test() as pilot:
                    await _goto(pilot, app, "embedding-provider")
                    _select_radio(app, "bedrock")
                    await pilot.press("ctrl+s")
                    await pilot.pause()
                    await pilot.click("#no")
                    await pilot.pause()
                    await pilot.pause()
                return reindex.call_count

        called = _run(scenario)
        config._settings_cache = None
        assert called == 0
        assert config.read_settings_file()["embedding-provider"] == "bedrock"


class TestWeights:
    def test_weights_row_present(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                # Grouped row present; individual weight keys are not listed.
                assert _WEIGHTS_KEY in app._row_order
                assert "score-weight-recency" not in app._row_order

        _run(scenario)

    def test_valid_sum_persists_all_three(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, _WEIGHTS_KEY)
                await pilot.press("ctrl+s")  # opens the weights modal
                await pilot.pause()
                await pilot.pause()
                # Modal widgets live on the top screen, not the base screen.
                app.screen.query_one("#w-score-weight-recency", Input).value = "0.2"
                app.screen.query_one("#w-score-weight-importance", Input).value = "0.3"
                app.screen.query_one("#w-score-weight-relevance", Input).value = "0.5"
                await pilot.pause()
                await pilot.click("#w-apply")
                await pilot.pause()
                await pilot.pause()

        _run(scenario)
        config._settings_cache = None
        values = config.read_settings_file()
        assert values["score-weight-recency"] == "0.2"
        assert values["score-weight-importance"] == "0.3"
        assert values["score-weight-relevance"] == "0.5"

    def test_invalid_sum_disables_apply(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, _WEIGHTS_KEY)
                await pilot.press("ctrl+s")
                await pilot.pause()
                await pilot.pause()
                app.screen.query_one("#w-score-weight-recency", Input).value = "0.5"
                app.screen.query_one("#w-score-weight-importance", Input).value = "0.5"
                app.screen.query_one("#w-score-weight-relevance", Input).value = "0.5"
                await pilot.pause()
                return app.screen.query_one("#w-apply", Button).disabled

        disabled = _run(scenario)
        assert disabled is True
        config._settings_cache = None
        # Nothing written.
        assert "score-weight-recency" not in config.read_settings_file()

    def test_cancel_writes_nothing(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, _WEIGHTS_KEY)
                await pilot.press("ctrl+s")
                await pilot.pause()
                await pilot.pause()
                app.screen.query_one("#w-score-weight-recency", Input).value = "0.2"
                app.screen.query_one("#w-score-weight-importance", Input).value = "0.3"
                app.screen.query_one("#w-score-weight-relevance", Input).value = "0.5"
                await pilot.pause()
                await pilot.click("#w-cancel")
                await pilot.pause()

        _run(scenario)
        config._settings_cache = None
        assert "score-weight-recency" not in config.read_settings_file()


class TestFollowupsDataDir:
    def test_data_dir_move_on_confirm(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        old = config.data_dir()
        old.mkdir(parents=True, exist_ok=True)
        (old / "marker").write_text("x")
        new = fake_home / "relocated"

        async def scenario():
            app = SettingsApp()
            async with app.run_test() as pilot:
                await _goto(pilot, app, "data-dir")
                app.query_one("#editor", Input).value = str(new)
                await pilot.press("ctrl+s")
                await pilot.pause()
                await pilot.click("#yes")
                await pilot.pause()
                await pilot.pause()

        _run(scenario)
        config._settings_cache = None
        assert (new / "marker").read_text() == "x"
        assert not old.exists()
        assert config.read_settings_file()["data-dir"] == str(new)
