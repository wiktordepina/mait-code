"""JSONL transcript parsing and message formatting for extraction."""

import json


def read_new_lines(transcript_path: str, byte_offset: int) -> tuple[list[dict], int]:
    """Read new JSONL lines from byte_offset to EOF.

    Returns (filtered_messages, new_byte_offset).
    Only returns user and assistant messages, skipping tool_result content.
    """
    with open(transcript_path, "rb") as f:
        f.seek(byte_offset)
        raw = f.read()

    # Only parse complete lines
    if not raw.endswith(b"\n") and b"\n" in raw:
        last_newline = raw.rfind(b"\n")
        raw = raw[: last_newline + 1]

    if not raw:
        return [], byte_offset

    new_offset = byte_offset + len(raw)
    messages = []

    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

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

    return messages, new_offset


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

    Truncates from the beginning if over max_chars (keeps most recent).
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
