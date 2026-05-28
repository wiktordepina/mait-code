"""Tests for ``mait-code settings`` (read-only, provenance-aware)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from mait_code import config
from mait_code.cli import app
from mait_code.config import (
    Setting,
    collect_settings,
    render as settings_render,
    render_json as settings_render_json,
)
from mait_code.console import console

runner = CliRunner()


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for setting in config.SETTINGS:
        monkeypatch.delenv(setting.env, raising=False)


class TestCollect:
    def test_unset_reports_default_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        snap = collect_settings()
        by_key = {r.key: r for r in snap.settings}
        assert by_key["log-level"].source == "default"
        assert by_key["log-level"].value == config.DEFAULT_LOG_LEVEL
        assert snap.drift is None

    def test_set_reports_env_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        by_key = {r.key: r for r in collect_settings().settings}
        assert by_key["embedding-provider"].source == "env"
        assert by_key["embedding-provider"].value == "bedrock"

    def test_drift_when_env_overrides_settings_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "_settings_cache", {"embedding-provider": "local"})
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        snap = collect_settings()
        assert snap.drift is not None
        assert "bedrock" in snap.drift and "local" in snap.drift

    def test_no_drift_when_env_matches_settings_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            config, "_settings_cache", {"embedding-provider": "bedrock"}
        )
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        assert collect_settings().drift is None

    def test_no_drift_when_no_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setattr(
            config, "_settings_cache", {"embedding-provider": "bedrock"}
        )
        assert collect_settings().drift is None

    def test_settings_source_shown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setattr(
            config, "_settings_cache", {"embedding-provider": "bedrock"}
        )
        snap = collect_settings()
        by_key = {r.key: r for r in snap.settings}
        assert by_key["embedding-provider"].source == "settings"
        assert by_key["embedding-provider"].value == "bedrock"

    def test_secret_value_is_masked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        secret = Setting("token", "MAIT_CODE_FAKE_TOKEN", "", secret=True)
        monkeypatch.setattr(config, "SETTINGS", (secret,))
        monkeypatch.setenv("MAIT_CODE_FAKE_TOKEN", "supersecretvalue")
        masked = collect_settings().settings[0].value
        assert masked == "…alue"
        assert "supersecret" not in masked


class TestRender:
    def test_text_shows_columns_and_migration_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        with console.capture() as cap:
            settings_render(collect_settings())
        out = cap.get()
        assert "SETTING" in out and "VALUE" in out and "SOURCE" in out
        assert "embedding-provider" in out
        # The migration footnote names the actual re-embed command.
        assert "mc-tool-memory reindex" in out

    def test_text_shows_drift_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "_settings_cache", {"embedding-provider": "local"})
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        with console.capture() as cap:
            settings_render(collect_settings())
        out = cap.get()
        assert "mc-tool-memory reindex" in out
        assert "bedrock" in out and "local" in out

    def test_json_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        payload = json.loads(settings_render_json(collect_settings()))
        assert "settings" in payload and "drift" in payload
        assert any(s["key"] == "data-dir" for s in payload["settings"])
        first = payload["settings"][0]
        assert {"key", "value", "source", "requires_migration"} <= set(first)


class TestSettingsCommand:
    def test_cli_runs_and_exits_zero(self) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings"])
        assert result.exit_code == 0

    def test_cli_json(self) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        result = runner.invoke(app, ["settings", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "settings" in payload

    def test_cli_aborts_when_settings_file_missing(self) -> None:
        # No settings.toml exists (XDG config is an isolated temp dir).
        result = runner.invoke(app, ["settings"])
        assert result.exit_code == 1
        assert "settings file not found" in result.output.lower()
        assert "mait-code install" in result.output

    def test_cli_json_aborts_when_settings_file_missing(self) -> None:
        result = runner.invoke(app, ["settings", "--json"])
        assert result.exit_code == 1
        assert "settings file not found" in result.output.lower()
