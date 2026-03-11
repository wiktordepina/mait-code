"""Tests for shared project/branch context detection."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from mait_code.context import DEFAULT_BRANCHES, get_branch, get_context, get_project


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
