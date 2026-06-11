"""Tests for entity and relationship CRUD operations."""

import sqlite3

import pytest

from mait_code.tools.memory.entities import (
    find_entity_by_name,
    get_entity_relationships,
    merge_entities,
    search_entities,
    upsert_entity,
    upsert_relationship,
)


def test_upsert_entity_new(memory_db: sqlite3.Connection):
    entity_id = upsert_entity(memory_db, "PostgreSQL", "tool")
    assert entity_id > 0

    row = memory_db.execute(
        "SELECT name, entity_type, mention_count FROM memory_entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    assert row == ("PostgreSQL", "tool", 1)


def test_upsert_entity_existing_increments(memory_db: sqlite3.Connection):
    id1 = upsert_entity(memory_db, "PostgreSQL", "tool")
    id2 = upsert_entity(memory_db, "PostgreSQL", "tool")
    assert id1 == id2

    count = memory_db.execute(
        "SELECT mention_count FROM memory_entities WHERE id = ?", (id1,)
    ).fetchone()[0]
    assert count == 2


def test_upsert_entity_upgrades_unknown_type(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "Redis", "unknown")
    upsert_entity(memory_db, "Redis", "service")

    entity = find_entity_by_name(memory_db, "Redis")
    assert entity["entity_type"] == "service"


def test_upsert_entity_preserves_known_type(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "Redis", "tool")
    upsert_entity(memory_db, "Redis", "service")

    entity = find_entity_by_name(memory_db, "Redis")
    assert entity["entity_type"] == "tool"


def test_find_entity_case_insensitive(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "PostgreSQL", "tool")

    assert find_entity_by_name(memory_db, "postgresql") is not None
    assert find_entity_by_name(memory_db, "POSTGRESQL") is not None
    assert find_entity_by_name(memory_db, "nonexistent") is None


def test_upsert_relationship_new(memory_db: sqlite3.Connection):
    src = upsert_entity(memory_db, "mait-code", "project")
    tgt = upsert_entity(memory_db, "SQLite", "tool")
    rel_id = upsert_relationship(memory_db, src, tgt, "uses", "for memory storage")
    assert rel_id > 0

    row = memory_db.execute(
        "SELECT relationship_type, context FROM memory_relationships WHERE id = ?",
        (rel_id,),
    ).fetchone()
    assert row == ("uses", "for memory storage")


def test_upsert_relationship_existing_updates(memory_db: sqlite3.Connection):
    src = upsert_entity(memory_db, "mait-code", "project")
    tgt = upsert_entity(memory_db, "SQLite", "tool")
    id1 = upsert_relationship(memory_db, src, tgt, "uses", "for memory")
    id2 = upsert_relationship(
        memory_db, src, tgt, "uses", "for memory and observations"
    )
    assert id1 == id2

    context = memory_db.execute(
        "SELECT context FROM memory_relationships WHERE id = ?", (id1,)
    ).fetchone()[0]
    assert context == "for memory and observations"


def test_get_entity_relationships(memory_db: sqlite3.Connection):
    a = upsert_entity(memory_db, "mait-code", "project")
    b = upsert_entity(memory_db, "SQLite", "tool")
    c = upsert_entity(memory_db, "Python", "language")
    upsert_relationship(memory_db, a, b, "uses", "database")
    upsert_relationship(memory_db, c, a, "implements", "written in Python")

    rels = get_entity_relationships(memory_db, a)
    assert len(rels) == 2
    rel_types = {r["relationship_type"] for r in rels}
    assert rel_types == {"uses", "implements"}


def test_search_entities(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "PostgreSQL", "tool")
    upsert_entity(memory_db, "PostHog", "service")
    upsert_entity(memory_db, "Redis", "tool")

    results = search_entities(memory_db, "Post")
    assert len(results) == 2
    names = {r["name"] for r in results}
    assert names == {"PostgreSQL", "PostHog"}


def test_search_entities_limit(memory_db: sqlite3.Connection):
    for i in range(5):
        upsert_entity(memory_db, f"Entity{i}", "tool")

    results = search_entities(memory_db, "Entity", limit=3)
    assert len(results) == 3


def test_merge_entities_repoints_and_sums(memory_db: sqlite3.Connection):
    """Merging folds the source's edges and mentions into the target."""
    user = upsert_entity(memory_db, "User", "unknown")
    wiktor = upsert_entity(memory_db, "Wiktor", "person")
    ghostty = upsert_entity(memory_db, "Ghostty", "tool")
    cairn = upsert_entity(memory_db, "cairn", "project")
    upsert_relationship(memory_db, user, ghostty, "uses", "terminal")
    upsert_relationship(memory_db, cairn, user, "depends_on", "feedback loop")
    upsert_relationship(memory_db, wiktor, cairn, "owns", "side project")

    result = merge_entities(memory_db, "User", "Wiktor")

    assert result["relationships_repointed"] == 2
    assert result["relationships_deduplicated"] == 0
    assert result["self_loops_dropped"] == 0
    assert find_entity_by_name(memory_db, "User") is None
    merged = result["target"]
    assert merged["name"] == "Wiktor"
    assert merged["mention_count"] == 2  # 1 + 1
    rels = get_entity_relationships(memory_db, wiktor)
    assert len(rels) == 3
    pairs = {(r["source_name"], r["relationship_type"], r["target_name"]) for r in rels}
    assert ("Wiktor", "uses", "Ghostty") in pairs
    assert ("cairn", "depends_on", "Wiktor") in pairs


def test_merge_entities_deduplicates_collisions(memory_db: sqlite3.Connection):
    """An edge whose repointed form already exists merges instead of erroring."""
    user = upsert_entity(memory_db, "User", "unknown")
    wiktor = upsert_entity(memory_db, "Wiktor", "person")
    ghostty = upsert_entity(memory_db, "Ghostty", "tool")
    upsert_relationship(memory_db, user, ghostty, "uses", "terminal")
    upsert_relationship(memory_db, wiktor, ghostty, "uses", "daily driver")

    result = merge_entities(memory_db, "User", "Wiktor")

    assert result["relationships_deduplicated"] == 1
    assert result["relationships_repointed"] == 0
    rels = get_entity_relationships(memory_db, wiktor)
    assert len(rels) == 1
    assert rels[0]["context"] == "daily driver"  # target's context wins


def test_merge_entities_drops_self_loops(memory_db: sqlite3.Connection):
    """Edges between the pair are dropped rather than becoming self-loops."""
    user = upsert_entity(memory_db, "User", "unknown")
    wiktor = upsert_entity(memory_db, "Wiktor", "person")
    upsert_relationship(memory_db, user, wiktor, "related_to", "same person")

    result = merge_entities(memory_db, "User", "Wiktor")

    assert result["self_loops_dropped"] == 1
    loops = memory_db.execute(
        "SELECT COUNT(*) FROM memory_relationships WHERE source_entity_id = target_entity_id"
    ).fetchone()[0]
    assert loops == 0


def test_merge_entities_upgrades_unknown_target_type(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "Forgejo", "tool")
    upsert_entity(memory_db, "forgejo-git", "unknown")

    result = merge_entities(memory_db, "Forgejo", "forgejo-git")

    assert result["target"]["entity_type"] == "tool"


def test_merge_entities_case_insensitive_lookup(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "User", "unknown")
    upsert_entity(memory_db, "Wiktor", "person")

    result = merge_entities(memory_db, "user", "WIKTOR")
    assert result["target"]["name"] == "Wiktor"


def test_merge_entities_missing_source(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "Wiktor", "person")
    with pytest.raises(ValueError, match="'Nobody' not found"):
        merge_entities(memory_db, "Nobody", "Wiktor")


def test_merge_entities_missing_target(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "User", "unknown")
    with pytest.raises(ValueError, match="'Nobody' not found"):
        merge_entities(memory_db, "User", "Nobody")


def test_merge_entities_refuses_self_merge(memory_db: sqlite3.Connection):
    upsert_entity(memory_db, "Wiktor", "person")
    with pytest.raises(ValueError, match="same entity"):
        merge_entities(memory_db, "wiktor", "Wiktor")
