"""Tests for ``mc-tool-memory observe`` — extraction from prepared text.

These drive ``main()`` end to end against a temp data directory: only the
LLM call and the ``claude`` PATH lookup are patched.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mait_code.tools.memory import cli as memory_cli
from mait_code.tools.memory.db import connection

EXTRACT = "mait_code.hooks.observe.extractor.extract_observations"

FULL_EXTRACTION = {
    "facts": [{"content": "The runner builds a digest per job", "scope": "global"}],
    "preferences": [{"content": "Prefers terse commit messages", "scope": "global"}],
    "decisions": [{"content": "Jobs extract once from a digest", "scope": "branch"}],
    "entities": [{"name": "maitre-d", "entity_type": "service"}],
    "relationships": [],
}


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(data))
    return data


@pytest.fixture
def digest(tmp_path: Path) -> Path:
    path = tmp_path / "digest.txt"
    path.write_text("Card #3: write the research doc. Outcome: PR opened.\n")
    return path


def _run(monkeypatch, *argv: str, extraction=None, claude: str | None = "/bin/claude"):
    """Run ``mc-tool-memory observe <argv>``; return (exit status, extract mock)."""
    monkeypatch.setattr(sys, "argv", ["mc-tool-memory", "observe", *argv])
    with (
        patch(EXTRACT, return_value=extraction) as mock_extract,
        patch.object(memory_cli.shutil, "which", return_value=claude),
        pytest.raises(SystemExit) as exc,
    ):
        memory_cli.main()
    return exc.value.code, mock_extract


def _rows() -> list[tuple]:
    with connection() as conn:
        return conn.execute(
            "SELECT content, entry_type, scope, project, branch, source "
            "FROM memory_entries ORDER BY id"
        ).fetchall()


def _raw_records(data: Path) -> list[dict]:
    records = []
    for path in (data / "memory" / "observations").glob("*.jsonl"):
        records += [json.loads(line) for line in path.read_text().splitlines()]
    return records


def test_extracts_and_stores_with_caps(data_dir, digest, monkeypatch, capsys):
    status, mock_extract = _run(
        monkeypatch,
        "--file", str(digest), "--project", "maitre-d", "--branch", "feat/x",
        extraction=FULL_EXTRACTION,
    )  # fmt: skip

    assert status == memory_cli.OBSERVE_EXTRACTED
    assert mock_extract.call_args.kwargs == {"project": "maitre-d", "branch": "feat/x"}
    rows = _rows()
    # No preferences; the global fact is pinned to project; branch stays branch.
    assert rows == [
        ("The runner builds a digest per job", "fact", "project", "maitre-d", None, "job"),
        ("Jobs extract once from a digest", "decision", "branch", "maitre-d", "feat/x", "job"),
    ]  # fmt: skip
    assert "Stored 2 new and 0 existing memories." in capsys.readouterr().out


def test_raw_log_records_trigger_source_and_confined_extraction(
    data_dir, digest, monkeypatch
):
    _run(
        monkeypatch,
        "--file", str(digest), "--project", "maitre-d", "--trigger", "nightly-job",
        extraction=FULL_EXTRACTION,
    )  # fmt: skip

    (record,) = _raw_records(data_dir)
    assert record["trigger"] == "nightly-job"
    assert record["source"] == "nightly-job"
    # Logged after confinement, so `restore` replays the same caps.
    assert "preferences" not in record["extraction"]
    assert {i["scope"] for i in record["extraction"]["facts"]} == {"project"}


def test_json_reports_outcome_and_counts(data_dir, digest, monkeypatch, capsys):
    status, _ = _run(
        monkeypatch,
        "--file", str(digest), "--project", "maitre-d", "--json",
        extraction=FULL_EXTRACTION,
    )  # fmt: skip

    assert status == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["outcome"] == "extracted"
    assert doc["counts"]["facts"] == {"created": 1, "deduplicated": 0, "failed": 0}
    assert doc["counts"]["preferences"] == {
        "created": 0,
        "deduplicated": 0,
        "failed": 0,
    }


def test_rerun_counts_deduplicated(data_dir, digest, monkeypatch, capsys):
    args = ("--file", str(digest), "--project", "maitre-d", "--json")
    _run(monkeypatch, *args, extraction=FULL_EXTRACTION)
    capsys.readouterr()

    status, _ = _run(monkeypatch, *args, extraction=FULL_EXTRACTION)

    assert status == memory_cli.OBSERVE_EXTRACTED
    counts = json.loads(capsys.readouterr().out)["counts"]
    assert counts["facts"] == {"created": 0, "deduplicated": 1, "failed": 0}
    assert len(_rows()) == 2


def test_default_branch_is_normalised(data_dir, digest, monkeypatch):
    _run(
        monkeypatch,
        "--file", str(digest), "--project", "maitre-d", "--branch", "main",
        extraction={"facts": [{"content": "A fact", "scope": "branch"}]},
    )  # fmt: skip

    # `main` counts as no branch, so a branch-scoped ask has no branch to carry.
    (row,) = _rows()
    assert row[4] is None


def test_project_is_canonicalised(data_dir, digest, monkeypatch):
    with patch(
        "mait_code.context.load_project_aliases", return_value={"old-name": "maitre-d"}
    ):
        status, mock_extract = _run(
            monkeypatch,
            "--file", str(digest), "--project", "old-name",
            extraction={"facts": [{"content": "A fact"}]},
        )  # fmt: skip

    assert status == 0
    assert mock_extract.call_args.kwargs["project"] == "maitre-d"
    (record,) = _raw_records(data_dir)
    assert record["project"] == "maitre-d"


def test_reads_stdin(data_dir, monkeypatch):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("digest via stdin"))
    status, mock_extract = _run(
        monkeypatch,
        "--file", "-", "--project", "maitre-d",
        extraction={"facts": [{"content": "A fact"}]},
    )  # fmt: skip

    assert status == 0
    assert mock_extract.call_args.args == ("digest via stdin",)


def test_runs_with_nested_flag_set(data_dir, digest, monkeypatch):
    """The runner calls it from a job, where MAIT_CODE_NESTED=1 is set."""
    monkeypatch.setenv("MAIT_CODE_NESTED", "1")
    status, mock_extract = _run(
        monkeypatch,
        "--file", str(digest), "--project", "maitre-d",
        extraction={"facts": [{"content": "A fact"}]},
    )  # fmt: skip

    assert status == memory_cli.OBSERVE_EXTRACTED
    mock_extract.assert_called_once()


@pytest.mark.parametrize(
    "extraction",
    [
        {"facts": [], "decisions": []},
        {"facts": [{"content": "   "}]},
        {"preferences": [{"content": "Only a preference"}]},
    ],
    ids=["empty-arrays", "blank-content", "only-preferences"],
)
def test_nothing_worth_storing(data_dir, digest, monkeypatch, capsys, extraction):
    status, _ = _run(
        monkeypatch, "--file", str(digest), "--project", "maitre-d", "--json",
        extraction=extraction,
    )  # fmt: skip

    assert status == memory_cli.OBSERVE_NOTHING
    captured = capsys.readouterr()
    assert json.loads(captured.out)["outcome"] == "nothing"
    assert captured.err.strip()
    assert _rows() == []
    # Still logged, so the observations browser shows the run happened.
    assert len(_raw_records(data_dir)) == 1


def test_empty_text_is_nothing_without_an_llm_call(data_dir, tmp_path, monkeypatch):
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n")

    status, mock_extract = _run(
        monkeypatch, "--file", str(empty), "--project", "maitre-d"
    )

    assert status == memory_cli.OBSERVE_NOTHING
    mock_extract.assert_not_called()


@pytest.mark.parametrize(
    ("extraction", "reason"),
    [(None, "timed out or exited non-zero"), ({}, "could not be parsed")],
    ids=["transport", "unparseable"],
)
def test_llm_failure(data_dir, digest, monkeypatch, capsys, extraction, reason):
    status, _ = _run(
        monkeypatch, "--file", str(digest), "--project", "maitre-d", "--json",
        extraction=extraction,
    )  # fmt: skip

    assert status == memory_cli.OBSERVE_LLM_FAILURE
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["outcome"] == "llm_failure"
    assert reason in doc["reason"]
    assert reason in captured.err
    assert _raw_records(data_dir) == []


def test_text_over_max_chars_is_refused(data_dir, digest, monkeypatch, capsys):
    status, mock_extract = _run(
        monkeypatch, "--file", str(digest), "--project", "maitre-d", "--max-chars", "10"
    )

    assert status == memory_cli.OBSERVE_ERROR
    mock_extract.assert_not_called()
    assert "--max-chars" in capsys.readouterr().err


def test_missing_claude_is_an_error_not_an_llm_failure(
    data_dir, digest, monkeypatch, capsys
):
    status, mock_extract = _run(
        monkeypatch, "--file", str(digest), "--project", "maitre-d", claude=None
    )

    assert status == memory_cli.OBSERVE_ERROR
    mock_extract.assert_not_called()
    assert "not on PATH" in capsys.readouterr().err


def test_unreadable_file_is_an_error(data_dir, tmp_path, monkeypatch, capsys):
    status, _ = _run(
        monkeypatch, "--file", str(tmp_path / "missing.txt"), "--project", "maitre-d"
    )

    assert status == memory_cli.OBSERVE_ERROR
    assert "cannot read" in capsys.readouterr().err


def test_every_write_failing_is_an_error(data_dir, digest, monkeypatch, capsys):
    with patch(
        "mait_code.hooks.observe.storage.store_memory", side_effect=RuntimeError("db")
    ):
        status, _ = _run(
            monkeypatch, "--file", str(digest), "--project", "maitre-d", "--json",
            extraction={"facts": [{"content": "A"}, {"content": "B"}]},
        )  # fmt: skip

    assert status == memory_cli.OBSERVE_ERROR
    doc = json.loads(capsys.readouterr().out)
    assert doc["outcome"] == "error"
    assert doc["counts"]["facts"]["failed"] == 2


@pytest.mark.parametrize("trigger", ["Job", "job run", "job_1", ""])
def test_trigger_must_be_a_slug(data_dir, digest, monkeypatch, trigger):
    status, mock_extract = _run(
        monkeypatch,
        "--file", str(digest), "--project", "maitre-d", "--trigger", trigger,
    )  # fmt: skip

    assert status == 2  # argparse usage error
    mock_extract.assert_not_called()


def test_blank_project_is_an_error(data_dir, digest, monkeypatch, capsys):
    status, _ = _run(monkeypatch, "--file", str(digest), "--project", "  ")

    assert status == memory_cli.OBSERVE_ERROR
    assert "--project" in capsys.readouterr().err
