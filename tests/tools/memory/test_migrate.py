"""Tests for schema migration system."""

import sqlite3

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
    assert versions == 8  # Exactly 8 migrations


def test_schema_version_tracking(memory_db: sqlite3.Connection):
    """All migrations should be recorded in schema_version."""
    rows = memory_db.execute(
        "SELECT version, description FROM schema_version ORDER BY version"
    ).fetchall()

    assert len(rows) == 8
    assert rows[0][0] == 1
    assert rows[-1][0] == 8


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
