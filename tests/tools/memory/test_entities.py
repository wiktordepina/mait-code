"""Tests for entity and relationship CRUD operations."""

import sqlite3

from mait_code.tools.memory.entities import (
    find_entity_by_name,
    get_entity_relationships,
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
