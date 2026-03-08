"""Tests for the reflection system."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.reflect import (
    _format_extraction,
    check_novelty_gate,
    count_entries_since,
    format_entries_text,
    generate_memory_diff,
    get_last_reflection_date,
    get_recent_entries,
    parse_reflection_response,
    read_memory_md,
    read_observation_logs,
    reflect,
    store_insights,
)


@pytest.fixture
def memory_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp database with full schema applied."""
    db_path = tmp_path / "test_memory.db"
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def db_with_entries(memory_db: sqlite3.Connection) -> sqlite3.Connection:
    """Database with recent entries of various types."""
    now = datetime.now()
    entries = [
        ("User prefers tabs over spaces", "preference", 7, now - timedelta(days=1)),
        ("Migrated auth to JWT", "fact", 8, now - timedelta(days=2)),
        ("Fixed race condition in worker pool", "event", 6, now - timedelta(days=3)),
        ("Use pytest -x for faster feedback", "preference", 5, now - timedelta(days=4)),
        ("API uses versioned endpoints /v2/", "fact", 7, now - timedelta(days=5)),
    ]
    for content, entry_type, importance, created_at in entries:
        memory_db.execute(
            """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
               VALUES (?, ?, ?, 'semantic', ?)""",
            (content, entry_type, importance, created_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
    memory_db.commit()
    return memory_db


@pytest.fixture
def obs_dir(tmp_path: Path) -> Path:
    """Create an observation log directory with sample JSONL files."""
    obs_path = tmp_path / "memory" / "observations"
    obs_path.mkdir(parents=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = obs_path / f"{today}.jsonl"

    records = [
        {
            "extraction": {
                "facts": [{"content": "Uses PostgreSQL 16", "importance": 7}],
                "preferences": [{"content": "Prefers dark mode", "importance": 5}],
                "decisions": [],
                "bugs_fixed": [],
                "entities": [{"name": "PostgreSQL", "entity_type": "tool", "context": "Primary database"}],
                "relationships": [],
            }
        },
        {
            "extraction": {
                "facts": [{"content": "Kubernetes cluster on GKE", "importance": 6}],
                "preferences": [],
                "decisions": [{"content": "Use Helm charts for deployment", "importance": 7}],
                "bugs_fixed": [],
                "entities": [],
                "relationships": [],
            }
        },
    ]
    with open(log_file, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    return obs_path


# --- get_last_reflection_date ---


def test_get_last_reflection_date_no_insights(memory_db):
    result = get_last_reflection_date(memory_db)
    assert result is None


def test_get_last_reflection_date_with_insight(memory_db):
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('test insight', 'insight', 6, 'semantic', '2026-03-01 12:00:00')"""
    )
    memory_db.commit()

    result = get_last_reflection_date(memory_db)
    assert result is not None
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 1


# --- count_entries_since ---


def test_count_entries_since(db_with_entries):
    since = datetime.now() - timedelta(days=3)
    count = count_entries_since(db_with_entries, since)
    # Should include entries from 1 and 2 days ago
    assert count >= 2


def test_count_entries_since_excludes_insights(memory_db):
    now = datetime.now()
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('an insight', 'insight', 6, 'semantic', ?)""",
        (now.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('a fact', 'fact', 5, 'semantic', ?)""",
        (now.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    memory_db.commit()

    since = now - timedelta(hours=1)
    count = count_entries_since(memory_db, since)
    assert count == 1  # Only the fact, not the insight


# --- check_novelty_gate ---


def test_novelty_gate_no_prior_reflection(memory_db):
    assert check_novelty_gate(memory_db) is True


def test_novelty_gate_enough_new_entries(db_with_entries):
    # Add an old insight
    db_with_entries.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('old insight', 'insight', 6, 'semantic', ?)""",
        ((datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    db_with_entries.commit()

    assert check_novelty_gate(db_with_entries, min_new=3) is True


def test_novelty_gate_not_enough_entries(memory_db):
    now = datetime.now()
    # Add a recent insight
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('recent insight', 'insight', 6, 'semantic', ?)""",
        ((now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    # Add only 1 new non-insight entry
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('one fact', 'fact', 5, 'semantic', ?)""",
        (now.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    memory_db.commit()

    assert check_novelty_gate(memory_db, min_new=3) is False


def test_novelty_gate_exactly_min_new(memory_db):
    now = datetime.now()
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('old insight', 'insight', 6, 'semantic', ?)""",
        ((now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    for i in range(3):
        memory_db.execute(
            """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
               VALUES (?, 'fact', 5, 'semantic', ?)""",
            (f"fact {i}", now.strftime("%Y-%m-%d %H:%M:%S")),
        )
    memory_db.commit()

    assert check_novelty_gate(memory_db, min_new=3) is True


# --- get_recent_entries ---


def test_get_recent_entries(db_with_entries):
    entries = get_recent_entries(db_with_entries, days=7)
    assert len(entries) == 5
    # Most recent first
    assert "tabs over spaces" in entries[0][0]


def test_get_recent_entries_excludes_insights(memory_db):
    now = datetime.now()
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('an insight', 'insight', 6, 'semantic', ?)""",
        (now.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('a fact', 'fact', 5, 'semantic', ?)""",
        (now.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    memory_db.commit()

    entries = get_recent_entries(memory_db, days=7)
    assert len(entries) == 1
    assert entries[0][1] == "fact"


# --- read_observation_logs ---


def test_read_observation_logs(obs_dir):
    # get_data_dir() / "memory" / "observations" must resolve to obs_dir
    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=obs_dir.parent.parent):
        text = read_observation_logs(days=7)

    assert "PostgreSQL 16" in text
    assert "Kubernetes cluster on GKE" in text
    assert "Prefers dark mode" in text
    assert "[entity] PostgreSQL" in text


def test_read_observation_logs_empty_dir(tmp_path):
    obs_dir = tmp_path / "memory" / "observations"
    obs_dir.mkdir(parents=True)

    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        text = read_observation_logs(days=7)

    assert text == ""


def test_read_observation_logs_no_dir(tmp_path):
    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        text = read_observation_logs(days=7)

    assert text == ""


# --- format_entries_text ---


def test_format_entries_text():
    entries = [
        ("User likes dark mode", "preference", 7, "2026-03-01 12:00:00"),
        ("Fixed auth bug", "event", 5, "2026-03-02 10:00:00"),
    ]
    text = format_entries_text(entries)
    assert "[2026-03-01]" in text
    assert "(preference, imp=7)" in text
    assert "Fixed auth bug" in text


def test_format_entries_text_empty():
    assert format_entries_text([]) == ""


# --- parse_reflection_response ---


def test_parse_reflection_response_full():
    response = """## Insights
INSIGHT: User consistently prefers minimal tooling
INSIGHT: Project is moving toward microservices architecture
INSIGHT: Testing practices emphasize speed over coverage

## Memory Updates
MEMORY_UPDATE: Primary stack: Python + PostgreSQL + Kubernetes
MEMORY_UPDATE: Prefers pytest with -x flag for fast feedback"""

    parsed = parse_reflection_response(response)
    assert len(parsed["insights"]) == 3
    assert "minimal tooling" in parsed["insights"][0]
    assert len(parsed["memory_updates"]) == 2
    assert "Primary stack" in parsed["memory_updates"][0]


def test_parse_reflection_response_insights_only():
    response = "INSIGHT: One key insight\nINSIGHT: Another insight"
    parsed = parse_reflection_response(response)
    assert len(parsed["insights"]) == 2
    assert len(parsed["memory_updates"]) == 0


def test_parse_reflection_response_empty():
    parsed = parse_reflection_response("No insights found here")
    assert len(parsed["insights"]) == 0
    assert len(parsed["memory_updates"]) == 0


def test_parse_reflection_response_blank_lines():
    response = "INSIGHT: first\n\nINSIGHT: \n\nINSIGHT: third"
    parsed = parse_reflection_response(response)
    # "INSIGHT: " with no text should be skipped
    assert len(parsed["insights"]) == 2


# --- store_insights ---


def test_store_insights(memory_db):
    insights = [
        "User consistently prefers minimal tooling and fast iteration cycles",
        "Project architecture is shifting toward microservices with Kubernetes orchestration",
    ]
    stored = store_insights(memory_db, insights)
    assert stored == 2

    rows = memory_db.execute(
        "SELECT content, entry_type, importance FROM memory_entries WHERE entry_type = 'insight'"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "insight"
    assert rows[0][2] == 6  # Fixed importance


def test_store_insights_empty(memory_db):
    stored = store_insights(memory_db, [])
    assert stored == 0


# --- generate_memory_diff ---


def test_generate_memory_diff():
    updates = ["Fact one", "Fact two"]
    diff = generate_memory_diff(updates)
    assert "+ Fact one" in diff
    assert "+ Fact two" in diff
    assert "Proposed additions" in diff


# --- reflect (integration) ---


def test_reflect_skipped_novelty_gate(memory_db):
    now = datetime.now()
    # Add a recent insight with no new entries after it
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('recent insight', 'insight', 6, 'semantic', ?)""",
        (now.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    memory_db.commit()

    result = reflect(memory_db, days=7, min_new=3)
    assert result["skipped"] is True
    assert "not enough" in result["reason"]


def test_reflect_skipped_no_data(memory_db):
    # No entries at all, no observation logs
    with patch("mait_code.tools.memory.reflect.read_observation_logs", return_value=""):
        result = reflect(memory_db, days=7, min_new=0)

    assert result["skipped"] is True
    assert "no data" in result["reason"]


def test_reflect_success(db_with_entries):
    llm_response = """## Insights
INSIGHT: User has a strong preference for speed in development workflows
INSIGHT: Project is in active migration phase across multiple systems
INSIGHT: Testing and iteration speed are prioritised over comprehensive coverage

## Memory Updates
MEMORY_UPDATE: Primary testing approach: pytest with -x flag"""

    with patch("mait_code.tools.memory.reflect.call_claude", return_value=llm_response), \
         patch("mait_code.tools.memory.reflect.read_observation_logs", return_value="some observations"):
        result = reflect(db_with_entries, days=7, min_new=0)

    assert result["skipped"] is False
    assert result["reason"] is None
    assert len(result["insights"]) == 3
    assert result["stored"] == 3
    assert result["memory_diff"] is not None
    assert "Primary testing approach" in result["memory_diff"]

    # Verify insights were stored in DB
    rows = db_with_entries.execute(
        "SELECT content FROM memory_entries WHERE entry_type = 'insight'"
    ).fetchall()
    assert len(rows) == 3


def test_reflect_llm_failure(db_with_entries):
    with patch("mait_code.tools.memory.reflect.call_claude", return_value=None), \
         patch("mait_code.tools.memory.reflect.read_observation_logs", return_value="obs"):
        result = reflect(db_with_entries, days=7, min_new=0)

    assert result["skipped"] is False
    assert "LLM call failed" in result["reason"]
    assert result["insights"] == []
    assert result["stored"] == 0


def test_reflect_no_memory_updates(db_with_entries):
    llm_response = "INSIGHT: Just one insight with no memory updates"

    with patch("mait_code.tools.memory.reflect.call_claude", return_value=llm_response), \
         patch("mait_code.tools.memory.reflect.read_observation_logs", return_value="obs"):
        result = reflect(db_with_entries, days=7, min_new=0)

    assert result["skipped"] is False
    assert result["memory_diff"] is None
    assert len(result["insights"]) == 1


def test_reflect_with_memory_md_content(db_with_entries, tmp_path):
    """Verify MEMORY.md content is included in the LLM prompt."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# Known Facts\n- Uses PostgreSQL")

    llm_response = "INSIGHT: An insight from reflection"
    captured_prompt = {}

    def fake_call_claude(prompt, **kwargs):
        captured_prompt["value"] = prompt
        return llm_response

    with patch("mait_code.tools.memory.reflect.call_claude", side_effect=fake_call_claude), \
         patch("mait_code.tools.memory.reflect.read_observation_logs", return_value="obs"), \
         patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        result = reflect(db_with_entries, days=7, min_new=0)

    assert result["skipped"] is False
    assert "Uses PostgreSQL" in captured_prompt["value"]
    assert "Current MEMORY.md content" in captured_prompt["value"]


# --- _format_extraction ---


def test_format_extraction_all_categories():
    extraction = {
        "facts": [{"content": "Uses PostgreSQL", "importance": 7}],
        "preferences": [{"content": "Prefers dark mode", "importance": 5}],
        "decisions": [{"content": "Chose REST over GraphQL", "importance": 8}],
        "bugs_fixed": [{"content": "Fixed memory leak in worker", "importance": 6}],
        "entities": [],
        "relationships": [],
    }
    text = _format_extraction(extraction)
    assert "[facts] (imp=7) Uses PostgreSQL" in text
    assert "[preferences] (imp=5) Prefers dark mode" in text
    assert "[decisions] (imp=8) Chose REST over GraphQL" in text
    assert "[bugs_fixed] (imp=6) Fixed memory leak in worker" in text


def test_format_extraction_entities():
    extraction = {
        "entities": [
            {"name": "PostgreSQL", "entity_type": "tool", "context": "Primary database"},
            {"name": "Alice", "entity_type": "person", "context": "Team lead"},
        ],
    }
    text = _format_extraction(extraction)
    assert "[entity] PostgreSQL (tool): Primary database" in text
    assert "[entity] Alice (person): Team lead" in text


def test_format_extraction_empty():
    assert _format_extraction({}) == ""
    assert _format_extraction({"facts": [], "entities": []}) == ""


def test_format_extraction_skips_empty_content():
    extraction = {
        "facts": [
            {"content": "  ", "importance": 5},  # whitespace only
            {"content": "", "importance": 3},  # empty
            {"content": "Valid fact", "importance": 7},
        ],
    }
    text = _format_extraction(extraction)
    assert "Valid fact" in text
    lines = [line for line in text.strip().split("\n") if line]
    assert len(lines) == 1


def test_format_extraction_truncates_long_content():
    long_content = "x" * 300
    extraction = {"facts": [{"content": long_content, "importance": 5}]}
    text = _format_extraction(extraction)
    # Content should be truncated at 200 chars
    assert len(long_content[:200]) == 200
    assert ("x" * 200) in text
    assert ("x" * 201) not in text


def test_format_extraction_default_importance():
    extraction = {"facts": [{"content": "No importance key"}]}
    text = _format_extraction(extraction)
    assert "(imp=5)" in text


def test_format_extraction_skips_nameless_entities():
    extraction = {
        "entities": [
            {"name": "", "entity_type": "tool", "context": "orphan"},
            {"name": "Valid", "entity_type": "tool", "context": "real"},
        ],
    }
    text = _format_extraction(extraction)
    assert "orphan" not in text
    assert "[entity] Valid" in text


# --- read_memory_md ---


def test_read_memory_md_exists(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# Facts\n- Uses uv")

    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        content = read_memory_md()

    assert content is not None
    assert "Uses uv" in content


def test_read_memory_md_missing(tmp_path):
    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        content = read_memory_md()

    assert content is None


# --- get_last_reflection_date edge cases ---


def test_get_last_reflection_date_malformed_timestamp(memory_db):
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, importance, memory_class, created_at)
           VALUES ('bad insight', 'insight', 6, 'semantic', 'not-a-date')"""
    )
    memory_db.commit()

    result = get_last_reflection_date(memory_db)
    assert result is None


# --- read_observation_logs edge cases ---


def test_read_observation_logs_skips_old_files(tmp_path):
    """Log files older than the days window should be excluded."""
    obs_dir = tmp_path / "memory" / "observations"
    obs_dir.mkdir(parents=True)

    # Create an old file (30 days ago)
    old_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    old_file = obs_dir / f"{old_date}.jsonl"
    old_file.write_text(json.dumps({
        "extraction": {"facts": [{"content": "Old fact", "importance": 5}]}
    }) + "\n")

    # Create a recent file
    today = datetime.now().strftime("%Y-%m-%d")
    new_file = obs_dir / f"{today}.jsonl"
    new_file.write_text(json.dumps({
        "extraction": {"facts": [{"content": "Recent fact", "importance": 5}]}
    }) + "\n")

    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        text = read_observation_logs(days=7)

    assert "Recent fact" in text
    assert "Old fact" not in text


def test_read_observation_logs_malformed_json(tmp_path):
    """Malformed JSON lines should be skipped, valid ones still parsed."""
    obs_dir = tmp_path / "memory" / "observations"
    obs_dir.mkdir(parents=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = obs_dir / f"{today}.jsonl"
    lines = [
        "this is not json",
        json.dumps({"extraction": {"facts": [{"content": "Valid fact", "importance": 7}]}}),
        "{broken json",
    ]
    log_file.write_text("\n".join(lines) + "\n")

    with patch("mait_code.tools.memory.reflect.get_data_dir", return_value=tmp_path):
        text = read_observation_logs(days=7)

    assert "Valid fact" in text
