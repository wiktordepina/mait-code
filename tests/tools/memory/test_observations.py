"""Tests for the observation queries (the raw extraction tier's read layer)."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from mait_code.tools.memory.observations import (
    daily_batches,
    list_observations,
    observation_projects,
)
from mait_code.tools.memory.reflect import update_watermark


def _seed(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, str, str | None]],
) -> None:
    """Insert (content, entry_type, scope, project) rows directly."""
    for content, entry_type, scope, project in rows:
        conn.execute(
            """INSERT INTO memory_entries
               (content, entry_type, importance, memory_class, scope, project)
               VALUES (?, ?, 5, 'episodic', ?, ?)""",
            (content, entry_type, scope, project),
        )
    conn.commit()


# -- list_observations ----------------------------------------------------------


def test_excludes_insights_and_orders_newest_first(memory_db) -> None:
    _seed(
        memory_db,
        [
            ("older fact", "fact", "global", None),
            ("an insight", "insight", "global", None),
            ("newer decision", "decision", "global", None),
        ],
    )
    entries = list_observations(memory_db)
    assert [e["content"] for e in entries] == ["newer decision", "older fact"]


def test_no_watermark_means_everything_pending(memory_db) -> None:
    _seed(memory_db, [("a fact", "fact", "global", None)])
    entries = list_observations(memory_db)
    assert entries and all(not e["reflected"] for e in entries)


def test_watermark_splits_reflected_from_pending(memory_db) -> None:
    _seed(
        memory_db,
        [
            ("reflected fact", "fact", "global", None),
            ("pending fact", "fact", "global", None),
        ],
    )
    first_id = memory_db.execute("SELECT MIN(id) FROM memory_entries").fetchone()[0]
    update_watermark(memory_db, first_id)

    by_content = {e["content"]: e["reflected"] for e in list_observations(memory_db)}
    assert by_content == {"reflected fact": True, "pending fact": False}


def test_project_filter_includes_global_and_uses_project_watermark(
    memory_db,
) -> None:
    _seed(
        memory_db,
        [
            ("global fact", "fact", "global", None),
            ("alpha fact", "fact", "project", "alpha"),
            ("beta fact", "fact", "project", "beta"),
        ],
    )
    # The *global* watermark covers everything; alpha has never been reflected,
    # so an alpha-scoped listing must ignore the global mark and show pending.
    last_id = memory_db.execute("SELECT MAX(id) FROM memory_entries").fetchone()[0]
    update_watermark(memory_db, last_id)

    entries = list_observations(memory_db, project="alpha")
    assert {e["content"] for e in entries} == {"global fact", "alpha fact"}
    assert all(not e["reflected"] for e in entries)

    update_watermark(memory_db, last_id, project="alpha")
    assert all(e["reflected"] for e in list_observations(memory_db, project="alpha"))


# -- observation_projects ---------------------------------------------------------


def test_projects_are_distinct_sorted_and_skip_insights(memory_db) -> None:
    _seed(
        memory_db,
        [
            ("b fact", "fact", "project", "beta"),
            ("a fact", "fact", "project", "alpha"),
            ("a fact too", "fact", "project", "alpha"),
            ("global fact", "fact", "global", None),
            ("gamma insight", "insight", "project", "gamma"),
        ],
    )
    assert observation_projects(memory_db) == ["alpha", "beta"]


# -- daily_batches ----------------------------------------------------------------


def _write_log(tmp_path: Path, day: str, lines: list[str]) -> None:
    obs_dir = tmp_path / "memory" / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    (obs_dir / f"{day}.jsonl").write_text("\n".join(lines) + "\n")


def test_daily_batches_missing_file_is_empty(tmp_path: Path) -> None:
    with patch(
        "mait_code.tools.memory.observations.get_data_dir", return_value=tmp_path
    ):
        assert daily_batches("2026-06-09") == []


def test_daily_batches_summarises_counts_and_skips_malformed(tmp_path: Path) -> None:
    record = {
        "timestamp": "2026-06-09T09:30:00+00:00",
        "trigger": "session-end",
        "project": "mait-code",
        "branch": "main",
        "extraction": {
            "facts": [{"content": "a"}, {"content": "b"}],
            "preferences": [],
            "entities": [{"name": "Cody"}],
        },
    }
    _write_log(
        tmp_path,
        "2026-06-09",
        ["not json", json.dumps(record), json.dumps(["not", "a", "dict"]), ""],
    )

    with patch(
        "mait_code.tools.memory.observations.get_data_dir", return_value=tmp_path
    ):
        batches = daily_batches("2026-06-09")

    assert len(batches) == 1
    batch = batches[0]
    assert batch["trigger"] == "session-end"
    assert batch["project"] == "mait-code"
    # Zero-count categories are omitted; present ones carry their counts.
    assert batch["counts"] == {"facts": 2, "entities": 1}
