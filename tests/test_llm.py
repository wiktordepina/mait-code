"""Tests for the shared LLM invocation module."""

from unittest.mock import patch

import pytest

from mait_code.llm import call_claude


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for claude CLI calls."""
    with patch("mait_code.llm.subprocess.run") as mock_run:
        yield mock_run


def test_call_claude_basic(mock_subprocess):
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "  Hello world  "
    mock_subprocess.return_value.stderr = ""

    result = call_claude("test prompt")

    assert result == "Hello world"
    mock_subprocess.assert_called_once()
    args = mock_subprocess.call_args
    assert args[0][0] == ["claude", "-p", "--model", "haiku", "--no-session-persistence"]
    assert args[1]["input"] == "test prompt"
    assert args[1]["timeout"] == 60


def test_call_claude_custom_model(mock_subprocess):
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "response"
    mock_subprocess.return_value.stderr = ""

    call_claude("prompt", model="sonnet", timeout=30)

    args = mock_subprocess.call_args
    assert args[0][0] == ["claude", "-p", "--model", "sonnet", "--no-session-persistence"]
    assert args[1]["timeout"] == 30


def test_call_claude_with_system_prompt(mock_subprocess):
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "response"
    mock_subprocess.return_value.stderr = ""

    call_claude("user prompt", system_prompt="be helpful")

    args = mock_subprocess.call_args
    assert "[System instruction]: be helpful" in args[1]["input"]
    assert "user prompt" in args[1]["input"]


def test_call_claude_nonzero_exit(mock_subprocess):
    mock_subprocess.return_value.returncode = 1
    mock_subprocess.return_value.stdout = ""
    mock_subprocess.return_value.stderr = "error occurred"

    result = call_claude("prompt")
    assert result is None


def test_call_claude_not_found(mock_subprocess):
    mock_subprocess.side_effect = FileNotFoundError()

    result = call_claude("prompt")
    assert result is None


def test_call_claude_timeout(mock_subprocess):
    import subprocess

    mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)

    result = call_claude("prompt")
    assert result is None


def test_call_claude_strips_claudecode_env(mock_subprocess):
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "ok"
    mock_subprocess.return_value.stderr = ""

    with patch.dict("os.environ", {"CLAUDECODE": "1", "PATH": "/usr/bin"}, clear=True):
        call_claude("prompt")

    env = mock_subprocess.call_args[1]["env"]
    assert "CLAUDECODE" not in env
    assert "PATH" in env
