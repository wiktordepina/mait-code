"""Schema migration for the memory database.

Forward-only, idempotent migrations for ``memory.db``. Call
``ensure_schema(conn)`` after opening any connection to guarantee the
schema is current.

Migrations can be either:

* SQL lists: ``list[str]`` of SQL statements.
* Callables: ``function(conn)`` for data migrations beyond plain SQL.
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

type MigrationBody = list[str] | Callable[[sqlite3.Connection], None]


def _migrate_8_scoped_memory(conn: sqlite3.Connection) -> None:
    """Add scope/project/branch columns and rebuild FTS with the new columns."""
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


def _migrate_10_decision_entry_type(conn: sqlite3.Connection) -> None:
    """Relabel extraction-sourced ``insight`` rows as ``decision``.

    The observe hook used to store extracted architectural decisions under
    ``entry_type='insight'``, colliding with reflection output (which also uses
    ``insight``). New extractions use ``decision``; this migration relabels the
    historical rows.

    Guarded: only run when reflection has never run on this database. Once
    reflection has produced genuine insights, the two are indistinguishable by
    ``entry_type`` alone, so a blanket rename would corrupt them — in that case
    leave existing rows untouched and rely on the forward-path fix. The
    ``memory_entries_au`` trigger keeps the FTS shadow table in sync with the
    relabelled ``entry_type`` automatically.
    """
    reflected = conn.execute("SELECT COUNT(*) FROM reflection_watermark").fetchone()[0]
    if reflected:
        logger.info(
            "Migration 10: reflection has run (%d watermark row(s)); leaving "
            "existing 'insight' rows untouched to avoid relabelling reflective "
            "insights.",
            reflected,
        )
        return
    cursor = conn.execute(
        "UPDATE memory_entries SET entry_type = 'decision' WHERE entry_type = 'insight'"
    )
    logger.info(
        "Migration 10: relabelled %d extracted 'insight' row(s) to 'decision'.",
        cursor.rowcount,
    )


#: Migration 12 — legacy relationship types written before write-time coercion
#: landed, remapped to the canonical vocabulary. Deliberately conservative:
#: only types whose meaning maps cleanly *without flipping edge direction* get
#: a specific target (e.g. ``hosts`` is inverse-``depends_on``, so it falls to
#: the ``related_to`` catch-all instead). Anything absent here and outside the
#: canonical set becomes ``related_to``.
_LEGACY_RELATIONSHIP_REMAP: dict[str, str] = {
    "runs_on": "depends_on",
    "implements": "contributes_to",
    "integrates_with": "uses",
}

#: Migration 12 — legacy entity types (never offered by the extraction prompt)
#: remapped to the canonical vocabulary. Anything absent here and outside the
#: canonical set becomes ``unknown``.
_LEGACY_ENTITY_TYPE_REMAP: dict[str, str] = {
    "component": "concept",
    "module": "concept",
    "feature": "concept",
    "pattern": "concept",
    "process": "concept",
    "artifact": "concept",
    "reference": "concept",
    "resource": "concept",
    "system": "service",
    "infrastructure": "service",
}


def _migrate_12_canonical_graph_types(conn: sqlite3.Connection) -> None:
    """Remap legacy entity and relationship types to the canonical vocabularies.

    Relationship-type coercion only ever applied at write time, so rows written
    before it landed carry free-form types; entity types were never coerced at
    all. Remaps both via static lookups, then sweeps the remainder to the
    defaults. A relationship whose remapped form collides with an existing row
    on the ``(source, target, type)`` unique index merges into it instead
    (widening the seen window, keeping the existing row's context).
    """
    # Local import to avoid hard-coding the vocabularies twice; entities.py
    # imports nothing from this module, so there is no cycle.
    from mait_code.tools.memory.entities import (
        DEFAULT_ENTITY_TYPE,
        DEFAULT_RELATIONSHIP_TYPE,
        VALID_ENTITY_TYPES,
        VALID_RELATIONSHIP_TYPES,
    )

    rel_placeholders = ",".join("?" * len(VALID_RELATIONSHIP_TYPES))
    legacy_rels = conn.execute(
        f"""SELECT id, source_entity_id, target_entity_id, relationship_type
            FROM memory_relationships
            WHERE relationship_type NOT IN ({rel_placeholders})""",
        tuple(VALID_RELATIONSHIP_TYPES),
    ).fetchall()

    remapped = merged = 0
    for rel_id, source_id, target_id, rel_type in legacy_rels:
        new_type = _LEGACY_RELATIONSHIP_REMAP.get(rel_type, DEFAULT_RELATIONSHIP_TYPE)
        existing = conn.execute(
            """SELECT id FROM memory_relationships
               WHERE source_entity_id = ? AND target_entity_id = ?
                 AND relationship_type = ?""",
            (source_id, target_id, new_type),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE memory_relationships SET
                       first_seen = MIN(
                           first_seen,
                           (SELECT first_seen FROM memory_relationships WHERE id = ?)),
                       last_seen = MAX(
                           last_seen,
                           (SELECT last_seen FROM memory_relationships WHERE id = ?))
                   WHERE id = ?""",
                (rel_id, rel_id, existing[0]),
            )
            conn.execute("DELETE FROM memory_relationships WHERE id = ?", (rel_id,))
            merged += 1
        else:
            conn.execute(
                "UPDATE memory_relationships SET relationship_type = ? WHERE id = ?",
                (new_type, rel_id),
            )
            remapped += 1

    entity_total = 0
    for legacy_type, new_type in _LEGACY_ENTITY_TYPE_REMAP.items():
        cursor = conn.execute(
            "UPDATE memory_entities SET entity_type = ? WHERE entity_type = ?",
            (new_type, legacy_type),
        )
        entity_total += cursor.rowcount
    entity_placeholders = ",".join("?" * len(VALID_ENTITY_TYPES))
    cursor = conn.execute(
        f"""UPDATE memory_entities SET entity_type = ?
            WHERE entity_type NOT IN ({entity_placeholders})""",
        (DEFAULT_ENTITY_TYPE, *VALID_ENTITY_TYPES),
    )
    entity_total += cursor.rowcount

    logger.info(
        "Migration 12: remapped %d relationship row(s), merged %d collision(s), "
        "remapped %d entity row(s).",
        remapped,
        merged,
        entity_total,
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
    (
        9,
        "Create reflection_watermark table for idempotent reflection",
        [
            """CREATE TABLE IF NOT EXISTS reflection_watermark (
                project TEXT NOT NULL DEFAULT '',
                last_reflected_id INTEGER NOT NULL,
                last_reflected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (project)
            )""",
        ],
    ),
    (
        10,
        "Relabel extraction-sourced insight entries as decision",
        _migrate_10_decision_entry_type,
    ),
    (
        11,
        "Add supersession columns for temporal/evolving memory",
        [
            "ALTER TABLE memory_entries ADD COLUMN superseded_by INTEGER "
            "REFERENCES memory_entries(id)",
            "ALTER TABLE memory_entries ADD COLUMN superseded_at DATETIME",
            # Partial index over the rare superseded rows: keeps the default
            # `superseded_by IS NULL` filter cheap and makes history lookups fast.
            "CREATE INDEX IF NOT EXISTS idx_memory_entries_superseded "
            "ON memory_entries(superseded_by) WHERE superseded_by IS NOT NULL",
        ],
    ),
    (
        12,
        "Remap legacy entity and relationship types to canonical vocabularies",
        _migrate_12_canonical_graph_types,
    ),
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations to the database.

    Safe to call on every connection open — checks a single integer and
    returns immediately if the schema is current. Gracefully skips vec0
    migrations if the sqlite-vec extension is not loaded.

    Args:
        conn: Open memory database connection.
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
