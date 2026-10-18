"""Tests for the shared LLM invocation module."""

import subprocess as _subprocess
from unittest.mock import MagicMock, patch

import pytest

from mait_code.llm import ProbeResult, call_claude, probe_claude


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for claude CLI calls."""
    with patch("mait_code.llm.subprocess.run") as mock_run:
        yield mock_run


@pytest.fixture
def mock_sleep():
    """Mock time.sleep to avoid delays in retry tests."""
    with patch("mait_code.llm.time.sleep") as mock:
        yield mock


def test_call_claude_basic(mock_subprocess):
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "  Hello world  "
    mock_subprocess.return_value.stderr = ""

    result = call_claude("test prompt")

    assert result == "Hello world"
    mock_subprocess.assert_called_once()
    args = mock_subprocess.call_args
    assert args[0][0] == [
        "claude",
        "-p",
        "--model",
        "haiku",
        "--no-session-persistence",
        "--tools",
        "",
        "--disallowedTools",
        "mcp__*",
        "--safe-mode",
    ]
    assert args[1]["input"] == "test prompt"
    # Default timeout follows the llm-timeout setting (90 by default).
    from mait_code import config

    assert args[1]["timeout"] == config.get_int("llm-timeout")


def test_call_claude_default_timeout_reads_setting(mock_subprocess, monkeypatch):
    from mait_code import config

    monkeypatch.setattr(config, "_settings_cache", {})
    monkeypatch.setenv("MAIT_CODE_LLM_TIMEOUT", "123")
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "ok"
    mock_subprocess.return_value.stderr = ""

    call_claude("prompt")

    assert mock_subprocess.call_args[1]["timeout"] == 123


def test_call_claude_custom_model(mock_subprocess):
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "response"
    mock_subprocess.return_value.stderr = ""

    call_claude("prompt", model="sonnet", timeout=30)

    args = mock_subprocess.call_args
    assert args[0][0] == [
        "claude",
        "-p",
        "--model",
        "sonnet",
        "--no-session-persistence",
        "--tools",
        "",
        "--disallowedTools",
        "mcp__*",
        "--safe-mode",
    ]
    assert args[1]["timeout"] == 30


def test_call_claude_disables_every_tool(mock_subprocess):
    """call_claude passes the flags that disable built-in tools and MCP servers.

    Prompts embed transcript windows; with tools available, a transcript that
    reads like a task gets carried out (files written, commits pushed). This
    pins the command line only: that the flags take effect is Claude Code's
    behaviour, measured on 2.1.302 (``mait-code doctor`` checks it live).
    ``--tools ""`` alone leaves every MCP tool available, and
    ``--strict-mcp-config`` is refused under a managed MCP config, so it
    must not come back.
    """
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "ok"
    mock_subprocess.return_value.stderr = ""

    call_claude("prompt")

    cmd = mock_subprocess.call_args[0][0]
    tools_at = cmd.index("--tools")
    assert cmd[tools_at + 1] == ""
    deny_at = cmd.index("--disallowedTools")
    assert cmd[deny_at + 1] == "mcp__*"
    assert "--safe-mode" in cmd
    assert "--strict-mcp-config" not in cmd
    assert "--mcp-config" not in cmd
    assert not any(a.startswith("--allowed") for a in cmd)


def test_call_claude_runs_from_data_dir(mock_subprocess, monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(data))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "ok"
    mock_subprocess.return_value.stderr = ""

    call_claude("prompt")

    assert mock_subprocess.call_args[1]["cwd"] == data


def test_call_claude_cwd_falls_back_to_home(mock_subprocess, monkeypatch, tmp_path):
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("HOME", str(tmp_path))
    mock_subprocess.return_value.returncode = 0
    mock_subprocess.return_value.stdout = "ok"
    mock_subprocess.return_value.stderr = ""

    call_claude("prompt")

    assert mock_subprocess.call_args[1]["cwd"] == tmp_path


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


class TestRetryBackoff:
    def test_retries_on_timeout_then_succeeds(self, mock_subprocess, mock_sleep):
        success = MagicMock()
        success.returncode = 0
        success.stdout = "ok"
        success.stderr = ""

        mock_subprocess.side_effect = [
            _subprocess.TimeoutExpired(cmd="claude", timeout=60),
            success,
        ]

        result = call_claude("prompt", retries=2)
        assert result == "ok"
        assert mock_subprocess.call_count == 2
        mock_sleep.assert_called_once_with(1.0)  # 2.0 ** 0

    def test_retries_on_nonzero_exit_then_succeeds(self, mock_subprocess, mock_sleep):
        fail = MagicMock()
        fail.returncode = 1
        fail.stdout = ""
        fail.stderr = "error"

        success = MagicMock()
        success.returncode = 0
        success.stdout = "ok"
        success.stderr = ""

        mock_subprocess.side_effect = [fail, fail, success]

        result = call_claude("prompt", retries=3)
        assert result == "ok"
        assert mock_subprocess.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)  # 2.0 ** 0
        mock_sleep.assert_any_call(2.0)  # 2.0 ** 1

    def test_no_retry_on_file_not_found(self, mock_subprocess, mock_sleep):
        mock_subprocess.side_effect = FileNotFoundError()

        result = call_claude("prompt", retries=2)
        assert result is None
        assert mock_subprocess.call_count == 1
        mock_sleep.assert_not_called()

    def test_retries_exhausted_returns_none(self, mock_subprocess, mock_sleep):
        mock_subprocess.side_effect = _subprocess.TimeoutExpired(
            cmd="claude", timeout=60
        )

        result = call_claude("prompt", retries=2)
        assert result is None
        assert mock_subprocess.call_count == 3
        assert mock_sleep.call_count == 2

    def test_default_no_retry(self, mock_subprocess):
        mock_subprocess.side_effect = _subprocess.TimeoutExpired(
            cmd="claude", timeout=60
        )

        result = call_claude("prompt")
        assert result is None
        assert mock_subprocess.call_count == 1

    def test_negative_retries_makes_no_attempt(self, mock_subprocess):
        """A negative retry count means an empty attempt loop — falls through to None.

        ``range(1 + retries)`` is empty when ``retries < 0``, so the subprocess
        is never invoked and the post-loop ``return None`` guard is reached.
        """
        result = call_claude("prompt", retries=-1)
        assert result is None
        mock_subprocess.assert_not_called()

    def test_custom_backoff_base(self, mock_subprocess, mock_sleep):
        fail = MagicMock()
        fail.returncode = 1
        fail.stdout = ""
        fail.stderr = "error"

        success = MagicMock()
        success.returncode = 0
        success.stdout = "ok"
        success.stderr = ""

        mock_subprocess.side_effect = [fail, success]

        result = call_claude("prompt", retries=1, backoff_base=5.0)
        assert result == "ok"
        mock_sleep.assert_called_once_with(1.0)  # 5.0 ** 0 = 1.0


class TestRefusal:
    """A refused command line fails identically every time: no retries."""

    @pytest.mark.parametrize(
        "stderr",
        [
            "You cannot use --strict-mcp-config when an enterprise MCP config "
            "is present",
            "error: unknown option '--safe-mode'",
        ],
    )
    def test_refusal_is_not_retried(
        self, mock_subprocess, mock_sleep, stderr, caplog, monkeypatch
    ):
        import logging

        # setup_logging() (run by earlier tests) sets propagate=False on the
        # mait_code logger, which hides records from caplog.
        monkeypatch.setattr(logging.getLogger("mait_code"), "propagate", True)
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stdout = ""
        mock_subprocess.return_value.stderr = stderr

        with caplog.at_level("ERROR", logger="mait_code.llm"):
            result = call_claude("prompt", retries=2)

        assert result is None
        mock_subprocess.assert_called_once()
        mock_sleep.assert_not_called()
        # Logged in full at error level, not truncated as a warning.
        assert any(
            r.levelname == "ERROR" and stderr in r.message for r in caplog.records
        )

    def test_other_failures_still_retry(self, mock_subprocess, mock_sleep):
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stdout = ""
        mock_subprocess.return_value.stderr = "API Error: 529 overloaded"

        assert call_claude("prompt", retries=2) is None
        assert mock_subprocess.call_count == 3


class TestProbe:
    _INIT = (
        '{"type":"system","subtype":"init","tools":%s,"mcp_servers":%s}\n'
        '{"type":"result","result":"ok"}\n'
    )

    def _run(self, mock_subprocess, tools: str, servers: str) -> ProbeResult:
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = self._INIT % (tools, servers)
        mock_subprocess.return_value.stderr = ""
        return probe_claude(timeout=5)

    def test_uses_call_claudes_command_line(self, mock_subprocess):
        self._run(mock_subprocess, "[]", "[]")
        cmd = mock_subprocess.call_args[0][0]
        assert cmd[:10] == [
            "claude",
            "-p",
            "--model",
            "haiku",
            "--no-session-persistence",
            "--tools",
            "",
            "--disallowedTools",
            "mcp__*",
            "--safe-mode",
        ]
        assert cmd[10:] == ["--output-format", "stream-json", "--verbose"]

    def test_reads_tools_and_servers_from_init(self, mock_subprocess):
        probe = self._run(
            mock_subprocess,
            '["mcp__x__y"]',
            '[{"name":"fake","status":"pending"}]',
        )
        assert probe == ProbeResult(0, ["mcp__x__y"], ["fake"], "", saw_init=True)

    def test_isolated_call(self, mock_subprocess):
        assert self._run(mock_subprocess, "[]", "[]") == ProbeResult(
            0, [], [], "", saw_init=True
        )

    def test_no_init_event_is_not_seen(self, mock_subprocess):
        # An exit 0 with no init event must not read as an isolated call.
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = '{"type":"result","result":"ok"}\n'
        mock_subprocess.return_value.stderr = ""
        assert probe_claude(timeout=5) == ProbeResult(0, [], [], "", saw_init=False)

    def test_refused_call(self, mock_subprocess):
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stdout = ""
        mock_subprocess.return_value.stderr = "error: unknown option '--safe-mode'\n"
        probe = probe_claude(timeout=5)
        assert probe == ProbeResult(1, [], [], "error: unknown option '--safe-mode'")

    def test_missing_cli(self, mock_subprocess):
        mock_subprocess.side_effect = FileNotFoundError()
        assert probe_claude(timeout=5).returncode is None
