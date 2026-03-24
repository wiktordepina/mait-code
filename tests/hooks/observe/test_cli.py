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
        slug = str(tmp_path).replace("/", "-").replace(".", "-")
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

    def test_no_projects_root(self, tmp_path: Path):
        """No ~/.claude/projects/ directory at all."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd="/nonexistent/project")

        assert result is None

    def test_no_matching_slug_no_transcripts(self, tmp_path: Path):
        """Slug doesn't match and no transcripts anywhere."""
        projects_root = tmp_path / ".claude" / "projects"
        projects_root.mkdir(parents=True)

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd="/nonexistent/project")

        assert result is None

    def test_empty_project_dir(self, tmp_path: Path):
        slug = str(tmp_path).replace("/", "-").replace(".", "-")
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=str(tmp_path))

        assert result is None

    def test_slug_derivation(self, tmp_path: Path):
        """The slug is the cwd with / and . replaced by -."""
        cwd = "/Users/someone/projects/my-app"
        slug = "-Users-someone-projects-my-app"
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=cwd)

        assert result == str(transcript)

    def test_slug_replaces_dots(self, tmp_path: Path):
        """Dots in the cwd are replaced with dashes in the slug."""
        cwd = "/Users/wiktor.depina/projects/mait-code"
        slug = "-Users-wiktor-depina-projects-mait-code"
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=cwd)

        assert result == str(transcript)

    def test_broad_scan_when_slug_misses(self, tmp_path: Path):
        """When cwd slug doesn't match, falls back to scanning all projects."""
        projects_root = tmp_path / ".claude" / "projects"
        # Create a project dir that does NOT match the cwd slug
        other_project = projects_root / "-Users-someone-projects-real-app"
        other_project.mkdir(parents=True)
        transcript = other_project / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd="/wrong/cwd")

        assert result == str(transcript)

    def test_broad_scan_picks_newest(self, tmp_path: Path):
        """Broad scan returns the most recently modified transcript."""
        projects_root = tmp_path / ".claude" / "projects"

        proj_a = projects_root / "-project-a"
        proj_a.mkdir(parents=True)
        old = proj_a / "old.jsonl"
        old.write_text('{"type": "user"}\n')

        time.sleep(0.05)

        proj_b = projects_root / "-project-b"
        proj_b.mkdir(parents=True)
        new = proj_b / "new.jsonl"
        new.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd="/wrong/cwd")

        assert result == str(new)

    def test_defaults_to_getcwd(self, tmp_path: Path, monkeypatch: object):
        monkeypatch.chdir(tmp_path)
        slug = str(tmp_path).replace("/", "-").replace(".", "-")
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript()

        assert result == str(transcript)
