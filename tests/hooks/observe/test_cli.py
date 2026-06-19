"""Tests for observe hook CLI — stdin parsing and transcript fallback."""

import io
import json
import logging
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mait_code.context import munge_path
from mait_code.hooks.observe import cli as observe_cli
from mait_code.hooks.observe.cli import _find_transcript, _read_event
from mait_code.hooks.observe.cursor import get_cursor


@pytest.fixture
def propagate_logs(monkeypatch):
    """Re-enable propagation so ``caplog`` can capture ``mait_code.*`` records.

    ``setup_logging()`` (run by an earlier test) sets ``propagate=False`` on the
    ``mait_code`` logger; caplog captures at the root, so restore propagation.
    """
    monkeypatch.setattr(logging.getLogger("mait_code"), "propagate", True)


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
        slug = munge_path(str(tmp_path))
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
        slug = munge_path(str(tmp_path))
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd=str(tmp_path))

        assert result is None

    def test_slug_derivation(self, tmp_path: Path):
        """The slug is the cwd with every non-alphanumeric char replaced by -."""
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

    def test_slug_replaces_other_non_alphanumerics(self, tmp_path: Path):
        """Underscores, spaces and other punctuation collapse to dashes too —
        matching Claude Code's replace(/[^a-zA-Z0-9]/g, "-")."""
        cwd = "/Users/someone/my_proj v2"
        slug = "-Users-someone-my-proj-v2"
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

    def test_broad_scan_skips_non_directories(self, tmp_path: Path):
        """Stray files under projects/ are ignored, not treated as project dirs."""
        projects_root = tmp_path / ".claude" / "projects"
        projects_root.mkdir(parents=True)
        # A loose file sitting alongside project dirs must be skipped.
        (projects_root / "stray.txt").write_text("not a project dir")

        proj = projects_root / "-project-a"
        proj.mkdir()
        transcript = proj / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript(cwd="/wrong/cwd")

        assert result == str(transcript)

    def test_defaults_to_getcwd(self, tmp_path: Path, monkeypatch: object):
        monkeypatch.chdir(tmp_path)
        slug = munge_path(str(tmp_path))
        project_dir = tmp_path / ".claude" / "projects" / slug
        project_dir.mkdir(parents=True)
        transcript = project_dir / "session.jsonl"
        transcript.write_text('{"type": "user"}\n')

        with patch.object(Path, "home", return_value=tmp_path):
            result = _find_transcript()

        assert result == str(transcript)


class TestRunCursorAdvance:
    """_run advances the cursor only when a window is handled, never on failure."""

    NEW_OFFSET = 100

    def _run_once(self, data_dir: Path, monkeypatch, extraction):
        """Drive _run once with a mocked transcript read and extraction result.

        The transcript file is created on disk so ``_run``'s existence guard
        passes — ``read_new_lines`` is mocked, so its contents are irrelevant.
        Cursor functions are left real (backed by the temp data dir) so the
        persisted offset reflects the actual decision.
        """
        tpath = data_dir / "transcript.jsonl"
        tpath.touch()
        self.tpath = str(tpath)
        monkeypatch.setattr(
            sys, "argv", ["mc-hook-observe", "--trigger", "session-end"]
        )
        with (
            patch.object(
                observe_cli,
                "_read_event",
                return_value={"transcript_path": self.tpath},
            ),
            patch.object(
                observe_cli,
                "read_new_lines",
                return_value=(
                    ["m"],
                    self.NEW_OFFSET,
                    {"project": None, "branch": None},
                ),
            ),
            patch.object(
                observe_cli, "format_for_extraction", return_value="conversation text"
            ),
            patch.object(observe_cli, "extract_observations", return_value=extraction),
            patch.object(observe_cli, "write_raw_extraction") as mock_raw,
            patch.object(observe_cli, "store_extraction") as mock_store,
            patch.object(observe_cli, "store_entities_and_relationships") as mock_ent,
        ):
            observe_cli._run()
        return mock_raw, mock_store, mock_ent

    def test_transport_failure_does_not_advance(self, data_dir: Path, monkeypatch):
        self._run_once(data_dir, monkeypatch, None)
        # Cursor stays put so the next session re-attempts the same window.
        assert get_cursor(self.tpath) == 0

    def test_advances_after_max_failures(self, data_dir: Path, monkeypatch):
        for _ in range(observe_cli.MAX_EXTRACTION_FAILURES):
            self._run_once(data_dir, monkeypatch, None)
        # The poison window is finally skipped rather than stalling forever.
        assert get_cursor(self.tpath) == self.NEW_OFFSET

    def test_empty_result_advances_without_storing(self, data_dir: Path, monkeypatch):
        mock_raw, mock_store, mock_ent = self._run_once(data_dir, monkeypatch, {})
        assert get_cursor(self.tpath) == self.NEW_OFFSET
        mock_raw.assert_not_called()
        mock_store.assert_not_called()
        mock_ent.assert_not_called()

    def test_populated_result_advances_and_stores(self, data_dir: Path, monkeypatch):
        extraction = {"facts": [{"content": "x", "importance": 5}]}
        mock_raw, mock_store, mock_ent = self._run_once(
            data_dir, monkeypatch, extraction
        )
        assert get_cursor(self.tpath) == self.NEW_OFFSET
        mock_raw.assert_called_once()
        mock_store.assert_called_once()
        mock_ent.assert_called_once()


class TestMain:
    """Tests for main() — the hook entry point wrapper."""

    def test_nested_invocation_is_skipped(self, monkeypatch):
        """A nested claude invocation short-circuits before running anything."""
        monkeypatch.setenv("MAIT_CODE_NESTED", "1")
        with (
            patch.object(observe_cli, "setup_logging"),
            patch("mait_code.ssl.setup_ssl"),
            patch.object(observe_cli, "_run") as mock_run,
        ):
            observe_cli.main()
        mock_run.assert_not_called()

    def test_runs_when_not_nested(self, monkeypatch):
        monkeypatch.delenv("MAIT_CODE_NESTED", raising=False)
        with (
            patch.object(observe_cli, "setup_logging"),
            patch("mait_code.ssl.setup_ssl"),
            patch.object(observe_cli, "_run") as mock_run,
        ):
            observe_cli.main()
        mock_run.assert_called_once()

    def test_broken_pipe_exits_zero(self, monkeypatch):
        """A BrokenPipeError must exit cleanly (0), never fail the hook."""
        monkeypatch.delenv("MAIT_CODE_NESTED", raising=False)
        with (
            patch.object(observe_cli, "setup_logging"),
            patch("mait_code.ssl.setup_ssl"),
            patch.object(observe_cli, "_run", side_effect=BrokenPipeError),
            pytest.raises(SystemExit) as exc,
        ):
            observe_cli.main()
        assert exc.value.code == 0

    def test_unexpected_error_is_swallowed(self, monkeypatch, caplog, propagate_logs):
        """Any other exception is logged and the hook exits 0 — never fails."""
        monkeypatch.delenv("MAIT_CODE_NESTED", raising=False)
        # The @log_invocation decorator also calls setup_logging() (which would
        # flip propagate back to False and defeat caplog); patch it at the
        # module the decorator imported it from, not just on the cli module.
        with (
            patch("mait_code.logging.setup_logging"),
            patch.object(observe_cli, "setup_logging"),
            patch("mait_code.ssl.setup_ssl"),
            patch.object(observe_cli, "_run", side_effect=RuntimeError("boom")),
            caplog.at_level("ERROR", logger="mait_code.hooks.observe.cli"),
            pytest.raises(SystemExit) as exc,
        ):
            observe_cli.main()
        assert exc.value.code == 0
        assert "boom" in caplog.text


class TestRunNoTranscript:
    """_run handles a missing transcript_path by falling back, then bailing."""

    def test_falls_back_to_find_transcript(self, data_dir: Path, monkeypatch):
        """When the event lacks transcript_path, _find_transcript is consulted."""
        tpath = data_dir / "found.jsonl"
        tpath.touch()
        monkeypatch.setattr(sys, "argv", ["mc-hook-observe", "--trigger", "precompact"])
        with (
            patch.object(observe_cli, "_read_event", return_value={"cwd": "/some/dir"}),
            patch.object(
                observe_cli, "_find_transcript", return_value=str(tpath)
            ) as mock_find,
            patch.object(
                observe_cli,
                "read_new_lines",
                return_value=([], 0, {}),
            ),
        ):
            observe_cli._run()
        # cwd from the event is threaded through to the fallback.
        mock_find.assert_called_once_with(cwd="/some/dir")

    def test_no_transcript_anywhere_warns_and_returns(
        self, data_dir: Path, monkeypatch, caplog, propagate_logs
    ):
        """Neither stdin nor fallback yields a path — warn and return."""
        monkeypatch.setattr(
            sys, "argv", ["mc-hook-observe", "--trigger", "session-end"]
        )
        with (
            patch.object(observe_cli, "_read_event", return_value={}),
            patch.object(observe_cli, "_find_transcript", return_value=None),
            patch.object(observe_cli, "read_new_lines") as mock_read,
            caplog.at_level("WARNING", logger="mait_code.hooks.observe.cli"),
        ):
            observe_cli._run()
        mock_read.assert_not_called()
        assert "no transcript_path available" in caplog.text


class TestRunNoContent:
    """_run advances the cursor cleanly when there's nothing to extract."""

    NEW_OFFSET = 42

    def _drive(self, data_dir: Path, monkeypatch, *, messages, conversation_text):
        tpath = data_dir / "transcript.jsonl"
        tpath.touch()
        self.tpath = str(tpath)
        monkeypatch.setattr(
            sys, "argv", ["mc-hook-observe", "--trigger", "session-end"]
        )
        with (
            patch.object(
                observe_cli,
                "_read_event",
                return_value={"transcript_path": self.tpath},
            ),
            patch.object(
                observe_cli,
                "read_new_lines",
                return_value=(messages, self.NEW_OFFSET, {}),
            ),
            patch.object(
                observe_cli, "format_for_extraction", return_value=conversation_text
            ),
            patch.object(observe_cli, "extract_observations") as mock_extract,
        ):
            observe_cli._run()
        return mock_extract

    def test_no_messages_advances_without_extracting(self, data_dir: Path, monkeypatch):
        """An empty window advances the cursor and never calls the extractor."""
        mock_extract = self._drive(
            data_dir, monkeypatch, messages=[], conversation_text=""
        )
        assert get_cursor(self.tpath) == self.NEW_OFFSET
        mock_extract.assert_not_called()

    def test_blank_conversation_text_advances_without_extracting(
        self, data_dir: Path, monkeypatch
    ):
        """Messages that format to whitespace-only text are skipped, cursor advances."""
        mock_extract = self._drive(
            data_dir, monkeypatch, messages=["m"], conversation_text="   \n  "
        )
        assert get_cursor(self.tpath) == self.NEW_OFFSET
        mock_extract.assert_not_called()


class TestRunMissingTranscript:
    """A transcript path that doesn't exist on disk is skipped cleanly.

    The stdin event can name a transcript that was never written or already
    cleaned up (a brand-new or ended session). That's expected and
    non-actionable — _run logs a WARNING and returns without touching the
    cursor or the extraction pipeline, rather than letting open() raise and
    surface as a generic ERROR.
    """

    def test_missing_transcript_skips_without_error(
        self, data_dir: Path, monkeypatch, caplog, propagate_logs
    ):
        missing = str(data_dir / "gone.jsonl")  # never created
        monkeypatch.setattr(
            sys, "argv", ["mc-hook-observe", "--trigger", "session-end"]
        )
        with (
            patch.object(
                observe_cli, "_read_event", return_value={"transcript_path": missing}
            ),
            patch.object(observe_cli, "read_new_lines") as mock_read,
            patch.object(observe_cli, "set_cursor") as mock_set_cursor,
            caplog.at_level("WARNING", logger="mait_code.hooks.observe.cli"),
        ):
            observe_cli._run()

        # Never opened the transcript, never advanced the cursor, warned (not errored).
        mock_read.assert_not_called()
        mock_set_cursor.assert_not_called()
        assert any(r.levelname == "WARNING" for r in caplog.records)
        assert not any(r.levelname == "ERROR" for r in caplog.records)
        assert "transcript not found" in caplog.text
