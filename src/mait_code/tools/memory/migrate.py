"""
Schema migration for memory database.

Forward-only, idempotent migrations for memory.db.
Call ensure_schema(conn) after opening any connection to guarantee
the schema is current.

Migrations can be either:
- SQL lists: list[str] of SQL statements
- Callables: function(conn) for complex data migrations
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

type MigrationBody = list[str] | Callable[[sqlite3.Connection], None]


def _migrate_8_scoped_memory(conn: sqlite3.Connection) -> None:
    """Add scope/project/branch columns and rebuild FTS with new columns."""
    # 1. Add columns
    conn.execute(
        "ALTER TABLE memory_entries ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'"
    )
    conn.execute("ALTER TABLE memory_entries ADD COLUMN project TEXT DEFAULT NULL")
    conn.execute("ALTER TABLE memory_entries ADD COLUMN branch TEXT DEFAULT NULL")

    # 2. Create indexes
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_entries_scope ON memory_entries(scope)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_entries_project ON memory_entries(project)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_entries_project_scope "
        "ON memory_entries(project, scope)"
    )

    # 3. Drop old FTS triggers
    conn.execute("DROP TRIGGER IF EXISTS memory_entries_ai")
    conn.execute("DROP TRIGGER IF EXISTS memory_entries_ad")
    conn.execute("DROP TRIGGER IF EXISTS memory_entries_au")

    # 4. Drop and recreate FTS table with project and scope columns
    conn.execute("DROP TABLE IF EXISTS memory_entries_fts")
    conn.execute(
        """CREATE VIRTUAL TABLE memory_entries_fts
           USING fts5(content, entry_type, project, scope,
                      content=memory_entries, content_rowid=id)"""
    )

    # 5. Repopulate FTS from existing data
    conn.execute(
        """INSERT INTO memory_entries_fts(rowid, content, entry_type, project, scope)
           SELECT id, content, entry_type, COALESCE(project, ''), COALESCE(scope, 'global')
           FROM memory_entries"""
    )

    # 6. Recreate sync triggers with new columns
    conn.execute(
        """CREATE TRIGGER memory_entries_ai AFTER INSERT ON memory_entries BEGIN
             INSERT INTO memory_entries_fts(rowid, content, entry_type, project, scope)
             VALUES (new.id, new.content, new.entry_type,
                     COALESCE(new.project, ''), COALESCE(new.scope, 'global'));
           END"""
    )
    conn.execute(
        """CREATE TRIGGER memory_entries_ad AFTER DELETE ON memory_entries BEGIN
             INSERT INTO memory_entries_fts(
                 memory_entries_fts, rowid, content, entry_type, project, scope)
             VALUES ('delete', old.id, old.content, old.entry_type,
                     COALESCE(old.project, ''), COALESCE(old.scope, 'global'));
           END"""
    )
    conn.execute(
        """CREATE TRIGGER memory_entries_au AFTER UPDATE ON memory_entries BEGIN
             INSERT INTO memory_entries_fts(
                 memory_entries_fts, rowid, content, entry_type, project, scope)
             VALUES ('delete', old.id, old.content, old.entry_type,
                     COALESCE(old.project, ''), COALESCE(old.scope, 'global'));
             INSERT INTO memory_entries_fts(rowid, content, entry_type, project, scope)
             VALUES (new.id, new.content, new.entry_type,
                     COALESCE(new.project, ''), COALESCE(new.scope, 'global'));
           END"""
    )


MIGRATIONS: list[tuple[int, str, MigrationBody]] = [
    (
        1,
        "Create memory_entries table with indexes",
        [
            """CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                entry_type TEXT NOT NULL DEFAULT 'fact',
                importance INTEGER NOT NULL DEFAULT 5,
                memory_class TEXT NOT NULL DEFAULT 'episodic',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_memory_entries_created_at ON memory_entries(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_memory_entries_type ON memory_entries(entry_type)",
            "CREATE INDEX IF NOT EXISTS idx_memory_entries_importance ON memory_entries(importance DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memory_entries_class ON memory_entries(memory_class)",
        ],
    ),
    (
        2,
        "Create FTS5 virtual table for full-text search",
        [
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_entries_fts
               USING fts5(content, entry_type, content=memory_entries, content_rowid=id)""",
            """INSERT INTO memory_entries_fts(rowid, content, entry_type)
               SELECT id, content, entry_type FROM memory_entries""",
        ],
    ),
    (
        3,
        "Create triggers to keep FTS in sync with memory_entries",
        [
            """CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN
                 INSERT INTO memory_entries_fts(rowid, content, entry_type)
                 VALUES (new.id, new.content, new.entry_type);
               END""",
            """CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN
                 INSERT INTO memory_entries_fts(memory_entries_fts, rowid, content, entry_type)
                 VALUES ('delete', old.id, old.content, old.entry_type);
               END""",
            """CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE ON memory_entries BEGIN
                 INSERT INTO memory_entries_fts(memory_entries_fts, rowid, content, entry_type)
                 VALUES ('delete', old.id, old.content, old.entry_type);
                 INSERT INTO memory_entries_fts(rowid, content, entry_type)
                 VALUES (new.id, new.content, new.entry_type);
               END""",
        ],
    ),
    (
        4,
        "Create vec0 virtual table for vector search (requires sqlite-vec)",
        [
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec
               USING vec0(embedding float[1536] distance_metric=cosine)""",
        ],
    ),
    (
        5,
        "Create memory_entities table for entity tracking",
        [
            """CREATE TABLE IF NOT EXISTS memory_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                mention_count INTEGER NOT NULL DEFAULT 1
            )""",
            "CREATE INDEX IF NOT EXISTS idx_entities_name ON memory_entities(name COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_entities_type ON memory_entities(entity_type)",
        ],
    ),
    (
        6,
        "Create memory_relationships table for entity relationships",
        [
            """CREATE TABLE IF NOT EXISTS memory_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id INTEGER NOT NULL REFERENCES memory_entities(id),
                target_entity_id INTEGER NOT NULL REFERENCES memory_entities(id),
                relationship_type TEXT NOT NULL,
                context TEXT,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_unique
                ON memory_relationships(source_entity_id, target_entity_id, relationship_type)""",
            "CREATE INDEX IF NOT EXISTS idx_rel_source ON memory_relationships(source_entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_rel_target ON memory_relationships(target_entity_id)",
        ],
    ),
    (
        7,
        "Recreate memory_vec with 768 dimensions for nomic-embed-text-v1.5",
        [
            "DROP TABLE IF EXISTS memory_vec",
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec
               USING vec0(embedding float[768] distance_metric=cosine)""",
            """CREATE TRIGGER IF NOT EXISTS memory_entries_vec_ad
               AFTER DELETE ON memory_entries BEGIN
                 DELETE FROM memory_vec WHERE rowid = old.id;
               END""",
        ],
    ),
    (
        8,
        "Add scope, project, branch columns for scoped memory",
        _migrate_8_scoped_memory,
    ),
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Apply any pending migrations to the database.

    Safe to call on every connection open — checks a single integer
    and returns immediately if the schema is current.

    Gracefully skips vec0 migrations if sqlite-vec extension
    is not loaded.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )"""
    )
    conn.commit()

    cursor = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    current_version = cursor.fetchone()[0]

    for version, description, body in MIGRATIONS:
        if version <= current_version:
            continue

        try:
            if callable(body):
                body(conn)
            else:
                for sql in body:
                    conn.execute(sql)
        except Exception as e:
            # vec0 migrations require sqlite-vec extension loaded.
            # If it's not available, skip gracefully — will run on next
            # connection that has the extension.
            if "vec0" in str(e).lower() or "no such module" in str(e).lower():
                logger.debug(
                    "Migration %d skipped (sqlite-vec not loaded): %s", version, e
                )
                break  # Stop here — later migrations may depend on vec0
            raise

        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, description),
        )
        conn.commit()
        logger.info("Migration %d: %s", version, description)
