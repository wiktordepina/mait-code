"""Shared LLM invocation for mait-code.

Wraps the ``claude`` CLI for subprocess-based LLM calls. Used by both the
observe hook (extraction) and the reflect tool (synthesis).

Every call is text in, text out, so the nested claude runs with no built-in
tools and no MCP servers, from the data directory rather than the caller's
cwd. The prompts embed transcript windows and memories; a transcript that
reads like a task must not be able to get the model to carry it out.
"""

import logging
import os
import subprocess
import time
from pathlib import Path

__all__ = ["call_claude"]

logger = logging.getLogger(__name__)


def call_claude(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str = "haiku",
    timeout: int | None = None,
    retries: int = 0,
    backoff_base: float = 2.0,
) -> str | None:
    """Invoke ``claude -p --model <model>`` with the prompt via stdin.

    Args:
        prompt: The user prompt to send.
        system_prompt: Optional system prompt prepended with a marker.
        model: Model name passed to ``--model`` (default: haiku).
        timeout: Subprocess timeout in seconds. ``None`` (the default) reads
            the ``llm-timeout`` setting.
        retries: Number of retries on transient failure (default: 0).
        backoff_base: Base for exponential backoff in seconds (default: 2.0).

    Returns:
        Stripped stdout on success, or ``None`` on failure.
    """
    if timeout is None:
        from mait_code.config import get_int

        timeout = get_int("llm-timeout")

    full_prompt = prompt
    if system_prompt:
        full_prompt = f"[System instruction]: {system_prompt}\n\n{prompt}"

    cmd = [
        "claude",
        "-p",
        "--model",
        model,
        "--no-session-persistence",
        # No built-in tools ("" disables them all) and, with no --mcp-config
        # alongside, no MCP servers either.
        "--tools",
        "",
        "--strict-mcp-config",
    ]

    # Clear CLAUDECODE env var to allow nested claude invocations from hooks.
    # Set MAIT_CODE_NESTED to prevent hooks from recursing.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["MAIT_CODE_NESTED"] = "1"
    cwd = _neutral_cwd()

    for attempt in range(1 + retries):
        try:
            result = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=cwd,
            )
            if result.returncode != 0:
                logger.warning(
                    "claude exited %d: %s",
                    result.returncode,
                    result.stderr[:200] if result.stderr else "",
                )
                if attempt < retries:
                    delay = backoff_base**attempt
                    logger.info(
                        "retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, retries
                    )
                    time.sleep(delay)
                    continue
                return None
            return result.stdout.strip()
        except FileNotFoundError:
            logger.error("claude CLI not found")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("claude timed out after %ds", timeout)
            if attempt < retries:
                delay = backoff_base**attempt
                logger.info(
                    "retrying in %.1fs (attempt %d/%d)", delay, attempt + 1, retries
                )
                time.sleep(delay)
                continue
            return None

    return None


def _neutral_cwd() -> Path:
    """Return a working directory for the nested claude away from any project.

    The data directory is user-owned and holds no project CLAUDE.md, so the
    call neither loads a repo's instructions nor lands file writes in it. A
    shared temp dir would not do: anyone can plant a ``CLAUDE.md`` there.
    Falls back to ``$HOME`` when the data directory does not exist yet.
    """
    from mait_code.config import data_dir

    path = data_dir()
    return path if path.is_dir() else Path.home()
