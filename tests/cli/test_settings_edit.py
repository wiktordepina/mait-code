"""Tests for the shared ``apply_setting`` write path and ``settings set/get``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mait_code import config
from mait_code.cli import app
from mait_code.cli._settings import (
    read_settings_file as read_claude_settings,
    write_settings_file as write_claude_settings,
)
from mait_code.cli._settings_edit import (
    SettingError,
    apply_setting,
    move_data_dir,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# apply_setting — validation / rejection
# ---------------------------------------------------------------------------


class TestApplyRejects:
    def test_unknown_key(self, fake_home: Path) -> None:
        with pytest.raises(SettingError, match="unknown setting"):
            apply_setting("nope", "x")

    def test_derived_key(self, fake_home: Path) -> None:
        with pytest.raises(SettingError, match="derived, read-only"):
            apply_setting("embedding-dim", "768")

    def test_single_weight_rejected(self, fake_home: Path) -> None:
        with pytest.raises(SettingError, match="sum to 1.0"):
            apply_setting("score-weight-recency", "0.5")

    def test_invalid_value(self, fake_home: Path) -> None:
        with pytest.raises(SettingError, match="must be one of"):
            apply_setting("log-level", "LOUD")

    def test_bad_int(self, fake_home: Path) -> None:
        with pytest.raises(SettingError, match="must be an integer"):
            apply_setting("git-timeout", "soon")


# ---------------------------------------------------------------------------
# apply_setting — persistence
# ---------------------------------------------------------------------------


class TestApplyPersists:
    def test_writes_primary_key(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        outcome = apply_setting("log-level", "DEBUG")
        assert outcome.old_value == config.DEFAULT_LOG_LEVEL
        assert outcome.new_value == "DEBUG"
        assert outcome.followup is None
        assert config.read_settings_file()["log-level"] == "DEBUG"

    def test_writes_advanced_key_active(self, fake_home: Path) -> None:
        config.write_settings_file({})
        apply_setting("git-timeout", "10")
        # The advanced opt-in round-trips (not commented out).
        assert config.read_settings_file().get("git-timeout") == "10"

    def test_preserves_other_keys(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        apply_setting("log-level", "WARNING")
        values = config.read_settings_file()
        assert values["embedding-provider"] == "local"
        assert values["log-level"] == "WARNING"


# ---------------------------------------------------------------------------
# enforcement — settings.json mirror sync + shell-shadow warning
# ---------------------------------------------------------------------------


class TestEnforce:
    def test_syncs_already_mirrored_key(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        cj_path = fake_home / ".claude" / "settings.json"
        write_claude_settings(
            cj_path, {"env": {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}}
        )
        apply_setting("embedding-provider", "bedrock", reindex=False)
        env = read_claude_settings(cj_path)["env"]
        assert env["MAIT_CODE_EMBEDDING_PROVIDER"] == "bedrock"

    def test_does_not_add_unmirrored_key(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        cj_path = fake_home / ".claude" / "settings.json"
        write_claude_settings(cj_path, {"env": {}})
        apply_setting("log-level", "DEBUG")
        env = read_claude_settings(cj_path).get("env", {})
        assert "MAIT_CODE_LOG_LEVEL" not in env

    def test_warns_on_shell_export(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"log-level": "INFO"})
        monkeypatch.setenv("MAIT_CODE_LOG_LEVEL", "ERROR")
        outcome = apply_setting("log-level", "DEBUG")
        assert any("exported as $MAIT_CODE_LOG_LEVEL" in w for w in outcome.warnings)


# ---------------------------------------------------------------------------
# follow-ups
# ---------------------------------------------------------------------------


class TestFollowups:
    def test_migration_requires_decision(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with pytest.raises(SettingError, match="--reindex"):
            apply_setting("embedding-provider", "bedrock")

    def test_migration_reindex_runs(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with patch("mait_code.tools.memory.cli.run_reindex", return_value=3) as reindex:
            outcome = apply_setting("embedding-provider", "bedrock", reindex=True)
        reindex.assert_called_once()
        assert outcome.followup == "reindex"
        assert outcome.followup_done is True

    def test_migration_deferred(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with patch("mait_code.tools.memory.cli.run_reindex") as reindex:
            outcome = apply_setting("embedding-provider", "bedrock", reindex=False)
        reindex.assert_not_called()
        assert outcome.followup == "reindex"
        assert outcome.followup_done is False

    def test_data_dir_requires_decision(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with pytest.raises(SettingError, match="--move-data"):
            apply_setting("data-dir", str(fake_home / "newdata"))

    def test_data_dir_move_runs(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        old = config.data_dir()
        old.mkdir(parents=True, exist_ok=True)
        (old / "marker.txt").write_text("hi")
        new = fake_home / "relocated-data"
        outcome = apply_setting("data-dir", str(new), move_data=True)
        assert outcome.followup_done is True
        assert (new / "marker.txt").read_text() == "hi"
        assert not old.exists()

    def test_confirm_callback_used_by_editor(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with patch("mait_code.tools.memory.cli.run_reindex", return_value=0):
            outcome = apply_setting(
                "embedding-provider", "bedrock", confirm=lambda _p: True
            )
        assert outcome.followup_done is True


# ---------------------------------------------------------------------------
# move_data_dir
# ---------------------------------------------------------------------------


class TestMoveDataDir:
    def test_moves_directory(self, tmp_path: Path) -> None:
        old = tmp_path / "old"
        old.mkdir()
        (old / "f").write_text("x")
        new = tmp_path / "new"
        move_data_dir(old, new)
        assert (new / "f").read_text() == "x"
        assert not old.exists()

    def test_refuses_nonempty_target(self, tmp_path: Path) -> None:
        old = tmp_path / "old"
        old.mkdir()
        new = tmp_path / "new"
        new.mkdir()
        (new / "existing").write_text("keep")
        with pytest.raises(SettingError, match="not empty"):
            move_data_dir(old, new)

    def test_noop_when_same(self, tmp_path: Path) -> None:
        old = tmp_path / "d"
        old.mkdir()
        move_data_dir(old, old)  # no error
        assert old.exists()


# ---------------------------------------------------------------------------
# CLI: settings set / get
# ---------------------------------------------------------------------------


class TestSetCommand:
    def test_set_persists(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "set", "log-level", "DEBUG"])
        assert result.exit_code == 0, result.output
        assert config.read_settings_file()["log-level"] == "DEBUG"

    def test_set_invalid_value_exits_1(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "set", "log-level", "LOUD"])
        assert result.exit_code == 1
        assert "must be one of" in result.output

    def test_set_migration_without_flag_errors(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(
            app, ["settings", "set", "embedding-provider", "bedrock"]
        )
        assert result.exit_code == 1
        assert "--reindex" in result.output

    def test_set_migration_no_reindex(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(
            app,
            ["settings", "set", "embedding-provider", "bedrock", "--no-reindex"],
        )
        assert result.exit_code == 0, result.output
        assert config.read_settings_file()["embedding-provider"] == "bedrock"


class TestGetCommand:
    def test_get_value_and_source(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "bedrock"})
        result = runner.invoke(app, ["settings", "get", "embedding-provider"])
        assert result.exit_code == 0, result.output
        assert "bedrock" in result.output
        assert "settings" in result.output

    def test_get_json(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "get", "log-level", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["key"] == "log-level"
        assert payload["value"] == config.DEFAULT_LOG_LEVEL
        assert payload["source"] in {"settings", "default"}

    def test_get_unknown_exits_1(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "get", "nope"])
        assert result.exit_code == 1
