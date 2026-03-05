"""Tests for schema migration system."""

import sqlite3

from mait_code.memory.migrate import ensure_schema


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
    assert versions == 4  # Exactly 4 migrations


def test_schema_version_tracking(memory_db: sqlite3.Connection):
    """All migrations should be recorded in schema_version."""
    rows = memory_db.execute(
        "SELECT version, description FROM schema_version ORDER BY version"
    ).fetchall()

    assert len(rows) == 4
    assert rows[0][0] == 1
    assert rows[-1][0] == 4


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
    }
    assert expected == columns
