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

    def test_drift_when_active_provider_differs_from_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        snap = collect_settings(recorded_provider="local")
        assert snap.drift is not None
        assert "bedrock" in snap.drift and "local" in snap.drift

    def test_no_drift_when_provider_matches_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)  # provider falls back to 'local'
        assert collect_settings(recorded_provider="local").drift is None

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
        assert "re-embed" in out  # the migration footnote

    def test_text_shows_drift_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        with console.capture() as cap:
            settings_render(collect_settings(recorded_provider="local"))
        assert "re-embed to switch" in cap.get()

    def test_json_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        payload = json.loads(settings_render_json(collect_settings()))
        assert "settings" in payload and "drift" in payload
        assert any(s["key"] == "data-dir" for s in payload["settings"])
        first = payload["settings"][0]
        assert {"key", "value", "source", "requires_migration"} <= set(first)


class TestSettingsCommand:
    def test_cli_runs_and_exits_zero(self) -> None:
        result = runner.invoke(app, ["settings"])
        assert result.exit_code == 0

    def test_cli_json(self) -> None:
        result = runner.invoke(app, ["settings", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "settings" in payload
