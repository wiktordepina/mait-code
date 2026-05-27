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
    # The provider classes must read their defaults from the registry, so a
    # change here can't silently diverge from what `settings` will display.
    from mait_code.tools.memory.embeddings import BedrockProvider, LocalProvider

    assert LocalProvider.DEFAULT_MODEL == config.DEFAULT_EMBEDDING_MODEL
    assert BedrockProvider.DEFAULT_MODEL == config.DEFAULT_BEDROCK_MODEL_ID
    assert BedrockProvider.DEFAULT_REGION == config.DEFAULT_BEDROCK_REGION
