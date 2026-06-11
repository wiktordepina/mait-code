"""Shared logging configuration for mait-code.

Call ``setup_logging()`` once in each entry point's ``main()`` to configure
file-based logging for the ``mait_code`` namespace. Uses a
``TimedRotatingFileHandler`` to rotate logs daily.

Log lines are structured JSON Lines (one JSON object per line) with a
deterministic, ECS-inspired schema. Core fields on every line:

* ``ts`` — epoch seconds as a float (``LogRecord.created``)
* ``level`` — ``debug`` / ``info`` / ``warning`` / ``error`` (lowercase)
* ``logger`` — logger name with the ``mait_code.`` prefix stripped
* ``msg`` — the rendered message
* ``tool`` — entry-point name (e.g. ``mc-tool-board``), captured at
  ``setup_logging()`` from ``sys.argv[0]``
* ``pid`` — process id

Invocation events (from :func:`log_invocation`) add ``event``
(``invoked``/``completed``/``failed``/``exited``), ``duration_ms`` and
``args``. Exceptions add ``error_type``, ``error_message`` and ``stack``.
Call sites may pass ``extra={...}`` to merge additional fields into the
line at top level; core fields win on collision.

Configuration via environment variables (settable in settings.json env):

* ``MAIT_CODE_LOG_LEVEL`` — DEBUG, INFO, WARNING, ERROR (default: INFO)
* ``MAIT_CODE_LOG_FILE``  — override log file path

Log output goes to file only — never stdout/stderr — so it cannot
interfere with hook JSON output or tool results.
"""

import functools
import json
import logging
import sys
import time
from collections.abc import Callable
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from mait_code.cli._paths import mait_code_log_dir
from mait_code.config import apply_env
from mait_code.config import get as config_get
from mait_code.config import get_int as config_get_int

__all__ = [
    "log_file_path",
    "log_invocation",
    "setup_logging",
]

# Parameters to truncate in invocation logs (prompt/message content)
_SENSITIVE_PARAMS = {"content", "query", "what", "description", "prompt", "message"}

_TRUNCATE_LEN = 80

# Attributes present on every vanilla LogRecord — anything else on a record's
# __dict__ arrived via ``extra={...}`` and is merged into the JSON line.
# Built dynamically so new stdlib attributes (e.g. taskName) are covered.
_STANDARD_RECORD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}

# ``args`` is reserved on LogRecord (printf interpolation), so the invocation
# decorator transports the parsed params under this key and the formatter
# publishes it under the schema name ``args``.
_ARGS_TRANSPORT_KEY = "args_"

_setup_done = False

# Entry-point name captured at setup_logging() so every line carries it.
_tool_name = ""


class _JsonLinesFormatter(logging.Formatter):
    """Serialise each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname.lower(),
            "logger": record.name.removeprefix("mait_code."),
            "msg": record.getMessage(),
            "tool": _tool_name,
            "pid": record.process,
        }

        # Extras merge after the core fields, which win on collision.
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key.startswith("_"):
                continue
            key = "args" if key == _ARGS_TRANSPORT_KEY else key
            if key not in line:
                line[key] = value

        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, _ = record.exc_info
            line["error_type"] = exc_type.__name__
            line["error_message"] = str(exc_value)
            line["stack"] = self.formatException(record.exc_info)

        return json.dumps(line, ensure_ascii=False, default=repr)


def log_file_path() -> Path:
    """Return the active log file path, creating its directory if needed.

    The ``log-file`` setting when set to a concrete path, otherwise
    ``<state-dir>/mait-code.jsonl``. The one resolution shared by the writing
    side (:func:`setup_logging`) and the read side (the ``mait-code logs``
    viewer).
    """
    value = config_get("log-file")
    if "<" not in value:
        path = Path(value).expanduser()
    else:
        path = mait_code_log_dir() / "mait-code.jsonl"

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> None:
    """Configure the ``mait_code`` logger hierarchy with a daily-rotating file handler.

    Safe to call multiple times — subsequent calls are no-ops.

    Also injects the settings ``[env]`` table into the process environment
    (:func:`mait_code.config.apply_env`): every tool and hook entry point
    passes through here, making it the shared startup path.
    """
    global _setup_done, _tool_name
    if _setup_done:
        return
    _setup_done = True

    apply_env()

    _tool_name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "python"

    level_name = config_get("log-level").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_path = log_file_path()

    # Rotate at midnight rather than by size. In short-lived hook/CLI
    # processes the rollover is checked on the first emit using the log file's
    # mtime, so the previous day's file is rolled to mait-code.jsonl.YYYY-MM-DD
    # before the first write of a new day — no long-running process needed.
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        backupCount=config_get_int("log-backup-count"),
        encoding="utf-8",
    )
    handler.setFormatter(_JsonLinesFormatter())

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
    """Format a single argument for the invocation ``args`` field."""
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

    Logs the command name and parsed arguments on entry (``event: invoked``,
    ``args``), and status plus duration on exit (``event: completed`` /
    ``failed`` / ``exited``, ``duration_ms``).

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

            params = " ".join(param_parts) if param_parts else argv_str
            logger.info(
                "invoked: %s",
                cmd_name,
                extra={"event": "invoked", _ARGS_TRANSPORT_KEY: params},
            )

            t0 = time.monotonic()
            try:
                result = func(*args, **kwargs)
                logger.info(
                    "completed: %s",
                    cmd_name,
                    extra={"event": "completed", "duration_ms": _elapsed_ms(t0)},
                )
                return result
            except SystemExit:
                logger.info(
                    "exited: %s",
                    cmd_name,
                    extra={"event": "exited", "duration_ms": _elapsed_ms(t0)},
                )
                raise
            except Exception:
                logger.exception(
                    "failed: %s",
                    cmd_name,
                    extra={"event": "failed", "duration_ms": _elapsed_ms(t0)},
                )
                raise

        return wrapper

    return decorator


def _elapsed_ms(t0: float) -> float:
    """Milliseconds elapsed since the monotonic timestamp ``t0``."""
    return round((time.monotonic() - t0) * 1000.0, 3)
