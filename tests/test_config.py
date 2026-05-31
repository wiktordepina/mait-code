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


def test_theme_setting_registered_with_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setting = next((s for s in config.SETTINGS if s.key == "theme"), None)
    assert setting is not None
    assert setting.env == "MAIT_CODE_THEME"
    assert setting.default == config.DEFAULT_THEME == "mait-dark"
    assert setting.settable is True
    assert setting.choices is None  # free text: valid themes are runtime-only
    # The validator rejects an empty value but accepts any non-empty name.
    assert setting.validate is not None
    assert setting.validate("") is not None
    assert setting.validate("anything") is None
    monkeypatch.delenv("MAIT_CODE_THEME", raising=False)
    assert config.resolve(setting) == (config.DEFAULT_THEME, "default")


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


# ---------------------------------------------------------------------------
# Typed, derived and advanced settings (Setting model extension)
# ---------------------------------------------------------------------------


def _use_settings(monkeypatch: pytest.MonkeyPatch, *settings: config.Setting) -> None:
    """Swap in a temporary SETTINGS registry and reset the key cache."""
    monkeypatch.setattr(config, "SETTINGS", tuple(settings))
    monkeypatch.setattr(config, "_SETTINGS_BY_KEY", {})
    monkeypatch.setattr(config, "_settings_cache", {})


class TestTypedGetters:
    def test_get_int_coerces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_settings(
            monkeypatch,
            config.Setting("retries", "MAIT_CODE_RETRIES", "3", kind="int"),
        )
        monkeypatch.setenv("MAIT_CODE_RETRIES", "9")
        assert config.get_int("retries") == 9

    def test_get_int_falls_back_on_bad_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_settings(
            monkeypatch,
            config.Setting("retries", "MAIT_CODE_RETRIES", "3", kind="int"),
        )
        monkeypatch.setenv("MAIT_CODE_RETRIES", "not-a-number")
        assert config.get_int("retries") == 3

    def test_get_float_coerces_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_settings(
            monkeypatch,
            config.Setting("ratio", "MAIT_CODE_RATIO", "0.4", kind="float"),
        )
        monkeypatch.setenv("MAIT_CODE_RATIO", "0.75")
        assert config.get_float("ratio") == 0.75
        monkeypatch.setenv("MAIT_CODE_RATIO", "huh")
        assert config.get_float("ratio") == 0.4


class TestDerivedSettings:
    def test_resolve_returns_derived_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = config.Setting("answer", "", "", settable=False, derive=lambda: "42")
        _use_settings(monkeypatch, s)
        assert config.resolve(s) == ("42", "derived")
        assert config.get_int("answer") == 42

    def test_derived_value_is_not_an_assignable_toml_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _use_settings(
            monkeypatch,
            config.Setting(
                "db-path",
                "",
                "",
                settable=False,
                derive=lambda: "/tmp/x.db",
                help="where data lives",
            ),
        )
        f = tmp_path / "settings.toml"
        config.write_settings_file({}, path=f)
        content = f.read_text()
        assert "# db-path: where data lives" in content
        assert "db-path = " not in content  # never an assignable line


class TestAdvancedSettings:
    def test_advanced_is_written_commented_out(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _use_settings(
            monkeypatch,
            config.Setting("log-level", "MAIT_CODE_LOG_LEVEL", "INFO"),
            config.Setting(
                "git-timeout",
                "MAIT_CODE_GIT_TIMEOUT",
                "5",
                kind="int",
                advanced=True,
                help="git op timeout",
            ),
        )
        f = tmp_path / "settings.toml"
        config.write_settings_file({}, path=f)
        content = f.read_text()
        assert 'log-level = "INFO"' in content  # primary: uncommented
        assert '# git-timeout = "5"' in content  # advanced: commented-out
        # The default still wins until uncommented.
        assert config.read_settings_file(path=f).get("git-timeout") is None

    def test_advanced_written_active_when_value_given(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _use_settings(
            monkeypatch,
            config.Setting("log-level", "MAIT_CODE_LOG_LEVEL", "INFO"),
            config.Setting(
                "git-timeout",
                "MAIT_CODE_GIT_TIMEOUT",
                "5",
                kind="int",
                advanced=True,
                help="git op timeout",
            ),
        )
        f = tmp_path / "settings.toml"
        config.write_settings_file({"git-timeout": "10"}, path=f)
        content = f.read_text()
        # Opted-in advanced key is written active, not commented.
        assert 'git-timeout = "10"' in content
        assert '# git-timeout = "10"' not in content
        # And it round-trips back through the reader.
        assert config.read_settings_file(path=f).get("git-timeout") == "10"


class TestValidateSettings:
    def test_collects_per_setting_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def must_be_pos(v: str) -> str | None:
            return None if v.isdigit() else "must be a positive integer"

        _use_settings(
            monkeypatch,
            config.Setting("n", "MAIT_CODE_N", "3", kind="int", validate=must_be_pos),
        )
        monkeypatch.setenv("MAIT_CODE_N", "-1")
        errors = config.validate_settings()
        assert errors == ["n: must be a positive integer"]

    def test_healthy_config_has_no_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_settings(
            monkeypatch,
            config.Setting("log-level", "MAIT_CODE_LOG_LEVEL", "INFO"),
        )
        assert config.validate_settings() == []


class TestChoices:
    def test_enum_settings_declare_choices(self) -> None:
        by_key = {s.key: s for s in config.SETTINGS}
        assert by_key["embedding-provider"].choices == ("local", "bedrock")
        assert by_key["log-level"].choices == ("DEBUG", "INFO", "WARNING", "ERROR")

    def test_embedding_provider_choices_match_install(self) -> None:
        # config is the leaf; the install constant must not drift from it.
        from mait_code.cli._install import EMBEDDING_PROVIDERS

        by_key = {s.key: s for s in config.SETTINGS}
        assert by_key["embedding-provider"].choices == EMBEDDING_PROVIDERS

    def test_embedding_provider_validator_rejects_off_choice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        by_key = {s.key: s for s in config.SETTINGS}
        validate = by_key["embedding-provider"].validate
        assert validate is not None
        assert validate("local") is None
        assert validate("openai") is not None


# ---------------------------------------------------------------------------
# Tier 2 derived values — pinned to their runtime path helpers (no drift)
# ---------------------------------------------------------------------------


class TestDerivedRegistry:
    def test_all_derived_keys_are_display_only(self) -> None:
        derived = [s for s in config.SETTINGS if not s.settable]
        assert {s.key for s in derived} == {
            "embedding-dim",
            "memory-db-path",
            "tasks-db-path",
            "decisions-db-path",
            "reminders-db-path",
            "model-cache-dir",
            "observations-dir",
            "project-aliases-path",
        }
        for s in derived:
            assert s.env == ""  # no env var
            assert s.derive is not None
            assert config.resolve(s)[1] == "derived"

    def test_db_paths_match_runtime_helpers(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mait_code.tools.decisions.db import get_db_path as decisions_db
        from mait_code.tools.memory.db import get_db_path as memory_db
        from mait_code.tools.reminders.db import get_db_path as reminders_db
        from mait_code.tools.tasks.db import get_db_path as tasks_db

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("MAIT_CODE_DATA_DIR", raising=False)
        monkeypatch.setattr(config, "_settings_cache", {})

        pairs = {
            "memory-db-path": memory_db,
            "tasks-db-path": tasks_db,
            "decisions-db-path": decisions_db,
            "reminders-db-path": reminders_db,
        }
        for key, helper in pairs.items():
            derived = Path(config.get(key)).expanduser()
            assert derived == helper()

    def test_embedding_dim_matches_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mait_code.tools.memory.embeddings import _get_embedding_dim

        monkeypatch.setattr(config, "_settings_cache", {})
        assert config.get_int("embedding-dim") == _get_embedding_dim()


# ---------------------------------------------------------------------------
# Tier 3 advanced operational knobs
# ---------------------------------------------------------------------------


class TestTier3Advanced:
    # Pin defaults to the constants they replaced — guards silent drift.
    EXPECTED = {
        "log-backup-count": "14",
        "extraction-model": "haiku",
        "reflection-model": "haiku",
        "llm-timeout": "90",
        "reflection-batch-size": "50",
        "reflection-novelty-gate": "3",
        "git-timeout": "5",
    }

    def test_registered_as_advanced_with_expected_defaults(self) -> None:
        by_key = {s.key: s for s in config.SETTINGS}
        for key, default in self.EXPECTED.items():
            assert by_key[key].advanced is True, key
            assert by_key[key].settable is True, key
            assert by_key[key].default == default, key

    def test_validate_flags_bad_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        monkeypatch.setenv("MAIT_CODE_GIT_TIMEOUT", "0")
        monkeypatch.setenv("MAIT_CODE_LOG_LEVEL", "LOUD")
        errors = config.validate_settings()
        assert any(e.startswith("git-timeout:") for e in errors)
        assert any(e.startswith("log-level:") for e in errors)

    def test_healthy_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        for key in self.EXPECTED:
            monkeypatch.delenv(config._by_key()[key].env, raising=False)
        monkeypatch.delenv("MAIT_CODE_LOG_LEVEL", raising=False)
        assert config.validate_settings() == []


# ---------------------------------------------------------------------------
# Tier 4 scoring / dedup knobs + cross-field validation
# ---------------------------------------------------------------------------


class TestTier4Scoring:
    EXPECTED = {
        "score-weight-recency": "0.3",
        "score-weight-importance": "0.3",
        "score-weight-relevance": "0.4",
        "half-life-episodic": "3.0",
        "half-life-semantic": "90.0",
        "dedup-string-threshold": "0.85",
        "dedup-vector-threshold": "0.92",
        "scope-boost-global": "0.7",
        "scope-boost-cross-project": "0.3",
    }

    def test_registered_with_expected_defaults(self) -> None:
        by_key = {s.key: s for s in config.SETTINGS}
        for key, default in self.EXPECTED.items():
            assert by_key[key].advanced is True, key
            assert by_key[key].kind == "float", key
            assert by_key[key].default == default, key

    def test_default_weights_sum_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        for key in self.EXPECTED:
            monkeypatch.delenv(config._by_key()[key].env, raising=False)
        assert config.validate_settings() == []

    def test_bad_weight_sum_is_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        monkeypatch.setenv("MAIT_CODE_SCORE_WEIGHT_RELEVANCE", "0.9")
        errors = config.validate_settings()
        assert any("scoring weights sum to" in e for e in errors)

    def test_out_of_range_threshold_is_flagged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "_settings_cache", {})
        monkeypatch.setenv("MAIT_CODE_DEDUP_VECTOR_THRESHOLD", "1.5")
        errors = config.validate_settings()
        assert any(e.startswith("dedup-vector-threshold:") for e in errors)
