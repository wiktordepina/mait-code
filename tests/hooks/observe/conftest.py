"""Shared fixtures for observation hook tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch):
    """Set MAIT_CODE_DATA_DIR to a temp directory."""
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
    (tmp_path / "memory" / "observations").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def sample_transcript(tmp_path: Path) -> Path:
    """Create a sample JSONL transcript file."""
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "timestamp": "2026-03-07T10:00:00Z",
            "sessionId": "sess-1",
            "message": {
                "role": "user",
                "content": "Can you add a dark mode toggle to the settings page?",
            },
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "timestamp": "2026-03-07T10:00:05Z",
            "sessionId": "sess-1",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "I'll add a dark mode toggle to the settings page using the existing theme context.",
                    }
                ],
            },
        },
        {
            "type": "system",
            "uuid": "s1",
            "timestamp": "2026-03-07T10:00:06Z",
            "sessionId": "sess-1",
            "content": "Running Edit tool...",
            "level": "info",
        },
        {
            "type": "user",
            "uuid": "u2",
            "timestamp": "2026-03-07T10:00:10Z",
            "sessionId": "sess-1",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_01",
                        "content": "File edited successfully",
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "uuid": "a2",
            "timestamp": "2026-03-07T10:00:15Z",
            "sessionId": "sess-1",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Done! The dark mode toggle is now on the settings page. It uses localStorage to persist the preference.",
                    }
                ],
            },
        },
        {
            "type": "user",
            "uuid": "u3",
            "timestamp": "2026-03-07T10:01:00Z",
            "sessionId": "sess-1",
            "message": {
                "role": "user",
                "content": "Great, we also use PostgreSQL for the backend database.",
            },
        },
    ]

    path = tmp_path / "transcript.jsonl"
    with open(path, "w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")
    return path
