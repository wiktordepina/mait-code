"""Tests for the shared ``apply_setting`` write path and ``settings set/get``."""

from __future__ import annotations

import json
import os
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
    env_name_error,
    move_data_dir,
    set_env_var,
    unset_env_var,
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

    def test_bad_float(self, fake_home: Path) -> None:
        # A float-kind setting rejects a non-numeric value at the coercion
        # step, before its own range validator runs.
        with pytest.raises(SettingError, match="must be a number"):
            apply_setting("half-life-episodic", "soon")


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

    def test_refuses_missing_source(self, tmp_path: Path) -> None:
        old = tmp_path / "absent"
        new = tmp_path / "new"
        with pytest.raises(SettingError, match="does not exist"):
            move_data_dir(old, new)

    def test_moves_into_existing_empty_target(self, tmp_path: Path) -> None:
        # An existing but *empty* target is acceptable — it is rmdir'd so the
        # rename/copy lands cleanly rather than nesting under it.
        old = tmp_path / "old"
        old.mkdir()
        (old / "f").write_text("x")
        new = tmp_path / "new"
        new.mkdir()  # exists, empty
        move_data_dir(old, new)
        assert (new / "f").read_text() == "x"
        assert not old.exists()


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


# ---------------------------------------------------------------------------
# Custom [env] variables — set_env_var / unset_env_var and the CLI on top
# ---------------------------------------------------------------------------


class TestEnvVarCore:
    def test_set_adds_and_persists(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        outcome = set_env_var("AWS_PROFILE", "dev-bedrock")
        assert (outcome.old_value, outcome.new_value) == (None, "dev-bedrock")
        assert config.read_env_table() == {"AWS_PROFILE": "dev-bedrock"}
        # Applied to the running process too (and marked as our injection).
        assert os.environ["AWS_PROFILE"] == "dev-bedrock"
        assert "AWS_PROFILE" in config._injected_env

    def test_set_updates_existing(self, fake_home: Path) -> None:
        config.write_settings_file(
            {"embedding-provider": "local"}, env={"AWS_PROFILE": "old"}
        )
        outcome = set_env_var("AWS_PROFILE", "new")
        assert (outcome.old_value, outcome.new_value) == ("old", "new")
        assert config.read_env_table() == {"AWS_PROFILE": "new"}

    def test_set_preserves_flat_settings(self, fake_home: Path) -> None:
        config.write_settings_file({"log-level": "DEBUG"})
        set_env_var("AWS_PROFILE", "dev")
        assert config.read_settings_file()["log-level"] == "DEBUG"

    def test_set_warns_when_shell_shadows(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        monkeypatch.setenv("MAIT_TEST_SHADOW", "from-shell")
        outcome = set_env_var("MAIT_TEST_SHADOW", "from-file")
        assert any("overrides" in w for w in outcome.warnings)
        # The shell export is left alone.
        assert os.environ["MAIT_TEST_SHADOW"] == "from-shell"

    def test_set_rejects_reserved_and_invalid_names(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with pytest.raises(SettingError, match="first-class settings"):
            set_env_var("MAIT_CODE_LOG_LEVEL", "DEBUG")
        with pytest.raises(SettingError, match="valid environment variable"):
            set_env_var("NOT VALID", "x")
        with pytest.raises(SettingError, match="valid environment variable"):
            set_env_var("1LEADING_DIGIT", "x")
        assert config.read_env_table() == {}

    def test_unset_removes_and_cleans_process_env(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        set_env_var("MAIT_TEST_REMOVE_ME", "x")
        assert os.environ["MAIT_TEST_REMOVE_ME"] == "x"
        outcome = unset_env_var("MAIT_TEST_REMOVE_ME")
        assert outcome.old_value == "x"
        assert outcome.new_value is None
        assert config.read_env_table() == {}
        # Our injection is rolled back...
        assert "MAIT_TEST_REMOVE_ME" not in os.environ

    def test_unset_leaves_real_shell_export(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file(
            {"embedding-provider": "local"}, env={"MAIT_TEST_KEEP": "from-file"}
        )
        monkeypatch.setenv("MAIT_TEST_KEEP", "from-shell")
        unset_env_var("MAIT_TEST_KEEP")
        # ...but a variable the shell owns is not touched.
        assert os.environ["MAIT_TEST_KEEP"] == "from-shell"

    def test_unset_unknown_raises(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        with pytest.raises(SettingError, match="not set in the \\[env\\] table"):
            unset_env_var("NOPE")

    def test_name_validation_rules(self) -> None:
        assert env_name_error("AWS_PROFILE") is None
        assert env_name_error("_LEADING_UNDERSCORE") is None
        assert env_name_error("MAIT_CODE_ANYTHING") is not None
        assert env_name_error("has space") is not None
        assert env_name_error("") is not None
        assert env_name_error("9TO5") is not None


class TestEnvVarCli:
    def test_set_get_unset_round_trip(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})

        result = runner.invoke(app, ["settings", "set", "env.AWS_PROFILE", "dev"])
        assert result.exit_code == 0, result.output
        assert "env.AWS_PROFILE: None → 'dev'" in result.output

        result = runner.invoke(app, ["settings", "get", "env.AWS_PROFILE"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("dev\t(settings)")

        result = runner.invoke(app, ["settings", "get", "env.AWS_PROFILE", "--json"])
        assert json.loads(result.output) == {
            "key": "env.AWS_PROFILE",
            "value": "dev",
            "source": "settings",
        }

        result = runner.invoke(app, ["settings", "unset", "env.AWS_PROFILE"])
        assert result.exit_code == 0, result.output
        assert "removed" in result.output
        assert config.read_env_table() == {}

    def test_set_rejects_reserved_name(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(
            app, ["settings", "set", "env.MAIT_CODE_LOG_LEVEL", "DEBUG"]
        )
        assert result.exit_code == 1
        assert "first-class settings" in result.output

    def test_get_unknown_env_var_errors(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "get", "env.NOPE"])
        assert result.exit_code == 1
        assert "not in the [env] table" in result.output

    def test_unset_rejects_registry_keys(self, fake_home: Path) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "unset", "log-level"])
        assert result.exit_code == 1
        assert "only env.<NAME> keys" in result.output
