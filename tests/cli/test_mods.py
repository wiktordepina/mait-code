"""Tests for the optional mait-companion mod's Python side.

The ``mods`` setting decides whether ``~/.claude/settings.json`` names the mod
folder in ``CLAUDE_CODE_PLUGIN_DIRS``. Install, update, uninstall and every
settings write path (CLI, settings TUI, hub) keep the two in step through
:func:`~mait_code.cli._settings.sync_mod_dir`; ``doctor`` reports drift.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mait_code import config
from mait_code.cli import app
from mait_code.cli._doctor import _check_mods
from mait_code.cli._install import install
from mait_code.cli._record import InstallRecord, write_record
from mait_code.cli._settings import (
    PLUGIN_DIRS_ENV,
    mod_dir,
    mod_registered,
    read_settings_file,
    sync_mod_dir,
    unmerge_settings,
    write_settings_file,
)
from mait_code.cli._settings_edit import apply_setting

runner = CliRunner()

OTHER = "/opt/plugins/other"


def _dirs(settings: dict) -> list[str]:
    return settings["env"][PLUGIN_DIRS_ENV].split(os.pathsep)


# ---------------------------------------------------------------------------
# sync_mod_dir / mod_registered / unmerge — pure
# ---------------------------------------------------------------------------


class TestSyncModDir:
    def test_adds_folder_to_empty_settings(self, tmp_path: Path) -> None:
        folder = mod_dir(tmp_path)
        assert sync_mod_dir({}, folder) == {"env": {PLUGIN_DIRS_ENV: str(folder)}}

    def test_keeps_other_plugin_dirs_in_order(self, tmp_path: Path) -> None:
        folder = mod_dir(tmp_path)
        settings = {"env": {PLUGIN_DIRS_ENV: OTHER, "KEEP": "1"}}
        synced = sync_mod_dir(settings, folder)
        assert _dirs(synced) == [OTHER, str(folder)]
        assert synced["env"]["KEEP"] == "1"

    def test_replaces_a_stale_mod_folder(self, tmp_path: Path) -> None:
        stale = "/old/clone/mods/mait-companion"
        settings = {"env": {PLUGIN_DIRS_ENV: os.pathsep.join([stale, OTHER])}}
        synced = sync_mod_dir(settings, mod_dir(tmp_path))
        assert _dirs(synced) == [OTHER, str(mod_dir(tmp_path))]

    def test_idempotent(self, tmp_path: Path) -> None:
        once = sync_mod_dir({}, mod_dir(tmp_path))
        assert sync_mod_dir(once, mod_dir(tmp_path)) == once

    def test_removal_leaves_other_dirs(self) -> None:
        settings = {
            "env": {
                PLUGIN_DIRS_ENV: os.pathsep.join(["~/x/mods/mait-companion", OTHER])
            }
        }
        assert sync_mod_dir(settings, None) == {"env": {PLUGIN_DIRS_ENV: OTHER}}

    def test_removal_drops_empty_variable_and_env(self, tmp_path: Path) -> None:
        settings = {"env": {PLUGIN_DIRS_ENV: str(mod_dir(tmp_path))}, "model": "x"}
        assert sync_mod_dir(settings, None) == {"model": "x"}

    def test_does_not_mutate_input(self, tmp_path: Path) -> None:
        settings = {"env": {PLUGIN_DIRS_ENV: OTHER}}
        sync_mod_dir(settings, mod_dir(tmp_path))
        assert settings == {"env": {PLUGIN_DIRS_ENV: OTHER}}

    def test_ignores_a_similarly_named_folder(self) -> None:
        # Only a trailing mods/mait-companion is ours.
        settings = {"env": {PLUGIN_DIRS_ENV: "/x/mait-companion"}}
        assert sync_mod_dir(settings, None) == settings
        assert mod_registered(settings) is None

    def test_tolerates_a_non_string_variable(self) -> None:
        assert sync_mod_dir({"env": {PLUGIN_DIRS_ENV: 3}}, None) == {}


def test_mod_registered(tmp_path: Path) -> None:
    folder = str(mod_dir(tmp_path))
    settings = {"env": {PLUGIN_DIRS_ENV: os.pathsep.join([OTHER, folder])}}
    assert mod_registered(settings) == folder
    assert mod_registered({}) is None


def test_unmerge_unloads_the_mod(tmp_path: Path) -> None:
    folder = str(mod_dir(tmp_path))
    settings = {
        "env": {
            PLUGIN_DIRS_ENV: os.pathsep.join([folder, OTHER]),
            "MAIT_CODE_MODS": "x",
        }
    }
    assert unmerge_settings(settings) == {"env": {PLUGIN_DIRS_ENV: OTHER}}


# ---------------------------------------------------------------------------
# install / apply_setting — the settings.json side effect
# ---------------------------------------------------------------------------


def _claude_settings(home: Path) -> dict:
    return read_settings_file(home / ".claude" / "settings.json")


class TestInstall:
    def test_mod_not_loaded_by_default(
        self, fake_home: Path, fake_source: Path
    ) -> None:
        install(source_dir=fake_source)
        assert mod_registered(_claude_settings(fake_home)) is None

    def test_mod_loaded_when_enabled(
        self, fake_home: Path, fake_source: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_MODS", "enabled")
        install(source_dir=fake_source)
        registered = mod_registered(_claude_settings(fake_home))
        assert registered == str(mod_dir(fake_source.resolve()))


class TestApplyMods:
    @pytest.fixture
    def installed(self, fake_home: Path, fake_source: Path) -> Path:
        write_record(InstallRecord.new(source_dir=fake_source))
        folder = mod_dir(fake_source.resolve())
        folder.mkdir(parents=True)
        return folder

    def test_enable_then_disable(self, fake_home: Path, installed: Path) -> None:
        cj = fake_home / ".claude" / "settings.json"
        write_settings_file(cj, {"env": {PLUGIN_DIRS_ENV: OTHER}})

        outcome = apply_setting("mods", "enabled")
        assert outcome.warnings == []
        assert _dirs(_claude_settings(fake_home)) == [OTHER, str(installed)]

        apply_setting("mods", "disabled")
        assert _claude_settings(fake_home) == {"env": {PLUGIN_DIRS_ENV: OTHER}}

    def test_disable_inside_a_session_unloads(
        self, fake_home: Path, installed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A Claude Code session exports the settings.json mirror; the written
        # value, not that stale export, must decide the plugin dirs.
        apply_setting("mods", "enabled")
        monkeypatch.setenv("MAIT_CODE_MODS", "enabled")
        apply_setting("mods", "disabled")
        assert mod_registered(_claude_settings(fake_home)) is None

    def test_disable_without_settings_json_writes_nothing(
        self, fake_home: Path, installed: Path
    ) -> None:
        apply_setting("mods", "disabled")
        assert not (fake_home / ".claude" / "settings.json").exists()

    def test_warns_without_install_record(self, fake_home: Path) -> None:
        outcome = apply_setting("mods", "enabled")
        assert any("mait-code install" in w for w in outcome.warnings)
        assert mod_registered(_claude_settings(fake_home)) is None

    def test_warns_when_folder_missing(self, fake_home: Path, installed: Path) -> None:
        installed.rmdir()
        outcome = apply_setting("mods", "enabled")
        assert any("is missing" in w for w in outcome.warnings)
        # Still registered: `update` restores the folder, and the entry with it.
        assert mod_registered(_claude_settings(fake_home)) == str(installed)

    def test_rejects_bad_value(self, fake_home: Path) -> None:
        from mait_code.cli._settings_edit import SettingError

        with pytest.raises(SettingError, match="must be one of"):
            apply_setting("mods", "yes please")

    def test_cli_notes_new_sessions(self, fake_home: Path, installed: Path) -> None:
        config.write_settings_file({})
        result = runner.invoke(app, ["settings", "set", "mods", "enabled"])
        assert result.exit_code == 0, result.output
        assert "new Claude Code sessions" in result.output


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


class TestDoctorMods:
    def _write(self, home: Path, folder: Path | None) -> Path:
        cdir = home / ".claude"
        write_settings_file(cdir / "settings.json", sync_mod_dir({}, folder))
        return cdir

    def test_default_off_is_ok(self, fake_home: Path) -> None:
        check = _check_mods(self._write(fake_home, None), None)
        assert (check.level, check.message) == ("ok", "disabled (the default)")

    def test_off_but_loaded_warns(self, fake_home: Path, tmp_path: Path) -> None:
        check = _check_mods(self._write(fake_home, mod_dir(tmp_path)), None)
        assert check.level == "warn"
        assert "still loads" in check.message

    def test_on_but_unloaded_warns(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_MODS", "enabled")
        check = _check_mods(self._write(fake_home, None), None)
        assert check.level == "warn"
        assert "missing from" in check.message

    def test_on_from_another_source_warns(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_MODS", "enabled")
        cdir = self._write(fake_home, mod_dir(tmp_path / "old"))
        check = _check_mods(cdir, tmp_path / "new")
        assert check.level == "warn"
        assert "not this install's" in check.message

    def test_on_with_missing_folder_warns(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_MODS", "enabled")
        check = _check_mods(self._write(fake_home, mod_dir(tmp_path)), tmp_path)
        assert check.level == "warn"
        assert "does not exist" in check.message

    def test_on_and_loaded_is_ok(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_MODS", "enabled")
        mod_dir(tmp_path).mkdir(parents=True)
        check = _check_mods(self._write(fake_home, mod_dir(tmp_path)), tmp_path)
        assert check.level == "ok"


# ---------------------------------------------------------------------------
# settings get theme --palette
# ---------------------------------------------------------------------------


class TestPaletteCli:
    def test_emits_resolved_palette(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({})
        monkeypatch.setenv("MAIT_CODE_THEME", "mait-ember")
        result = runner.invoke(app, ["settings", "get", "theme", "--palette"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["theme"] == data["resolved"] == "mait-ember"
        assert data["palette"]["primary"] == "#F2A65A"

    def test_reports_fallback(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({})
        monkeypatch.setenv("MAIT_CODE_THEME", "ansi-dark")
        data = json.loads(
            runner.invoke(app, ["settings", "get", "theme", "--palette"]).output
        )
        assert (data["theme"], data["resolved"]) == ("ansi-dark", "mait-dark")

    def test_refuses_other_keys(self, fake_home: Path) -> None:
        config.write_settings_file({})
        result = runner.invoke(app, ["settings", "get", "log-level", "--palette"])
        assert result.exit_code == 1
