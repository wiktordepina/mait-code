"""Branch coverage for ``mait-code uninstall``.

The end-to-end tests in ``test_uninstall.py`` cover the main flow with a
stubbed ``safe_runner``. These tests pin the remaining branches: the real
``_safe_default_runner`` subprocess wrapper, the unreadable-record warning,
the settings-clean exception path, the no-settings skip, and removal of the
centralised TOML settings file (and its now-empty config dir).

All effects land under the ``fake_home`` tmp tree — no real ``~/.claude`` or
``uv`` invocation escapes the sandbox.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mait_code.cli._install import install
from mait_code.cli._paths import install_record_path, mait_code_config_dir
from mait_code.cli._paths import settings_path as mait_settings_path
from mait_code.cli._uninstall import _safe_default_runner, uninstall


def _safe_runner_success(_cmd: list[str]) -> bool:
    return True


# --- _safe_default_runner: real subprocess wrapper (lines 82-88) ---


def test_safe_default_runner_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command that exits 0 returns True."""

    def fake_run(cmd, check, capture_output):  # noqa: ARG001 — signature mirror
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _safe_default_runner(["uv", "tool", "uninstall", "mait-code"]) is True


def test_safe_default_runner_called_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero exit (CalledProcessError) is swallowed and returns False."""

    def fake_run(cmd, check, capture_output):  # noqa: ARG001 — signature mirror
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _safe_default_runner(["uv", "tool", "uninstall", "mait-code"]) is False


def test_safe_default_runner_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """``uv`` not on PATH (FileNotFoundError) is swallowed and returns False."""

    def fake_run(cmd, check, capture_output):  # noqa: ARG001 — signature mirror
        raise FileNotFoundError("uv")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _safe_default_runner(["uv", "tool", "uninstall", "mait-code"]) is False


# --- unreadable install record warning (lines 134-135) ---


def test_corrupt_record_warns_and_continues(fake_home: Path, fake_source: Path) -> None:
    """A malformed install record yields a warning, not a crash."""
    install(source_dir=fake_source)
    # Corrupt the record so ``read_record`` raises RecordError.
    install_record_path().write_text("{ not valid json", encoding="utf-8")

    summary = uninstall(safe_runner=_safe_runner_success)

    assert summary.had_record is True
    assert any("install record unreadable" in w for w in summary.warnings)
    # No symlinks could be resolved (source_dir unknown), so nothing removed.
    assert summary.claude_md_removed is False
    assert summary.skills_removed == []
    # Record is still cleaned up at the end.
    assert not install_record_path().exists()


# --- no settings.json — clean step skipped (branch 152->161) ---


def test_no_settings_file_skips_clean(fake_home: Path, fake_source: Path) -> None:
    """With no settings.json present, the clean step is skipped, not errored."""
    install(source_dir=fake_source)
    settings_json = fake_home / ".claude" / "settings.json"
    if settings_json.exists():
        settings_json.unlink()

    summary = uninstall(safe_runner=_safe_runner_success)

    assert summary.settings_cleaned is False
    assert not any("could not clean" in w for w in summary.warnings)


# --- settings clean raises — warning path (lines 157-158) ---


def test_settings_clean_failure_is_warning(
    fake_home: Path, fake_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An IO failure while cleaning settings.json becomes a warning."""
    install(source_dir=fake_source)
    settings_json = fake_home / ".claude" / "settings.json"
    assert settings_json.exists()  # install merged our settings in

    def boom(_path):
        raise OSError("disk gone")

    # Patch the symbol as imported into the uninstall module.
    monkeypatch.setattr("mait_code.cli._uninstall.read_settings_file", boom)

    summary = uninstall(safe_runner=_safe_runner_success)

    assert summary.settings_cleaned is False
    assert any("could not clean" in w for w in summary.warnings)


# --- centralised TOML settings file removal (lines 162-166) ---


def test_removes_toml_settings_and_empty_config_dir(
    fake_home: Path, fake_source: Path
) -> None:
    """The centralised settings.toml and its now-empty config dir are removed."""
    install(source_dir=fake_source)
    toml = mait_settings_path()
    toml.parent.mkdir(parents=True, exist_ok=True)
    toml.write_text("[settings]\n")
    assert toml.exists()

    uninstall(safe_runner=_safe_runner_success)

    assert not toml.exists()
    # The config dir held only the toml, so it should be gone too.
    assert not mait_code_config_dir().exists()


def test_keeps_config_dir_when_not_empty(fake_home: Path, fake_source: Path) -> None:
    """A config dir with other files survives after the toml is removed."""
    install(source_dir=fake_source)
    config_dir = mait_code_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    toml = mait_settings_path()
    toml.write_text("[settings]\n")
    # A sibling file keeps the directory non-empty.
    (config_dir / "other.txt").write_text("keep me\n")

    uninstall(safe_runner=_safe_runner_success)

    assert not toml.exists()
    assert config_dir.exists()
    assert (config_dir / "other.txt").exists()
