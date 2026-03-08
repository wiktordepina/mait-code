"""
Shared logging configuration for mait-code.

Call setup_logging() once in each entry point's main() to configure
file-based logging for the mait_code namespace. Uses RotatingFileHandler
to keep logs bounded.

Configuration via environment variables (settable in settings.json env):
    MAIT_CODE_LOG_LEVEL  — DEBUG, INFO, WARNING, ERROR (default: INFO)
    MAIT_CODE_LOG_FILE   — override log file path

Log output goes to file only — never stdout/stderr — so it cannot
interfere with hook JSON output or tool results.
"""

import functools
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Parameters to truncate in invocation logs (prompt/message content)
_SENSITIVE_PARAMS = {"content", "query", "what", "description", "prompt", "message"}

_TRUNCATE_LEN = 80

_setup_done = False


def _get_log_path() -> Path:
    """Return the log file path, creating the directory if needed."""
    override = os.environ.get("MAIT_CODE_LOG_FILE")
    if override:
        path = Path(override)
    else:
        data_dir = Path(
            os.environ.get(
                "MAIT_CODE_DATA_DIR", Path.home() / ".claude" / "mait-code-data"
            )
        )
        path = data_dir / "logs" / "mait-code.log"

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> None:
    """
    Configure the mait_code logger hierarchy with a rotating file handler.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    level_name = os.environ.get("MAIT_CODE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_path = _get_log_path()

    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
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
    """Truncate a string for logging, adding ellipsis."""
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
):
    """
    Decorator that logs CLI tool/hook invocations.

    Logs the command name and all parsed arguments on entry,
    and status + duration on exit.

    Args:
        name: Override the logged command name (default: function name).
        truncate_params: Extra parameter names to truncate beyond the
                         built-in sensitive set.
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
