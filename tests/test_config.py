"""Tests for the central configuration registry.

Commit 4 is a pure refactor: these pin the registry's resolution
behaviour and assert it stays single-sourced with the embedding
providers (the drift guard).
"""

from __future__ import annotations

import os
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

    def test_write_cleans_up_tempfile_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If os.replace blows up mid-write, the partial tempfile must not be
        # left behind — the except branch unlinks it and re-raises.
        f = tmp_path / "settings.toml"

        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(config.os, "replace", boom)
        with pytest.raises(OSError, match="disk full"):
            config.write_settings_file({"log-level": "DEBUG"}, path=f)

        # No leftover *.tmp scratch file in the target directory.
        assert not list(tmp_path.glob("settings.toml.*.tmp"))

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


class TestNumericValidators:
    """The numeric validators must reject non-numeric input via their
    ``except`` branch before the range comparison, returning a typed error
    rather than letting ``int``/``float`` raise."""

    def test_positive_int_rejects_non_integer(self) -> None:
        assert config._positive_int("soon") == "must be an integer, got 'soon'"
        assert config._positive_int("3") is None
        # The range comparison still rejects zero / negatives.
        assert config._positive_int("0") == "must be a positive integer, got 0"

    def test_non_negative_int_rejects_non_integer(self) -> None:
        assert config._non_negative_int("nope") == "must be an integer, got 'nope'"
        assert config._non_negative_int("0") is None
        assert config._non_negative_int("-1") == "must be zero or greater, got -1"

    def test_unit_interval_rejects_non_number(self) -> None:
        assert config._unit_interval("x") == "must be a number, got 'x'"
        assert config._unit_interval("0.5") is None
        assert config._unit_interval("2") == "must be in [0, 1], got 2.0"

    def test_positive_float_rejects_non_number(self) -> None:
        assert config._positive_float("y") == "must be a number, got 'y'"
        assert config._positive_float("0.1") is None
        assert config._positive_float("0") == "must be greater than zero, got 0.0"


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
            "reminders-db-path",
            "bridge-config-path",
            "model-cache-dir",
            "observations-dir",
            "project-aliases-path",
            "dashboard-config-path",
        }
        for s in derived:
            assert s.env == ""  # no env var
            assert s.derive is not None
            assert config.resolve(s)[1] == "derived"

    def test_db_paths_match_runtime_helpers(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mait_code.tools.memory.db import get_db_path as memory_db
        from mait_code.tools.reminders.db import get_db_path as reminders_db

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("MAIT_CODE_DATA_DIR", raising=False)
        monkeypatch.setattr(config, "_settings_cache", {})

        pairs = {
            "memory-db-path": memory_db,
            "reminders-db-path": reminders_db,
        }
        for key, helper in pairs.items():
            derived = Path(config.get(key)).expanduser()
            assert derived == helper()

    def test_dashboard_config_path_matches_runtime_helper(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mait_code.cli._dashboard import dashboard_path

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("MAIT_CODE_DATA_DIR", raising=False)
        monkeypatch.setattr(config, "_settings_cache", {})

        derived = Path(config.get("dashboard-config-path")).expanduser()
        assert derived == dashboard_path()

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
        "half-life-procedural": "180.0",
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


# ---------------------------------------------------------------------------
# Custom [env] table — read, write round-trip, and startup injection
# ---------------------------------------------------------------------------


def _write_default_settings_with_env(body: str) -> Path:
    """Write a settings file with an [env] table at the default path.

    The autouse isolation fixture points ``XDG_CONFIG_HOME`` at a temp dir,
    so this is the path the no-arg readers (``read_env_table``,
    ``apply_env``, ``collect_settings``) resolve to.
    """
    from mait_code.cli._paths import settings_path

    sp = settings_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text("[env]\n" + body, encoding="utf-8")
    return sp


class TestEnvTable:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert config.read_env_table(path=tmp_path / "nope.toml") == {}

    def test_read_no_table_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        f.write_text('log-level = "DEBUG"\n')
        assert config.read_env_table(path=f) == {}

    def test_read_values_and_drops_non_strings(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        f.write_text('[env]\nAWS_PROFILE = "dev-bedrock"\nNOT_A_STRING = 5\n')
        assert config.read_env_table(path=f) == {"AWS_PROFILE": "dev-bedrock"}

    def test_flat_reader_ignores_env_table(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        f.write_text('log-level = "DEBUG"\n[env]\nAWS_PROFILE = "dev"\n')
        assert config.read_settings_file(path=f) == {"log-level": "DEBUG"}

    def test_write_with_explicit_env_round_trips(self, tmp_path: Path) -> None:
        import tomllib

        f = tmp_path / "settings.toml"
        env = {"AWS_PROFILE": "dev-bedrock", "WEIRD KEY": 'va"lue\\path'}
        config.write_settings_file({"log-level": "DEBUG"}, path=f, env=env)
        # The file must stay valid TOML and the table must round-trip intact.
        tomllib.loads(f.read_text(encoding="utf-8"))
        assert config.read_env_table(path=f) == env
        assert config.read_settings_file(path=f)["log-level"] == "DEBUG"

    def test_rewrite_preserves_existing_env_table(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        config.write_settings_file({}, path=f, env={"AWS_PROFILE": "dev-bedrock"})
        # A later rewrite that doesn't mention env (settings set, TUI, theme
        # persist, install/update) must carry the table over untouched.
        config.write_settings_file({"log-level": "DEBUG"}, path=f)
        assert config.read_env_table(path=f) == {"AWS_PROFILE": "dev-bedrock"}
        assert config.read_settings_file(path=f)["log-level"] == "DEBUG"

    def test_empty_env_writes_commented_example(self, tmp_path: Path) -> None:
        f = tmp_path / "settings.toml"
        config.write_settings_file({}, path=f)
        content = f.read_text(encoding="utf-8")
        assert "# [env]" in content
        assert '# AWS_PROFILE = "dev-bedrock"' in content
        assert "\n[env]" not in content


class TestApplyEnv:
    def test_injects_missing_var(self) -> None:
        _write_default_settings_with_env('MAIT_TEST_APPLY_VAR = "hello"\n')
        os.environ.pop("MAIT_TEST_APPLY_VAR", None)
        try:
            assert config.apply_env() == ["MAIT_TEST_APPLY_VAR"]
            assert os.environ["MAIT_TEST_APPLY_VAR"] == "hello"
            # Second call is a no-op — the var is now present.
            assert config.apply_env() == []
        finally:
            os.environ.pop("MAIT_TEST_APPLY_VAR", None)

    def test_real_environment_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_default_settings_with_env('MAIT_TEST_APPLY_VAR = "from-file"\n')
        monkeypatch.setenv("MAIT_TEST_APPLY_VAR", "from-env")
        assert config.apply_env() == []
        assert os.environ["MAIT_TEST_APPLY_VAR"] == "from-env"

    def test_mait_code_keys_are_skipped(self) -> None:
        _write_default_settings_with_env('MAIT_CODE_LOG_LEVEL = "DEBUG"\n')
        assert config.apply_env() == []
        assert "MAIT_CODE_LOG_LEVEL" not in os.environ


class TestCollectSettingsEnvRows:
    def test_provenance_and_masking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_default_settings_with_env(
            'AWS_PROFILE = "dev-bedrock"\n'
            'MY_API_TOKEN = "abcdef1234"\n'
            'SHADOWED_VAR = "from-file"\n'
        )
        config.reset_cache()
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("MY_API_TOKEN", raising=False)
        monkeypatch.setenv("SHADOWED_VAR", "from-env")

        rows = {r.key: r for r in config.collect_settings().settings}
        assert rows["env.AWS_PROFILE"].value == "dev-bedrock"
        assert rows["env.AWS_PROFILE"].source == "settings"
        # The real environment carries SHADOWED_VAR, so it wins.
        assert rows["env.SHADOWED_VAR"].value == "from-env"
        assert rows["env.SHADOWED_VAR"].source == "env"
        # Secret-looking names are masked.
        assert rows["env.MY_API_TOKEN"].value == "…1234"

    def test_short_secret_is_fully_masked(self) -> None:
        # A secret of four chars or fewer reveals nothing — the whole value
        # collapses to bullets rather than leaking its (short) length's worth
        # of characters.
        _write_default_settings_with_env('TINY_TOKEN = "abc"\n')
        config.reset_cache()
        rows = {r.key: r for r in config.collect_settings().settings}
        assert rows["env.TINY_TOKEN"].value == "••••"

    def test_no_env_table_adds_no_rows(self) -> None:
        keys = [r.key for r in config.collect_settings().settings]
        assert not [k for k in keys if k.startswith("env.")]

    def test_own_injection_is_not_shadowing(self) -> None:
        """apply_env runs before collect_settings in the real CLI — the var
        it injected must still report source 'settings', not 'env'."""
        _write_default_settings_with_env('MAIT_TEST_INJECTED = "from-file"\n')
        os.environ.pop("MAIT_TEST_INJECTED", None)
        try:
            config.apply_env()
            rows = {r.key: r for r in config.collect_settings().settings}
            assert rows["env.MAIT_TEST_INJECTED"].value == "from-file"
            assert rows["env.MAIT_TEST_INJECTED"].source == "settings"
        finally:
            os.environ.pop("MAIT_TEST_INJECTED", None)
