"""Tests for the shared logging module."""

import logging
import os
import sys
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


class TestSetupLogging:
    def test_creates_log_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logger = logging.getLogger("mait_code.test")
        logger.info("test message")

        assert log_file.exists()
        content = log_file.read_text()
        assert "test message" in content

    def test_idempotent(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()
            setup_logging()
            setup_logging()

        logger = logging.getLogger("mait_code")
        # Should only have one handler despite three calls
        file_handlers = [
            h for h in logger.handlers
            if hasattr(h, "baseFilename")
        ]
        assert len(file_handlers) == 1

    def test_respects_log_level(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {
            "MAIT_CODE_LOG_FILE": str(log_file),
            "MAIT_CODE_LOG_LEVEL": "WARNING",
        }):
            setup_logging()

        logger = logging.getLogger("mait_code")
        assert logger.level == logging.WARNING

    def test_default_level_is_info(self, tmp_path):
        log_file = tmp_path / "test.log"
        env = {"MAIT_CODE_LOG_FILE": str(log_file)}
        # Remove MAIT_CODE_LOG_LEVEL if set
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MAIT_CODE_LOG_LEVEL", None)
            setup_logging()

        logger = logging.getLogger("mait_code")
        assert logger.level == logging.INFO

    def test_no_propagation(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logger = logging.getLogger("mait_code")
        assert logger.propagate is False

    def test_default_log_path(self, tmp_path):
        data_dir = tmp_path / "mait-data"
        with patch.dict(os.environ, {"MAIT_CODE_DATA_DIR": str(data_dir)}):
            # Remove override so default path is used
            os.environ.pop("MAIT_CODE_LOG_FILE", None)
            setup_logging()

        expected = data_dir / "logs" / "mait-code.log"
        assert expected.parent.exists()

    def test_log_format(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            setup_logging()

        logger = logging.getLogger("mait_code.tools.memory")
        logger.info("test format")

        content = log_file.read_text()
        assert "INFO" in content
        assert "mait_code.tools.memory" in content
        assert "test format" in content


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
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd")
            def my_func():
                return 42

            result = my_func()

        assert result == 42
        content = log_file.read_text()
        assert "invoked: test-cmd" in content
        assert "completed: test-cmd" in content

    def test_logs_argparse_namespace(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd")
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(query=["dark", "mode"], limit=10, type=None)
            my_func(ns)

        content = log_file.read_text()
        assert 'query="dark mode"' in content
        assert "limit=10" in content

    def test_truncates_sensitive_args(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd")
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(content=["x"] * 100)
            my_func(ns)

        content = log_file.read_text()
        assert "..." in content

    def test_logs_exception(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd")
            def my_func():
                raise ValueError("boom")

            with pytest.raises(ValueError, match="boom"):
                my_func()

        content = log_file.read_text()
        assert "failed: test-cmd" in content
        assert "boom" in content

    def test_logs_system_exit(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd")
            def my_func():
                sys.exit(1)

            with pytest.raises(SystemExit):
                my_func()

        content = log_file.read_text()
        assert "exited: test-cmd" in content

    def test_extra_truncate_params(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd", truncate_params={"custom_field"})
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(custom_field="x" * 200)
            my_func(ns)

        content = log_file.read_text()
        assert "..." in content

    def test_skips_func_attribute(self, tmp_path):
        """The argparse 'func' attribute should not be logged."""
        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"MAIT_CODE_LOG_FILE": str(log_file)}):
            @log_invocation(name="test-cmd")
            def my_func(args):
                pass

            from argparse import Namespace

            ns = Namespace(func=lambda: None, limit=5)
            my_func(ns)

        content = log_file.read_text()
        assert "func=" not in content
        assert "limit=5" in content
