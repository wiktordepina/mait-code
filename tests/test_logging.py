"""Tests for the shared logging module."""

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import mait_code.logging as log_mod
from mait_code.logging import (
    _format_arg,
    _truncate,
    log_invocation,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Reset module state between tests."""
    log_mod._setup_done = False

    # Remove any handlers added by setup_logging
    logger = logging.getLogger("mait_code")
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate

    yield

    logger.handlers = original_handlers
    logger.level = original_level
    logger.propagate = original_propagate
    log_mod._setup_done = False


def _read_lines(log_file: Path) -> list[dict]:
    """Parse every line of the log file as a JSON object."""
    return [
        json.loads(line) for line in log_file.read_text().splitlines() if line.strip()
    ]


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logger = logging.getLogger("mait_code.test")
        logger.info("test message")

        assert log_file.exists()
        assert any(line["msg"] == "test message" for line in _read_lines(log_file))

    def test_uses_daily_rotating_handler(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        from logging.handlers import TimedRotatingFileHandler

        logger = logging.getLogger("mait_code")
        handlers = [
            h for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(handlers) == 1
        assert handlers[0].when == "MIDNIGHT"
        assert handlers[0].backupCount == 14

    def test_idempotent(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()
            setup_logging()
            setup_logging()

        logger = logging.getLogger("mait_code")
        # Should only have one handler despite three calls
        file_handlers = [h for h in logger.handlers if hasattr(h, "baseFilename")]
        assert len(file_handlers) == 1

    def test_respects_log_level(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(
            os.environ,
            {
                "MAIT_CODE_LOG_FILE": str(log_file),
                "MAIT_CODE_LOG_LEVEL": "WARNING",
            },
        ):
            setup_logging()

        logger = logging.getLogger("mait_code")
        assert logger.level == logging.WARNING

    def test_default_level_is_info(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        env = {"MAIT_CODE_LOG_FILE": str(log_file)}
        # Remove MAIT_CODE_LOG_LEVEL if set
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAIT_CODE_LOG_LEVEL", None)
            setup_logging()

        logger = logging.getLogger("mait_code")
        assert logger.level == logging.INFO

    def test_no_propagation(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logger = logging.getLogger("mait_code")
        assert logger.propagate is False

    def test_default_log_path(self, tmp_path):
        state_dir = tmp_path / "state"
        with patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(state_dir)},
        ):
            os.environ.pop("MAIT_CODE_LOG_FILE", None)
            import mait_code.config as _config

            _config._settings_cache = None
            setup_logging()

        logger = logging.getLogger("mait_code")
        file_handlers = [h for h in logger.handlers if hasattr(h, "baseFilename")]
        expected = state_dir / "mait-code" / "mait-code.jsonl"
        assert Path(file_handlers[0].baseFilename) == expected


class TestJsonSchema:
    def test_core_fields_on_every_line(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logging.getLogger("mait_code.tools.memory").info("test format")

        (line,) = _read_lines(log_file)
        assert isinstance(line["ts"], float)
        assert line["level"] == "info"
        assert line["logger"] == "tools.memory"
        assert line["msg"] == "test format"
        assert line["tool"] == Path(sys.argv[0]).name
        assert line["pid"] == os.getpid()

    def test_level_is_lowercase(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logging.getLogger("mait_code.test").warning("careful")

        (line,) = _read_lines(log_file)
        assert line["level"] == "warning"

    def test_extra_fields_merge_at_top_level(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logging.getLogger("mait_code.test").info(
            "stored", extra={"memory_id": 42, "store": "procedural"}
        )

        (line,) = _read_lines(log_file)
        assert line["memory_id"] == 42
        assert line["store"] == "procedural"

    def test_core_fields_win_collisions(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logging.getLogger("mait_code.test").info(
            "real message", extra={"tool": "imposter", "pid": -1}
        )

        (line,) = _read_lines(log_file)
        assert line["tool"] != "imposter"
        assert line["pid"] == os.getpid()

    def test_non_serialisable_extra_falls_back_to_repr(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logging.getLogger("mait_code.test").info(
            "odd extra", extra={"path": Path("/tmp/x")}
        )

        (line,) = _read_lines(log_file)
        assert "/tmp/x" in line["path"]

    def test_exception_serialises_to_one_line(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logger = logging.getLogger("mait_code.test")
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("it failed")

        (line,) = _read_lines(log_file)
        assert line["error_type"] == "ValueError"
        assert line["error_message"] == "boom"
        assert "Traceback" in line["stack"]
        assert "\n" in line["stack"]  # multiline traceback inside one JSON line


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_string_truncated(self):
        long = "x" * 200
        result = _truncate(long)
        assert len(result) == 83  # 80 + "..."
        assert result.endswith("...")

    def test_exact_length_unchanged(self):
        exact = "x" * 80
        assert _truncate(exact) == exact


class TestFormatArg:
    def test_sensitive_param_truncated(self):
        result = _format_arg("content", "x" * 200)
        assert result.startswith('content="')
        assert result.endswith('..."')

    def test_sensitive_list_joined_and_truncated(self):
        result = _format_arg("query", ["hello", "world"])
        assert result == 'query="hello world"'

    def test_non_sensitive_param_repr(self):
        result = _format_arg("limit", 10)
        assert result == "limit=10"

    def test_non_sensitive_string_not_truncated(self):
        result = _format_arg("mode", "hybrid")
        assert result == "mode='hybrid'"


class TestLogInvocation:
    def test_logs_invocation_and_completion(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd")
            def my_func():
                return 42

            result = my_func()

        assert result == 42
        invoked, completed = _read_lines(log_file)
        assert invoked["msg"] == "invoked: test-cmd"
        assert invoked["event"] == "invoked"
        assert completed["msg"] == "completed: test-cmd"
        assert completed["event"] == "completed"
        assert isinstance(completed["duration_ms"], (int, float))
        assert completed["duration_ms"] >= 0

    def test_logs_argparse_namespace(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd")
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(query=["dark", "mode"], limit=10, type=None)
            my_func(ns)

        invoked = _read_lines(log_file)[0]
        assert 'query="dark mode"' in invoked["args"]
        assert "limit=10" in invoked["args"]

    def test_truncates_sensitive_args(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd")
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(content=["x"] * 100)
            my_func(ns)

        invoked = _read_lines(log_file)[0]
        assert "..." in invoked["args"]

    def test_logs_exception(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd")
            def my_func():
                raise ValueError("boom")

            with pytest.raises(ValueError, match="boom"):
                my_func()

        failed = _read_lines(log_file)[-1]
        assert failed["msg"] == "failed: test-cmd"
        assert failed["event"] == "failed"
        assert failed["error_type"] == "ValueError"
        assert failed["error_message"] == "boom"
        assert "Traceback" in failed["stack"]
        assert failed["duration_ms"] >= 0

    def test_logs_system_exit(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd")
            def my_func():
                sys.exit(1)

            with pytest.raises(SystemExit):
                my_func()

        exited = _read_lines(log_file)[-1]
        assert exited["msg"] == "exited: test-cmd"
        assert exited["event"] == "exited"
        assert exited["duration_ms"] >= 0

    def test_extra_truncate_params(self, tmp_path):
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd", truncate_params={"custom_field"})
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(custom_field="x" * 200)
            my_func(ns)

        invoked = _read_lines(log_file)[0]
        assert "..." in invoked["args"]

    def test_skips_func_attribute(self, tmp_path):
        """The argparse 'func' attribute should not be logged."""
        log_file = tmp_path / "test.jsonl"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):

            @log_invocation(name="test-cmd")
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(func=lambda: None, limit=5)
            my_func(ns)

        invoked = _read_lines(log_file)[0]
        assert "func=" not in invoked["args"]
        assert "limit=5" in invoked["args"]


class TestSetupLoggingAppliesEnv:
    def test_injects_env_table_at_startup(self):
        """setup_logging is the shared startup path — it applies [env]."""
        from mait_code.cli._paths import settings_path

        sp = settings_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text('[env]\nMAIT_TEST_LOGSETUP_VAR = "on"\n', encoding="utf-8")
        os.environ.pop("MAIT_TEST_LOGSETUP_VAR", None)
        try:
            setup_logging()
            assert os.environ["MAIT_TEST_LOGSETUP_VAR"] == "on"
        finally:
            os.environ.pop("MAIT_TEST_LOGSETUP_VAR", None)
