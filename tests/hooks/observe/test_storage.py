"""Tests for observation storage bridge."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from mait_code.hooks.observe.storage import (
    confine_extraction,
    record_extraction,
    store_entities_and_relationships,
    store_extraction,
    write_raw_extraction,
)


@pytest.fixture
def propagate_logs(monkeypatch):
    """Re-enable log propagation so ``caplog`` (rooted at the root logger) can see
    ``mait_code.*`` records.

    ``setup_logging()`` - run by an earlier test in the session - sets
    ``propagate=False`` on the ``mait_code`` logger, which otherwise swallows
    records before they reach caplog's root handler.
    """
    monkeypatch.setattr(logging.getLogger("mait_code"), "propagate", True)


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
        "procedures": [
            {"content": "to reindex: run mc-tool-memory reindex", "importance": 6}
        ],
        "bugs_fixed": [{"content": "fixed null pointer in auth", "importance": 7}],
        "entities": [],
        "relationships": [],
    }

    with (
        patch("mait_code.hooks.observe.storage.store_memory") as mock_store,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_store.return_value = {"action": "created", "id": 1, "content": ""}

        store_extraction(extraction)

        assert mock_store.call_count == 5
        # Check entry types
        call_types = [call.args[2] for call in mock_store.call_args_list]
        assert "fact" in call_types
        assert "preference" in call_types
        assert "decision" in call_types
        assert "procedure" in call_types
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
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
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
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
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
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [10, 20]
        mock_rel.return_value = 1

        store_entities_and_relationships(extraction)

        # Both entities auto-created
        assert mock_entity.call_count == 2
        assert mock_rel.call_count == 1


def test_store_relationship_keeps_valid_type(data_dir: Path):
    extraction = {
        "entities": [
            {"name": "A", "entity_type": "tool"},
            {"name": "B", "entity_type": "tool"},
        ],
        "relationships": [
            {"source": "A", "target": "B", "relationship_type": "depends_on"},
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [1, 2]
        mock_rel.return_value = 1

        store_entities_and_relationships(extraction)

        # relationship_type is the 4th positional arg to upsert_relationship
        assert mock_rel.call_args.args[3] == "depends_on"


def test_store_relationship_coerces_unknown_type(data_dir: Path):
    """An out-of-enum relationship type is coerced to related_to (edge preserved)."""
    extraction = {
        "entities": [
            {"name": "A", "entity_type": "tool"},
            {"name": "B", "entity_type": "tool"},
        ],
        "relationships": [
            {"source": "A", "target": "B", "relationship_type": "provides_lan_access"},
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [1, 2]
        mock_rel.return_value = 1

        store_entities_and_relationships(extraction)

        # Edge still written, but the invented label is normalised.
        assert mock_rel.call_count == 1
        assert mock_rel.call_args.args[3] == "related_to"


def test_store_extraction_warns_on_store_failure(
    data_dir: Path, caplog, propagate_logs
):
    """A store_memory failure for one item is logged and never propagates."""
    extraction = {"facts": [{"content": "a fact", "importance": 5}]}

    with (
        patch(
            "mait_code.hooks.observe.storage.store_memory",
            side_effect=RuntimeError("db locked"),
        ),
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
        caplog.at_level("WARNING", logger="mait_code.hooks.observe.storage"),
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None

        # Must not raise despite the store failure.
        store_extraction(extraction)

    assert "failed to store fact" in caplog.text


def test_store_entities_skips_unnamed(data_dir: Path):
    """Entities with blank names are skipped entirely."""
    extraction = {
        "entities": [
            {"name": "   ", "entity_type": "tool"},
            {"name": "Real", "entity_type": "tool"},
        ],
        "relationships": [],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.return_value = 1

        store_entities_and_relationships(extraction)

        # Only the named entity is upserted.
        assert mock_entity.call_count == 1
        assert mock_entity.call_args.args[1] == "Real"


def test_store_entities_warns_on_entity_failure(data_dir: Path, caplog, propagate_logs):
    """An upsert_entity failure is logged and does not abort the batch."""
    extraction = {
        "entities": [{"name": "Broken", "entity_type": "tool"}],
        "relationships": [],
    }

    with (
        patch(
            "mait_code.hooks.observe.storage.upsert_entity",
            side_effect=RuntimeError("constraint"),
        ),
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
        caplog.at_level("WARNING", logger="mait_code.hooks.observe.storage"),
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None

        store_entities_and_relationships(extraction)

    assert "failed to upsert entity 'Broken'" in caplog.text


def test_store_relationship_skips_when_endpoint_blank(data_dir: Path):
    """A relationship missing a source or target is skipped."""
    extraction = {
        "entities": [],
        "relationships": [
            {"source": "", "target": "B", "relationship_type": "uses"},
            {"source": "A", "target": "  ", "relationship_type": "uses"},
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None

        store_entities_and_relationships(extraction)

        # No endpoints created, no edges written.
        mock_entity.assert_not_called()
        mock_rel.assert_not_called()


def test_store_relationship_skips_when_source_autocreate_fails(
    data_dir: Path, caplog, propagate_logs
):
    """If auto-creating a relationship's source entity fails, the edge is skipped."""
    extraction = {
        "entities": [],
        "relationships": [
            {"source": "Ghost", "target": "Real", "relationship_type": "uses"},
        ],
    }

    with (
        patch(
            "mait_code.hooks.observe.storage.upsert_entity",
            side_effect=RuntimeError("cannot create"),
        ),
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
        caplog.at_level("WARNING", logger="mait_code.hooks.observe.storage"),
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None

        store_entities_and_relationships(extraction)

        mock_rel.assert_not_called()
    assert "failed to create entity 'Ghost'" in caplog.text


def test_store_relationship_skips_when_target_autocreate_fails(
    data_dir: Path, caplog, propagate_logs
):
    """If auto-creating a relationship's target entity fails, the edge is skipped."""
    extraction = {
        "entities": [],
        "relationships": [
            {"source": "Real", "target": "Ghost", "relationship_type": "uses"},
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.upsert_relationship") as mock_rel,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
        caplog.at_level("WARNING", logger="mait_code.hooks.observe.storage"),
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        # First call (source) succeeds, second (target auto-create) fails.
        mock_entity.side_effect = [1, RuntimeError("cannot create")]

        store_entities_and_relationships(extraction)

        mock_rel.assert_not_called()
    assert "failed to create entity 'Ghost'" in caplog.text


def test_store_relationship_warns_on_upsert_failure(
    data_dir: Path, caplog, propagate_logs
):
    """An upsert_relationship failure is logged and swallowed."""
    extraction = {
        "entities": [
            {"name": "A", "entity_type": "tool"},
            {"name": "B", "entity_type": "tool"},
        ],
        "relationships": [
            {"source": "A", "target": "B", "relationship_type": "uses"},
        ],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch(
            "mait_code.hooks.observe.storage.upsert_relationship",
            side_effect=RuntimeError("edge failed"),
        ),
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
        caplog.at_level("WARNING", logger="mait_code.hooks.observe.storage"),
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [1, 2]

        store_entities_and_relationships(extraction)

    assert "failed to upsert relationship" in caplog.text


def test_store_entity_coerces_unknown_type(data_dir: Path):
    """An out-of-enum entity type is coerced to unknown (entity preserved)."""
    extraction = {
        "entities": [
            {"name": "board TUI", "entity_type": "component"},
            {"name": "Ruff", "entity_type": "tool"},
        ],
        "relationships": [],
    }

    with (
        patch("mait_code.hooks.observe.storage.upsert_entity") as mock_entity,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_entity.side_effect = [1, 2]

        store_entities_and_relationships(extraction)

        # Both entities written; the invented type is normalised, the
        # canonical one passes through.
        assert mock_entity.call_count == 2
        assert mock_entity.call_args_list[0].args[1:] == ("board TUI", "unknown")
        assert mock_entity.call_args_list[1].args[1:] == ("Ruff", "tool")


def test_store_extraction_returns_counts(data_dir: Path):
    extraction = {
        "facts": [{"content": "new"}, {"content": "seen"}, {"content": "  "}],
        "decisions": [{"content": "broken"}],
    }
    actions = {"new": "created", "seen": "deduplicated"}

    def fake_store(conn, content, *args, **kwargs):
        if content == "broken":
            raise RuntimeError("db locked")
        return {"action": actions[content]}

    with (
        patch("mait_code.hooks.observe.storage.store_memory", side_effect=fake_store),
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        counts = store_extraction(extraction, project="p")

    assert counts["facts"] == {"created": 1, "deduplicated": 1, "failed": 0}
    assert counts["decisions"] == {"created": 0, "deduplicated": 0, "failed": 1}
    # Every category is present, so callers get a fixed shape.
    assert counts["procedures"] == {"created": 0, "deduplicated": 0, "failed": 0}


def test_store_extraction_passes_source(data_dir: Path):
    with (
        patch("mait_code.hooks.observe.storage.store_memory") as mock_store,
        patch("mait_code.hooks.observe.storage.connection") as mock_conn,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_store.return_value = {"action": "created"}
        store_extraction({"facts": [{"content": "x"}]}, project="p", source="job")

    assert mock_store.call_args.kwargs["source"] == "job"


def test_write_raw_extraction_records_source_only_when_set(data_dir: Path):
    write_raw_extraction({"facts": []}, "session-end")
    write_raw_extraction({"facts": []}, "job", source="job")

    (path,) = (data_dir / "memory" / "observations").glob("*.jsonl")
    hook, job = [json.loads(line) for line in path.read_text().splitlines()]
    assert "source" not in hook
    assert job["source"] == "job"


def test_confine_extraction_drops_preferences_and_pins_scope():
    extraction = {
        "facts": [
            {"content": "a", "scope": "global"},
            {"content": "b", "scope": "Branch"},
            {"content": "c"},
        ],
        "preferences": [{"content": "p", "scope": "global"}],
        "entities": [{"name": "e"}],
    }

    confined = confine_extraction(extraction, branch="feat/x")

    assert "preferences" not in confined
    assert [i["scope"] for i in confined["facts"]] == ["project", "branch", "project"]
    assert confined["entities"] == [{"name": "e"}]
    # The input is left alone.
    assert extraction["facts"][0]["scope"] == "global"
    assert "preferences" in extraction


def test_record_extraction_runs_the_whole_tail(data_dir: Path):
    extraction = {"facts": [{"content": "x"}]}
    with (
        patch("mait_code.hooks.observe.storage.write_raw_extraction") as mock_raw,
        patch(
            "mait_code.hooks.observe.storage.store_extraction",
            return_value={"facts": {"created": 1}},
        ) as mock_store,
        patch(
            "mait_code.hooks.observe.storage.store_entities_and_relationships"
        ) as mock_ent,
    ):
        counts = record_extraction(
            extraction, "job", project="p", branch="b", source="job"
        )

    mock_raw.assert_called_once_with(
        extraction, "job", project="p", branch="b", source="job"
    )
    mock_store.assert_called_once_with(
        extraction, project="p", branch="b", source="job"
    )
    mock_ent.assert_called_once_with(extraction)
    assert counts == {"facts": {"created": 1}}


def test_confine_extraction_without_a_branch_pins_branch_asks_to_project():
    """A branch-scoped row with no branch is unreachable by any search."""
    confined = confine_extraction(
        {"facts": [{"content": "a", "scope": "branch"}]}, branch=None
    )
    assert confined["facts"][0]["scope"] == "project"


def test_confine_extraction_caps_importance():
    confined = confine_extraction(
        {
            "facts": [
                {"content": "a", "importance": 10},
                {"content": "b", "importance": 3},
                {"content": "c", "importance": "high"},
                {"content": "d"},
            ]
        },
        branch=None,
    )
    assert [i["importance"] for i in confined["facts"]] == [7, 3, 5, 5]


@pytest.mark.parametrize(
    "extraction",
    [{"facts": "x"}, {"decisions": [1, 2]}, {"relationships": {"a": "b"}}],
)
def test_confine_extraction_rejects_malformed_shapes(extraction):
    with pytest.raises(ValueError, match="not a list of objects"):
        confine_extraction(extraction, branch=None)
