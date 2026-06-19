"""Tests for schema migration system."""

import sqlite3

import pytest

from mait_code.tools.memory.migrate import ensure_schema


def test_ensure_schema_creates_tables(memory_db: sqlite3.Connection):
    """All core tables should exist after migration."""
    tables = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r[0] for r in tables}

    assert "memory_entries" in table_names
    assert "schema_version" in table_names


def test_ensure_schema_creates_fts(memory_db: sqlite3.Connection):
    """FTS5 virtual table should exist."""
    tables = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries_fts'"
    ).fetchall()
    assert len(tables) == 1


def test_ensure_schema_creates_vec0(memory_db: sqlite3.Connection):
    """Vec0 virtual table should exist (sqlite-vec is loaded in test fixture)."""
    tables = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vec'"
    ).fetchall()
    assert len(tables) == 1


def test_ensure_schema_idempotent(memory_db: sqlite3.Connection):
    """Running ensure_schema twice should not raise or duplicate migrations."""
    ensure_schema(memory_db)
    ensure_schema(memory_db)

    versions = memory_db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert versions == 12  # Exactly 12 migrations


def test_schema_version_tracking(memory_db: sqlite3.Connection):
    """All migrations should be recorded in schema_version."""
    rows = memory_db.execute(
        "SELECT version, description FROM schema_version ORDER BY version"
    ).fetchall()

    assert len(rows) == 12
    assert rows[0][0] == 1
    assert rows[-1][0] == 12


def test_fts_trigger_on_insert(memory_db: sqlite3.Connection):
    """Inserting into memory_entries should auto-populate FTS."""
    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type) VALUES (?, ?)",
        ("test content for FTS", "fact"),
    )
    memory_db.commit()

    results = memory_db.execute(
        "SELECT rowid FROM memory_entries_fts WHERE memory_entries_fts MATCH 'test'"
    ).fetchall()
    assert len(results) == 1


def test_fts_trigger_on_delete(memory_db: sqlite3.Connection):
    """Deleting from memory_entries should remove from FTS."""
    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type) VALUES (?, ?)",
        ("deletable content", "fact"),
    )
    memory_db.commit()
    entry_id = memory_db.execute("SELECT last_insert_rowid()").fetchone()[0]

    memory_db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
    memory_db.commit()

    results = memory_db.execute(
        "SELECT rowid FROM memory_entries_fts WHERE memory_entries_fts MATCH 'deletable'"
    ).fetchall()
    assert len(results) == 0


def test_fts_trigger_on_update(memory_db: sqlite3.Connection):
    """Updating content in memory_entries should update FTS."""
    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type) VALUES (?, ?)",
        ("original content", "fact"),
    )
    memory_db.commit()
    entry_id = memory_db.execute("SELECT last_insert_rowid()").fetchone()[0]

    memory_db.execute(
        "UPDATE memory_entries SET content = ? WHERE id = ?",
        ("updated content", entry_id),
    )
    memory_db.commit()

    # Old content should not match
    old = memory_db.execute(
        "SELECT rowid FROM memory_entries_fts WHERE memory_entries_fts MATCH 'original'"
    ).fetchall()
    assert len(old) == 0

    # New content should match
    new = memory_db.execute(
        "SELECT rowid FROM memory_entries_fts WHERE memory_entries_fts MATCH 'updated'"
    ).fetchall()
    assert len(new) == 1


def test_memory_entries_columns(memory_db: sqlite3.Connection):
    """Verify all expected columns exist on memory_entries."""
    cursor = memory_db.execute("PRAGMA table_info(memory_entries)")
    columns = {r[1] for r in cursor.fetchall()}

    expected = {
        "id",
        "content",
        "entry_type",
        "importance",
        "memory_class",
        "created_at",
        "scope",
        "project",
        "branch",
        "superseded_by",
        "superseded_at",
    }
    assert expected == columns


def test_migration_5_creates_entities_table(memory_db: sqlite3.Connection):
    """memory_entities table should exist with correct columns."""
    cursor = memory_db.execute("PRAGMA table_info(memory_entities)")
    columns = {r[1] for r in cursor.fetchall()}
    expected = {"id", "name", "entity_type", "first_seen", "last_seen", "mention_count"}
    assert expected == columns


def test_migration_6_creates_relationships_table(memory_db: sqlite3.Connection):
    """memory_relationships table should exist with correct columns."""
    cursor = memory_db.execute("PRAGMA table_info(memory_relationships)")
    columns = {r[1] for r in cursor.fetchall()}
    expected = {
        "id",
        "source_entity_id",
        "target_entity_id",
        "relationship_type",
        "context",
        "first_seen",
        "last_seen",
    }
    assert expected == columns


def test_migration_7_recreates_vec_768(memory_db: sqlite3.Connection):
    """memory_vec should exist as a vec0 table after migration 7."""
    tables = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_vec'"
    ).fetchall()
    assert len(tables) == 1


def test_migration_11_supersede_index(memory_db: sqlite3.Connection):
    """The partial superseded index should exist after migration 11."""
    indexes = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='idx_memory_entries_superseded'"
    ).fetchall()
    assert len(indexes) == 1

    # Verify migration 7 is recorded
    row = memory_db.execute(
        "SELECT description FROM schema_version WHERE version = 7"
    ).fetchone()
    assert row is not None
    assert "768" in row[0]


def test_migration_8_adds_scope_columns(memory_db: sqlite3.Connection):
    """Migration 8 should add scope, project, branch columns."""
    cursor = memory_db.execute("PRAGMA table_info(memory_entries)")
    columns = {r[1] for r in cursor.fetchall()}
    assert "scope" in columns
    assert "project" in columns
    assert "branch" in columns


def test_migration_8_existing_entries_default_global(memory_db: sqlite3.Connection):
    """Existing entries should have scope='global' after migration."""
    # The fixture runs all migrations on a fresh DB, so insert and check defaults
    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type) VALUES (?, ?)",
        ("test entry", "fact"),
    )
    memory_db.commit()

    row = memory_db.execute(
        "SELECT scope, project, branch FROM memory_entries WHERE content = ?",
        ("test entry",),
    ).fetchone()
    assert row[0] == "global"
    assert row[1] is None
    assert row[2] is None


def test_migration_8_fts_includes_project_scope(memory_db: sqlite3.Connection):
    """FTS table should include project and scope columns after migration 8."""
    memory_db.execute(
        """INSERT INTO memory_entries (content, entry_type, project, scope)
           VALUES (?, ?, ?, ?)""",
        ("scoped test content", "fact", "my-project", "project"),
    )
    memory_db.commit()

    # Search by project name in FTS (quote to handle hyphens)
    results = memory_db.execute(
        """SELECT m.id FROM memory_entries_fts f
           JOIN memory_entries m ON m.id = f.rowid
           WHERE memory_entries_fts MATCH '"my-project"'"""
    ).fetchall()
    assert len(results) == 1


def test_migration_10_relabels_insight_to_decision(memory_db: sqlite3.Connection):
    """With no reflection watermark, extracted 'insight' rows become 'decision'."""
    from mait_code.tools.memory.migrate import _migrate_10_decision_entry_type

    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type, memory_class) "
        "VALUES (?, 'insight', 'semantic')",
        ("chose REST over GraphQL",),
    )
    memory_db.commit()

    _migrate_10_decision_entry_type(memory_db)
    memory_db.commit()

    row = memory_db.execute(
        "SELECT entry_type FROM memory_entries WHERE content = ?",
        ("chose REST over GraphQL",),
    ).fetchone()
    assert row[0] == "decision"

    # The AU trigger keeps the FTS shadow table in sync with the new type.
    hits = memory_db.execute(
        "SELECT rowid FROM memory_entries_fts "
        "WHERE memory_entries_fts MATCH 'entry_type:decision'"
    ).fetchall()
    assert len(hits) == 1


def test_migration_10_skips_when_reflection_has_run(memory_db: sqlite3.Connection):
    """If reflection has run, existing 'insight' rows are left untouched."""
    from mait_code.tools.memory.migrate import _migrate_10_decision_entry_type

    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type, memory_class) "
        "VALUES (?, 'insight', 'semantic')",
        ("a genuine reflective insight",),
    )
    # Simulate a prior reflection run.
    memory_db.execute(
        "INSERT INTO reflection_watermark (project, last_reflected_id) VALUES ('', 1)"
    )
    memory_db.commit()

    _migrate_10_decision_entry_type(memory_db)
    memory_db.commit()

    row = memory_db.execute(
        "SELECT entry_type FROM memory_entries WHERE content = ?",
        ("a genuine reflective insight",),
    ).fetchone()
    assert row[0] == "insight"


def test_vec_delete_trigger(memory_db: sqlite3.Connection):
    """Deleting a memory entry should remove its embedding via trigger."""
    import struct

    memory_db.execute(
        "INSERT INTO memory_entries (content, entry_type) VALUES (?, ?)",
        ("trigger test", "fact"),
    )
    memory_db.commit()
    entry_id = memory_db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert a fake embedding
    fake_vec = struct.pack("768f", *([0.1] * 768))
    memory_db.execute(
        "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
        (entry_id, fake_vec),
    )
    memory_db.commit()

    # Verify embedding exists
    count = memory_db.execute(
        "SELECT COUNT(*) FROM memory_vec WHERE rowid = ?", (entry_id,)
    ).fetchone()[0]
    assert count == 1

    # Delete entry — trigger should remove embedding
    memory_db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
    memory_db.commit()

    count = memory_db.execute(
        "SELECT COUNT(*) FROM memory_vec WHERE rowid = ?", (entry_id,)
    ).fetchone()[0]
    assert count == 0


def _rewind_to_version_11_with_legacy_rows(conn: sqlite3.Connection) -> None:
    """Insert pre-coercion rows and rewind schema_version so migration 12 re-runs."""
    conn.executemany(
        "INSERT INTO memory_entities (name, entity_type) VALUES (?, ?)",
        [
            ("svc", "tool"),  # canonical — untouched
            ("box", "infrastructure"),  # legacy — service
            ("widget", "component"),  # legacy — concept
            ("mystery", "blob"),  # unmapped legacy — unknown
        ],
    )
    ids = {
        name: conn.execute(
            "SELECT id FROM memory_entities WHERE name = ?", (name,)
        ).fetchone()[0]
        for name in ("svc", "box", "widget", "mystery")
    }
    conn.executemany(
        """INSERT INTO memory_relationships
           (source_entity_id, target_entity_id, relationship_type, context)
           VALUES (?, ?, ?, ?)""",
        [
            (ids["svc"], ids["box"], "uses", "canonical, untouched"),
            (ids["svc"], ids["box"], "runs_on", "remaps to depends_on"),
            (ids["widget"], ids["box"], "wires_into", "unmapped, to related_to"),
            # Collision pair: remapping the second onto the first must merge.
            (ids["box"], ids["widget"], "related_to", "existing canonical"),
            (ids["box"], ids["widget"], "connected_to", "collides on remap"),
        ],
    )
    conn.execute("DELETE FROM schema_version WHERE version = 12")
    conn.commit()


def test_migration_12_remaps_legacy_types(memory_db: sqlite3.Connection):
    """Legacy entity/relationship types end up canonical; collisions merge."""
    _rewind_to_version_11_with_legacy_rows(memory_db)
    ensure_schema(memory_db)

    entity_types = dict(
        memory_db.execute("SELECT name, entity_type FROM memory_entities").fetchall()
    )
    assert entity_types["svc"] == "tool"
    assert entity_types["box"] == "service"
    assert entity_types["widget"] == "concept"
    assert entity_types["mystery"] == "unknown"

    rels = memory_db.execute(
        "SELECT relationship_type, context FROM memory_relationships ORDER BY id"
    ).fetchall()
    types = [r[0] for r in rels]
    assert sorted(types) == ["depends_on", "related_to", "related_to", "uses"]
    # The colliding connected_to row merged into the existing related_to one.
    contexts = {r[1] for r in rels}
    assert "existing canonical" in contexts
    assert "collides on remap" not in contexts

    from mait_code.tools.memory.entities import (
        VALID_ENTITY_TYPES,
        VALID_RELATIONSHIP_TYPES,
    )

    leftover_rels = memory_db.execute(
        f"""SELECT COUNT(*) FROM memory_relationships
            WHERE relationship_type NOT IN ({",".join("?" * len(VALID_RELATIONSHIP_TYPES))})""",
        tuple(VALID_RELATIONSHIP_TYPES),
    ).fetchone()[0]
    leftover_entities = memory_db.execute(
        f"""SELECT COUNT(*) FROM memory_entities
            WHERE entity_type NOT IN ({",".join("?" * len(VALID_ENTITY_TYPES))})""",
        tuple(VALID_ENTITY_TYPES),
    ).fetchone()[0]
    assert leftover_rels == 0
    assert leftover_entities == 0


# ---------------------------------------------------------------------------
# Error handling in ensure_schema's migration loop
# ---------------------------------------------------------------------------


def test_migration_vec0_error_skips_gracefully():
    """A 'no such module' error skips the migration without raising.

    vec0 migrations need the sqlite-vec extension; when it isn't loaded the
    loop logs and stops rather than aborting connection setup.
    """
    from unittest.mock import patch

    import mait_code.tools.memory.migrate as migrate_mod

    conn = sqlite3.connect(":memory:")
    try:

        def _vec0_body(c):
            raise sqlite3.OperationalError("no such module: vec0")

        # A single migration that simulates the missing extension.
        fake_migrations = [(1, "needs vec0", _vec0_body)]
        with patch.object(migrate_mod, "MIGRATIONS", fake_migrations):
            # Must not raise — the error is swallowed and the loop breaks.
            migrate_mod.ensure_schema(conn)

        # Nothing was recorded since the migration was skipped.
        count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_migration_unrelated_error_propagates():
    """A non-vec0 error is re-raised rather than silently swallowed."""
    from unittest.mock import patch

    import mait_code.tools.memory.migrate as migrate_mod

    conn = sqlite3.connect(":memory:")
    try:

        def _broken_body(c):
            raise ValueError("genuine migration bug")

        fake_migrations = [(1, "broken", _broken_body)]
        with patch.object(migrate_mod, "MIGRATIONS", fake_migrations):
            with pytest.raises(ValueError, match="genuine migration bug"):
                migrate_mod.ensure_schema(conn)
    finally:
        conn.close()
