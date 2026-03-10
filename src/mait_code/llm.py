"""
Shared LLM invocation for mait-code.

Wraps the `claude` CLI for subprocess-based LLM calls.
Used by both the observe hook (extraction) and the reflect tool (synthesis).
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def call_claude(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str = "haiku",
    timeout: int = 60,
) -> str | None:
    """
    Call `claude -p --model <model>` with prompt via stdin.

    Args:
        prompt: The user prompt to send.
        system_prompt: Optional system prompt (prepended with [S]: prefix).
        model: Model name for --model flag (default: haiku).
        timeout: Subprocess timeout in seconds.

    Returns:
        Stripped stdout on success, None on failure.
    """
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"[System instruction]: {system_prompt}\n\n{prompt}"

    cmd = ["claude", "-p", "--model", model, "--no-session-persistence"]

    try:
        # Clear CLAUDECODE env var to allow nested claude invocations from hooks.
        # Set MAIT_CODE_NESTED to prevent hooks from recursing.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["MAIT_CODE_NESTED"] = "1"
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
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        logger.error("claude CLI not found")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("claude timed out after %ds", timeout)
        return None
