"""Tests for observation storage bridge."""

import json
from pathlib import Path
from unittest.mock import patch

from mait_code.hooks.observe.storage import (
    store_entities_and_relationships,
    store_extraction,
    write_raw_extraction,
)


def test_write_raw_extraction(data_dir: Path):
    extraction = {"facts": [{"content": "test fact", "importance": 5}]}
    write_raw_extraction(extraction, "precompact")

    obs_dir = data_dir / "memory" / "observations"
    jsonl_files = list(obs_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1

    with open(jsonl_files[0]) as f:
        record = json.loads(f.readline())
    assert record["trigger"] == "precompact"
    assert record["extraction"]["facts"][0]["content"] == "test fact"


def test_write_raw_extraction_appends(data_dir: Path):
    write_raw_extraction({"facts": []}, "precompact")
    write_raw_extraction({"facts": []}, "session-end")

    obs_dir = data_dir / "memory" / "observations"
    jsonl_files = list(obs_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1

    with open(jsonl_files[0]) as f:
        lines = f.readlines()
    assert len(lines) == 2


def test_store_extraction_creates_memories(data_dir: Path):
    extraction = {
        "facts": [{"content": "project uses SQLite", "importance": 7}],
        "preferences": [{"content": "prefers dark mode", "importance": 6}],
        "decisions": [{"content": "chose REST over GraphQL", "importance": 8}],
        "bugs_fixed": [{"content": "fixed null pointer in auth", "importance": 7}],
        "entities": [],
        "relationships": [],
    }

    with (
        patch("mait_code.hooks.observe.storage.store_memory") as mock_store,
        patch("mait_code.hooks.observe.storage.get_connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_store.return_value = {"action": "created", "id": 1, "content": ""}

        store_extraction(extraction)

        assert mock_store.call_count == 4
        # Check entry types
        call_types = [call.args[2] for call in mock_store.call_args_list]
        assert "fact" in call_types
        assert "preference" in call_types
        assert "insight" in call_types
        assert "event" in call_types


def test_store_extraction_skips_empty_content(data_dir: Path):
    extraction = {
        "facts": [
            {"content": "", "importance": 5},
            {"content": "real fact", "importance": 5},
        ],
        "preferences": [],
        "decisions": [],
        "bugs_fixed": [],
    }

    with (
        patch("mait_code.hooks.observe.storage.store_memory") as mock_store,
        patch("mait_code.hooks.observe.storage.get_connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_store.return_value = {"action": "created", "id": 1, "content": ""}

        store_extraction(extraction)
        assert mock_store.call_count == 1


def test_store_entities_and_relationships(data_dir: Path):
    extraction = {
        "entities": [
            {
                "name": "mait-code",
                "entity_type": "project",
                "context": "companion framework",
            },
            {"name": "SQLite", "entity_type": "tool", "context": "database"},
        ],
        "relationships": [
            {
                "source": "mait-code",
                "target": "SQLite",
                "relationship_type": "uses",
                "context": "for memory",
            },
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.get_connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [1, 2]
        mock_rel.return_value = 1

        store_entities_and_relationships(extraction)

        assert mock_entity.call_count == 2
        assert mock_rel.call_count == 1


def test_store_entities_auto_creates_for_relationships(data_dir: Path):
    extraction = {
        "entities": [],
        "relationships": [
            {
                "source": "Alpha",
                "target": "Beta",
                "relationship_type": "uses",
                "context": "",
            },
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.get_connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [10, 20]
        mock_rel.return_value = 1

        store_entities_and_relationships(extraction)

        # Both entities auto-created
        assert mock_entity.call_count == 2
        assert mock_rel.call_count == 1
