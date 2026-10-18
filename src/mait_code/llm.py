"""Shared LLM invocation for mait-code.

Wraps the ``claude`` CLI for subprocess-based LLM calls. Used by both the
observe hook (extraction) and the reflect tool (synthesis).

Every call is text in, text out, so the nested claude runs with no tools at
all, built-in or MCP, from the data directory rather than the caller's cwd.
The prompts embed transcript windows and memories; a transcript that reads
like a task must not be able to get the model to carry it out.

The nested call also runs in safe mode, so it loads no CLAUDE.md, skills,
plugins, user hooks or MCP servers. Every prompt must therefore carry its
own context.
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    # Invocation
    "call_claude",
    # Diagnostics
    "ProbeResult",
    "probe_claude",
]

logger = logging.getLogger(__name__)

#: Command-line flags every nested call runs with. Measured on Claude Code
#: 2.1.302:
#:
#: - ``--tools ""`` disables every built-in tool, and only those: MCP tools
#:   stay available without the next flag.
#: - ``--disallowedTools "mcp__*"`` removes every MCP tool from the model's
#:   tool list. Under ``allowManagedPermissionRulesOnly`` it holds only from
#:   Claude Code 2.1.257; earlier versions dropped command-line deny rules
#:   at the first settings reload.
#: - ``--safe-mode`` starts no MCP servers at all, policy-configured ones
#:   included, so no server process runs and no server instructions reach
#:   the prompt. ``--strict-mcp-config`` would do the same, but Claude Code
#:   refuses it outright when a managed MCP config is present.
_ISOLATION_FLAGS = (
    "--no-session-persistence",
    "--tools",
    "",
    "--disallowedTools",
    "mcp__*",
    "--safe-mode",
)

#: Stderr fragments that mark Claude Code refusing the command line itself.
#: Such a refusal fails the same way on every attempt, so it is not retried.
_REFUSAL_MARKERS = ("unknown option", "You cannot use")


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
        retries: Number of retries on transient failure (default: 0). A
            refused command line is never retried.
        backoff_base: Base for exponential backoff in seconds (default: 2.0).

    Returns:
        Stripped stdout on success, or ``None`` on failure.
    """
    if timeout is None:
        timeout = _default_timeout()

    full_prompt = prompt
    if system_prompt:
        full_prompt = f"[System instruction]: {system_prompt}\n\n{prompt}"

    cmd = _command(model)
    env = _nested_env()
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
                if _is_refusal(result.stderr):
                    logger.error(
                        "claude refused the command line (exit %d): %s",
                        result.returncode,
                        result.stderr.strip(),
                    )
                    return None
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


@dataclass(frozen=True)
class ProbeResult:
    """What one real nested call saw, read from its stream-json init event.

    Attributes:
        returncode: The nested claude's exit code (``None`` if it never ran).
        tools: Tool names offered to the model.
        mcp_servers: MCP server names the call started, whatever their status.
        stderr: The call's stderr, stripped, or why it could not run.
    """

    returncode: int | None
    tools: list[str]
    mcp_servers: list[str]
    stderr: str


def probe_claude(*, model: str = "haiku", timeout: int | None = None) -> ProbeResult:
    """Make one tiny real nested call and report what it ran with.

    Uses exactly the command line :func:`call_claude` uses, plus
    ``--output-format stream-json --verbose`` for the init event, so a
    diagnostic can confirm the call succeeds and runs with no tools and no
    MCP servers on this host.

    Args:
        model: Model name passed to ``--model`` (default: haiku).
        timeout: Subprocess timeout in seconds. ``None`` (the default) reads
            the ``llm-timeout`` setting.

    Returns:
        The call's :class:`ProbeResult`.
    """
    if timeout is None:
        timeout = _default_timeout()
    cmd = [*_command(model), "--output-format", "stream-json", "--verbose"]
    try:
        result = subprocess.run(
            cmd,
            input="Reply with the single word: ok",
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_nested_env(),
            cwd=_neutral_cwd(),
        )
    except FileNotFoundError:
        return ProbeResult(None, [], [], "claude CLI not found")
    except subprocess.TimeoutExpired:
        return ProbeResult(None, [], [], f"timed out after {timeout}s")

    tools: list[str] = []
    servers: list[str] = []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("subtype") == "init":
            tools = [str(t) for t in event.get("tools") or []]
            servers = [
                str(s.get("name", "?")) if isinstance(s, dict) else str(s)
                for s in event.get("mcp_servers") or []
            ]
            break
    return ProbeResult(result.returncode, tools, servers, result.stderr.strip())


def _command(model: str) -> list[str]:
    return ["claude", "-p", "--model", model, *_ISOLATION_FLAGS]


def _default_timeout() -> int:
    from mait_code.config import get_int

    return get_int("llm-timeout")


def _nested_env() -> dict[str, str]:
    """The caller's environment, made safe for a nested claude.

    Clears CLAUDECODE to allow nested claude invocations from hooks, and
    sets MAIT_CODE_NESTED to prevent hooks from recursing.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["MAIT_CODE_NESTED"] = "1"
    return env


def _is_refusal(stderr: str | None) -> bool:
    return bool(stderr) and any(m in stderr for m in _REFUSAL_MARKERS)


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
