"""Tests for transcript parsing and formatting."""

import json
from pathlib import Path

from mait_code.hooks.observe.transcript import (
    format_for_extraction,
    read_new_lines,
)


def test_read_new_lines_from_start(sample_transcript: Path):
    messages, offset, metadata = read_new_lines(str(sample_transcript), 0)
    # Should get user+assistant messages, minus system and tool_result-only
    # Line 0: user (text) -> kept
    # Line 1: assistant (text blocks) -> kept
    # Line 2: system -> filtered
    # Line 3: user (tool_result only) -> filtered
    # Line 4: assistant (text blocks) -> kept
    # Line 5: user (text) -> kept
    assert len(messages) == 4
    assert offset > 0
    assert metadata["project"] == "my-app"
    assert metadata["branch"] == "feature/dark-mode"


def test_read_new_lines_incremental(sample_transcript: Path):
    msgs1, offset1, _ = read_new_lines(str(sample_transcript), 0)
    assert len(msgs1) == 4

    # Append a new line
    with open(sample_transcript, "a") as f:
        entry = {
            "type": "user",
            "uuid": "u4",
            "sessionId": "sess-1",
            "cwd": "/Users/someone/projects/my-app",
            "gitBranch": "feature/dark-mode",
            "message": {"role": "user", "content": "Thanks!"},
        }
        f.write(json.dumps(entry) + "\n")

    msgs2, offset2, _ = read_new_lines(str(sample_transcript), offset1)
    assert len(msgs2) == 1
    assert offset2 > offset1


def test_read_new_lines_no_new_content(sample_transcript: Path):
    _, offset, _ = read_new_lines(str(sample_transcript), 0)
    msgs, new_offset, metadata = read_new_lines(str(sample_transcript), offset)
    assert msgs == []
    assert new_offset == offset
    assert metadata == {}


def test_filters_system_and_progress(tmp_path: Path):
    path = tmp_path / "test.jsonl"
    lines = [
        {"type": "system", "content": "info"},
        {"type": "progress", "content": "running"},
        {"type": "user", "message": {"role": "user", "content": "hello"}},
    ]
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    messages, _, metadata = read_new_lines(str(path), 0)
    assert len(messages) == 1
    assert messages[0]["type"] == "user"
    # No cwd/gitBranch in these entries
    assert metadata["project"] is None
    assert metadata["branch"] is None


def test_metadata_from_cwd_and_branch(tmp_path: Path):
    """Extracts project and branch from transcript cwd/gitBranch fields."""
    path = tmp_path / "test.jsonl"
    lines = [
        {
            "type": "user",
            "cwd": "/Users/wiktor.depina/projects/mait-code",
            "gitBranch": "feature/memory",
            "message": {"role": "user", "content": "hello"},
        },
    ]
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    _, _, metadata = read_new_lines(str(path), 0)
    assert metadata["project"] == "mait-code"
    assert metadata["branch"] == "feature/memory"


def test_metadata_default_branch_becomes_none(tmp_path: Path):
    """Default branches (main/master) are normalised to None."""
    path = tmp_path / "test.jsonl"
    lines = [
        {
            "type": "user",
            "cwd": "/Users/someone/projects/app",
            "gitBranch": "main",
            "message": {"role": "user", "content": "hello"},
        },
    ]
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    _, _, metadata = read_new_lines(str(path), 0)
    assert metadata["project"] == "app"
    assert metadata["branch"] is None


def test_metadata_uses_last_entry(tmp_path: Path):
    """When entries span branches, the last value wins."""
    path = tmp_path / "test.jsonl"
    lines = [
        {
            "type": "user",
            "cwd": "/home/dev/projects/alpha",
            "gitBranch": "old-branch",
            "message": {"role": "user", "content": "first"},
        },
        {
            "type": "user",
            "cwd": "/home/dev/projects/beta",
            "gitBranch": "new-branch",
            "message": {"role": "user", "content": "second"},
        },
    ]
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    _, _, metadata = read_new_lines(str(path), 0)
    assert metadata["project"] == "beta"
    assert metadata["branch"] == "new-branch"


def test_format_for_extraction_basic(sample_transcript: Path):
    messages, _, _ = read_new_lines(str(sample_transcript), 0)
    text = format_for_extraction(messages)
    assert "USER:" in text
    assert "ASSISTANT:" in text
    assert "dark mode" in text


def test_format_for_extraction_truncation():
    messages = [
        {
            "type": "user",
            "message": {"role": "user", "content": "x" * 100},
        }
        for _ in range(10)
    ]
    text = format_for_extraction(messages, max_chars=500)
    assert len(text) <= 500


def test_handles_string_content():
    messages = [
        {"type": "user", "message": {"role": "user", "content": "simple string"}},
    ]
    text = format_for_extraction(messages)
    assert "simple string" in text


def test_handles_content_blocks():
    messages = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "block text"}],
            },
        },
    ]
    text = format_for_extraction(messages)
    assert "block text" in text
