"""Tests for shared project/branch context detection."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import mait_code.context as context_mod
from mait_code.context import (
    DEFAULT_BRANCHES,
    canonical_project,
    get_branch,
    get_context,
    get_project,
    load_project_aliases,
)


@pytest.fixture(autouse=True)
def _isolate_aliases(tmp_path, monkeypatch):
    """Point the alias map at an empty temp data dir; clear the cache each test."""
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
    context_mod._alias_cache.clear()
    yield
    context_mod._alias_cache.clear()


def _mock_run(returncode=0, stdout="", side_effect=None):
    """Create a mock subprocess.run result or side effect."""
    if side_effect:
        return patch("mait_code.context.subprocess.run", side_effect=side_effect)
    result = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)
    return patch("mait_code.context.subprocess.run", return_value=result)


class TestGetProject:
    def test_returns_git_root_basename(self):
        with _mock_run(returncode=0, stdout="/home/user/GIT/my-project\n"):
            assert get_project() == "my-project"

    def test_falls_back_to_cwd_on_non_git(self):
        with _mock_run(returncode=128, stdout=""):
            result = get_project()
            assert result == Path.cwd().name

    def test_falls_back_on_timeout(self):
        with _mock_run(side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5)):
            result = get_project()
            assert result == Path.cwd().name

    def test_falls_back_on_missing_git(self):
        with _mock_run(side_effect=FileNotFoundError):
            result = get_project()
            assert result == Path.cwd().name


class TestGetBranch:
    def test_returns_feature_branch(self):
        with _mock_run(returncode=0, stdout="feature/scoped-memory\n"):
            assert get_branch() == "feature/scoped-memory"

    def test_returns_none_for_main(self):
        with _mock_run(returncode=0, stdout="main\n"):
            assert get_branch() is None

    def test_returns_none_for_master(self):
        with _mock_run(returncode=0, stdout="master\n"):
            assert get_branch() is None

    def test_returns_none_for_detached_head(self):
        with _mock_run(returncode=0, stdout="HEAD\n"):
            assert get_branch() is None

    def test_returns_none_on_non_git(self):
        with _mock_run(returncode=128, stdout=""):
            assert get_branch() is None

    def test_returns_none_on_timeout(self):
        with _mock_run(side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5)):
            assert get_branch() is None

    def test_returns_none_on_missing_git(self):
        with _mock_run(side_effect=FileNotFoundError):
            assert get_branch() is None


class TestGetContext:
    def test_returns_project_and_branch(self):
        with patch("mait_code.context.get_project", return_value="my-project"):
            with patch("mait_code.context.get_branch", return_value="feature/foo"):
                ctx = get_context()
                assert ctx == {"project": "my-project", "branch": "feature/foo"}

    def test_returns_none_branch_on_main(self):
        with patch("mait_code.context.get_project", return_value="my-project"):
            with patch("mait_code.context.get_branch", return_value=None):
                ctx = get_context()
                assert ctx == {"project": "my-project", "branch": None}


class TestDefaultBranches:
    def test_contains_main_and_master(self):
        assert "main" in DEFAULT_BRANCHES
        assert "master" in DEFAULT_BRANCHES


class TestProjectAliases:
    ALIASES = '{"h-cc-bridge": "hermes-cc-bridge"}'

    def test_no_file_returns_empty(self):
        assert load_project_aliases() == {}

    def test_malformed_file_is_empty(self, tmp_path):
        (tmp_path / "project-aliases.json").write_text("not json{{")
        assert load_project_aliases() == {}

    def test_canonical_resolves_alias(self, tmp_path):
        (tmp_path / "project-aliases.json").write_text(self.ALIASES)
        assert canonical_project("h-cc-bridge") == "hermes-cc-bridge"

    def test_canonical_passes_through_unknown(self, tmp_path):
        (tmp_path / "project-aliases.json").write_text(self.ALIASES)
        assert canonical_project("cairn") == "cairn"

    def test_canonical_none_passes_through(self):
        assert canonical_project(None) is None

    def test_get_project_canonicalises(self, tmp_path):
        (tmp_path / "project-aliases.json").write_text(self.ALIASES)
        with _mock_run(returncode=0, stdout="/home/user/projects/h-cc-bridge\n"):
            assert get_project() == "hermes-cc-bridge"


class TestGitTimeoutSetting:
    def test_git_timeout_is_read_from_setting(self, monkeypatch):
        from mait_code import config

        monkeypatch.setattr(config, "_settings_cache", {})
        monkeypatch.setenv("MAIT_CODE_GIT_TIMEOUT", "7")
        with patch("mait_code.context.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="/x/proj\n"
            )
            get_project()
            assert mock_run.call_args[1]["timeout"] == 7
