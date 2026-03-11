"""
Shared LLM invocation for mait-code.

Wraps the `claude` CLI for subprocess-based LLM calls.
Used by both the observe hook (extraction) and the reflect tool (synthesis).
"""

import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)


def call_claude(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str = "haiku",
    timeout: int = 60,
    retries: int = 0,
    backoff_base: float = 2.0,
) -> str | None:
    """
    Call `claude -p --model <model>` with prompt via stdin.

    Args:
        prompt: The user prompt to send.
        system_prompt: Optional system prompt (prepended with [S]: prefix).
        model: Model name for --model flag (default: haiku).
        timeout: Subprocess timeout in seconds.
        retries: Number of retries on transient failure (default: 0).
        backoff_base: Base for exponential backoff in seconds (default: 2.0).

    Returns:
        Stripped stdout on success, None on failure.
    """
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"[System instruction]: {system_prompt}\n\n{prompt}"

    cmd = ["claude", "-p", "--model", model, "--no-session-persistence"]

    # Clear CLAUDECODE env var to allow nested claude invocations from hooks.
    # Set MAIT_CODE_NESTED to prevent hooks from recursing.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["MAIT_CODE_NESTED"] = "1"

    for attempt in range(1 + retries):
        try:
            result = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
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
