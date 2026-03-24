"""Tests for observe hook CLI — stdin parsing and transcript fallback."""

import io
import json
import time
from pathlib import Path
from unittest.mock import patch

from mait_code.hooks.observe.cli import _find_transcript, _read_event


class TestReadEvent:
    """Tests for _read_event — resilient stdin JSON parsing."""

    def test_valid_json(self):
        event = {"session_id": "abc", "transcript_path": "/tmp/t.jsonl"}
        with patch("sys.stdin", io.StringIO(json.dumps(event))):
            assert _read_event() == event

    def test_empty_stdin(self):
        with patch("sys.stdin", io.StringIO("")):
            assert _read_event() == {}

    def test_whitespace_only_stdin(self):
        with patch("sys.stdin", io.StringIO("  \n  ")):
            assert _read_event() == {}

    def test_invalid_json(self):
        with patch("sys.stdin", io.StringIO("not json{{")):
            assert _read_event() == {}


class TestFindTranscript:
    """Tests for _find_transcript — filesystem fallback."""

    def test_finds_newest_transcript(self, tmp_path: Path):
        slug = str(tmp_path).replace("/", "-")
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)

        old = project_dir / "old-session.jsonl"
        old.write_text('{"type": "user"}\n')

        # Ensure different mtime
        time.sleep(0.05)

        new = project_dir / "new-session.jsonl"
        new.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=str(tmp_path))

        assert result == str(new)

    def test_no_project_dir(self, tmp_path: Path):
        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd="/nonexistent/project")

        assert result is None

    def test_empty_project_dir(self, tmp_path: Path):
        slug = str(tmp_path).replace("/", "-")
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=str(tmp_path))

        assert result is None

    def test_slug_derivation(self, tmp_path: Path):
        """The slug is the cwd with / replaced by -."""
        cwd = "/Users/someone/projects/my-app"
        slug = "-Users-someone-projects-my-app"
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=cwd)

        assert result == str(transcript)

    def test_defaults_to_getcwd(self, tmp_path: Path, monkeypatch: object):
        monkeypatch.chdir(tmp_path)
        slug = str(tmp_path).replace("/", "-")
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript()

        assert result == str(transcript)
