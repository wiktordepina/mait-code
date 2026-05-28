"""Shared logging configuration for mait-code.

Call ``setup_logging()`` once in each entry point's ``main()`` to configure
file-based logging for the ``mait_code`` namespace. Uses a
``TimedRotatingFileHandler`` to rotate logs daily.

Configuration via environment variables (settable in settings.json env):

* ``MAIT_CODE_LOG_LEVEL`` — DEBUG, INFO, WARNING, ERROR (default: INFO)
* ``MAIT_CODE_LOG_FILE``  — override log file path

Log output goes to file only — never stdout/stderr — so it cannot
interfere with hook JSON output or tool results.
"""

import functools
import logging
import sys
import time
from collections.abc import Callable
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from mait_code.config import data_dir, get as config_get

__all__ = [
    "log_invocation",
    "setup_logging",
]

# Parameters to truncate in invocation logs (prompt/message content)
_SENSITIVE_PARAMS = {"content", "query", "what", "description", "prompt", "message"}

_TRUNCATE_LEN = 80

_setup_done = False


def _get_log_path() -> Path:
    """Return the log file path, creating the directory if needed."""
    value = config_get("log-file")
    if "<" not in value:
        path = Path(value)
    else:
        path = data_dir() / "logs" / "mait-code.log"

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> None:
    """Configure the ``mait_code`` logger hierarchy with a daily-rotating file handler.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    level_name = config_get("log-level").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_path = _get_log_path()

    # Rotate at midnight rather than by size. In short-lived hook/CLI
    # processes the rollover is checked on the first emit using the log file's
    # mtime, so the previous day's file is rolled to mait-code.log.YYYY-MM-DD
    # before the first write of a new day — no long-running process needed.
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )

    # Strip the mait_code. prefix from logger names for readability
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger("mait_code")
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # Prevent propagation to the root logger (which may write to stderr)
    root_logger.propagate = False


def _truncate(value: str) -> str:
    """Truncate a string for logging, appending an ellipsis when shortened."""
    if len(value) <= _TRUNCATE_LEN:
        return value
    return value[:_TRUNCATE_LEN] + "..."


def _format_arg(name: str, value) -> str:
    """Format a single argument for the invocation log line."""
    if name in _SENSITIVE_PARAMS and isinstance(value, (str, list)):
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        return f'{name}="{_truncate(value)}"'
    return f"{name}={value!r}"


def log_invocation(
    *,
    name: str | None = None,
    truncate_params: set[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate CLI tool/hook entry points so invocations are logged.

    Logs the command name and parsed arguments on entry, and status plus
    duration on exit.

    Args:
        name: Override the logged command name (default: the wrapped
            function's name).
        truncate_params: Extra parameter names to truncate beyond the
            built-in sensitive set.

    Returns:
        A decorator that wraps the entry-point function.
    """
    extra_sensitive = truncate_params or set()

    def decorator(func):
        cmd_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            setup_logging()
            logger = logging.getLogger("mait_code.invocation")

            # Build param string from sys.argv (most reliable for CLI tools)
            argv_str = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""

            # Also try to extract argparse Namespace if first arg looks like one
            param_parts = []
            ns = args[0] if args else None
            if ns is not None and hasattr(ns, "__dict__") and not callable(ns):
                merged_sensitive = _SENSITIVE_PARAMS | extra_sensitive
                for k, v in vars(ns).items():
                    if k.startswith("_") or k == "func":
                        continue
                    if k in merged_sensitive and isinstance(v, (str, list)):
                        if isinstance(v, list):
                            v = " ".join(str(x) for x in v)
                        param_parts.append(f'{k}="{_truncate(v)}"')
                    else:
                        param_parts.append(f"{k}={v!r}")

            if param_parts:
                logger.info("invoked: %s %s", cmd_name, " ".join(param_parts))
            else:
                logger.info("invoked: %s %s", cmd_name, argv_str)

            t0 = time.monotonic()
            try:
                result = func(*args, **kwargs)
                elapsed = time.monotonic() - t0
                logger.info("completed: %s (%.2fs)", cmd_name, elapsed)
                return result
            except SystemExit:
                elapsed = time.monotonic() - t0
                logger.info("exited: %s (%.2fs)", cmd_name, elapsed)
                raise
            except Exception:
                elapsed = time.monotonic() - t0
                logger.exception("failed: %s (%.2fs)", cmd_name, elapsed)
                raise

        return wrapper

    return decorator
