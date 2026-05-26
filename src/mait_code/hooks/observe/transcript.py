"""JSONL transcript parsing and message formatting for extraction."""

import json
from pathlib import Path

from mait_code.context import DEFAULT_BRANCHES


def read_new_lines(
    transcript_path: str, byte_offset: int
) -> tuple[list[dict], int, dict]:
    """Read new JSONL transcript lines from ``byte_offset`` to EOF.

    Only returns user and assistant messages, skipping ``tool_result`` and
    ``tool_use`` blocks.

    Args:
        transcript_path: Filesystem path to the JSONL transcript.
        byte_offset: Last-read offset; reading resumes from here.

    Returns:
        A tuple ``(filtered_messages, new_byte_offset, metadata)``.
        ``metadata`` contains ``project`` and ``branch`` derived from the
        transcript entries' ``cwd`` and ``gitBranch`` fields; the last
        non-empty values encountered are used.
    """
    with open(transcript_path, "rb") as f:
        f.seek(byte_offset)
        raw = f.read()

    # Only parse complete lines
    if not raw.endswith(b"\n") and b"\n" in raw:
        last_newline = raw.rfind(b"\n")
        raw = raw[: last_newline + 1]

    if not raw:
        return [], byte_offset, {}

    new_offset = byte_offset + len(raw)
    messages = []
    last_cwd: str | None = None
    last_branch: str | None = None

    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Capture cwd / gitBranch from any entry that carries them
        if entry.get("cwd"):
            last_cwd = entry["cwd"]
        if entry.get("gitBranch"):
            last_branch = entry["gitBranch"]

        entry_type = entry.get("type")
        if entry_type not in ("user", "assistant"):
            continue

        # Skip tool_result messages
        message = entry.get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            # Filter out tool_result and tool_use blocks
            text_blocks = [
                b
                for b in content
                if isinstance(b, dict)
                and b.get("type") not in ("tool_result", "tool_use")
            ]
            if not text_blocks:
                continue
            entry["_text_blocks"] = text_blocks

        messages.append(entry)

    # Derive project name from cwd (basename of git root / working dir)
    project = Path(last_cwd).name if last_cwd else None
    # Treat default branches as None (project-scoped, not branch-scoped)
    branch = (
        last_branch if last_branch and last_branch not in DEFAULT_BRANCHES else None
    )

    metadata = {"project": project, "branch": branch}
    return messages, new_offset, metadata


def _extract_text(message: dict) -> str:
    """Extract readable text from a message entry."""
    if "_text_blocks" in message:
        parts = []
        for block in message["_text_blocks"]:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts).strip()

    content = message.get("message", {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts).strip()
    return ""


def format_for_extraction(messages: list[dict], max_chars: int = 60_000) -> str:
    """Format filtered messages into readable text for the extraction prompt.

    Args:
        messages: Filtered transcript message dicts.
        max_chars: Maximum length of the returned string. If exceeded, the
            leading portion is dropped so the most recent content is kept.

    Returns:
        A single string with one ``ROLE: text`` line per message.
    """
    lines = []
    for msg in messages:
        role = msg.get("type", "unknown").upper()
        text = _extract_text(msg)
        if text:
            lines.append(f"{role}: {text}")

    result = "\n".join(lines)

    if len(result) > max_chars:
        result = result[-max_chars:]
        # Cut at first newline to avoid partial line
        first_nl = result.find("\n")
        if first_nl != -1:
            result = result[first_nl + 1 :]

    return result
