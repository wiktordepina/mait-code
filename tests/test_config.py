"""Tests for the central configuration registry.

Commit 4 is a pure refactor: these pin the registry's resolution
behaviour and assert it stays single-sourced with the embedding
providers (the drift guard).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mait_code import config


def test_registry_keys_are_unique_and_kebab_case() -> None:
    keys = [s.key for s in config.SETTINGS]
    assert len(keys) == len(set(keys))
    assert all(k == k.lower() and " " not in k for k in keys)
    # The internal recursion guard must not be exposed as a setting.
    assert all("MAIT_CODE_NESTED" not in s.env for s in config.SETTINGS)


def test_migration_sensitive_knobs_are_flagged() -> None:
    by_key = {s.key: s for s in config.SETTINGS}
    for key in ("embedding-provider", "embedding-model", "bedrock-model-id"):
        assert by_key[key].requires_migration is True
    for key in ("data-dir", "log-level", "bedrock-region"):
        assert by_key[key].requires_migration is False


def test_resolve_reports_env_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    setting = next(s for s in config.SETTINGS if s.key == "log-level")

    monkeypatch.delenv(setting.env, raising=False)
    value, source = config.resolve(setting)
    assert (value, source) == (config.DEFAULT_LOG_LEVEL, "default")

    monkeypatch.setenv(setting.env, "DEBUG")
    assert config.resolve(setting) == ("DEBUG", "env")


def test_resolve_treats_blank_env_as_default(monkeypatch: pytest.MonkeyPatch) -> None:
    setting = next(s for s in config.SETTINGS if s.key == "log-level")
    monkeypatch.setenv(setting.env, "   ")
    value, source = config.resolve(setting)
    assert source == "default"


def test_data_dir_honours_env_and_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    monkeypatch.delenv("MAIT_CODE_DATA_DIR", raising=False)
    assert config.data_dir() == tmp_path / ".claude" / "mait-code-data"

    custom = tmp_path / "elsewhere"
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(custom))
    assert config.data_dir() == custom

    # Blank / whitespace override falls back to the default, not Path("").
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", "  ")
    assert config.data_dir() == tmp_path / ".claude" / "mait-code-data"


def test_defaults_are_single_sourced_with_embedding_providers() -> None:
    from mait_code.tools.memory.embeddings import BedrockProvider, LocalProvider

    assert LocalProvider.DEFAULT_MODEL == config.DEFAULT_EMBEDDING_MODEL
    assert BedrockProvider.DEFAULT_MODEL == config.DEFAULT_BEDROCK_MODEL_ID
    assert BedrockProvider.DEFAULT_REGION == config.DEFAULT_BEDROCK_REGION


# ---------------------------------------------------------------------------
# Three-tier resolution: env → settings file → default
# ---------------------------------------------------------------------------


class TestThreeTierResolution:
    def test_env_wins_over_settings_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(config, "_settings_cache", None)
        settings_file = tmp_path / "settings.toml"
        settings_file.write_text('embedding-provider = "local"\n')
        monkeypatch.setattr(
            config,
            "read_settings_file",
            lambda path=None: {"embedding-provider": "local"},
        )
        monkeypatch.setenv("MAIT_CODE_EMBEDDING_PROVIDER", "bedrock")
        setting = next(s for s in config.SETTINGS if s.key == "embedding-provider")
        value, source = config.resolve(setting)
        assert value == "bedrock"
        assert source == "env"

    def test_settings_file_wins_over_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            config, "_settings_cache", {"embedding-provider": "bedrock"}
        )
        monkeypatch.delenv("MAIT_CODE_EMBEDDING_PROVIDER", raising=False)
        setting = next(s for s in config.SETTINGS if s.key == "embedding-provider")
        value, source = config.resolve(setting)
        assert value == "bedrock"
        assert source == "settings"

    def test_falls_to_default_when_no_file_or_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        monkeypatch.delenv("MAIT_CODE_EMBEDDING_PROVIDER", raising=False)
        setting = next(s for s in config.SETTINGS if s.key == "embedding-provider")
        value, source = config.resolve(setting)
        assert value == config.DEFAULT_EMBEDDING_PROVIDER
        assert source == "default"


class TestGet:
    def test_returns_value_without_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        monkeypatch.delenv("MAIT_CODE_LOG_LEVEL", raising=False)
        assert config.get("log-level") == config.DEFAULT_LOG_LEVEL

    def test_raises_on_unknown_key(self) -> None:
        with pytest.raises(KeyError):
            config.get("nonexistent-key")


# ---------------------------------------------------------------------------
# Settings file I/O (TOML)
# ---------------------------------------------------------------------------


class TestSettingsFileIO:
    def test_read_missing_returns_empty(self, tmp_path: Path) -> None:
        assert config.read_settings_file(path=tmp_path / "nope.toml") == {}

    def test_read_malformed_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.toml"
        bad.write_text("not valid toml [[[")
        assert config.read_settings_file(path=bad) == {}

    def test_read_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.toml"
        f.write_text('embedding-provider = "bedrock"\nlog-level = "DEBUG"\n')
        result = config.read_settings_file(path=f)
        assert result == {"embedding-provider": "bedrock", "log-level": "DEBUG"}

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "settings.toml"
        config.write_settings_file({"log-level": "DEBUG"}, path=deep)
        assert deep.exists()
        content = deep.read_text()
        assert 'log-level = "DEBUG"' in content

    def test_write_includes_all_settings_with_comments(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        config.write_settings_file({"embedding-provider": "bedrock"}, path=f)
        content = f.read_text()
        for setting in config.SETTINGS:
            assert setting.help in content
        assert 'embedding-provider = "bedrock"' in content
        assert 'data-dir = "~/.claude/mait-code-data"' in content

    def test_round_trip(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        config.write_settings_file(
            {"embedding-provider": "bedrock", "log-level": "DEBUG"}, path=f
        )
        result = config.read_settings_file(path=f)
        assert result["embedding-provider"] == "bedrock"
        assert result["log-level"] == "DEBUG"
        assert result["data-dir"] == "~/.claude/mait-code-data"
