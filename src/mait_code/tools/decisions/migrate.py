"""
Schema migration for decisions database.

Forward-only, idempotent migrations for decisions.db.
Call ensure_schema(conn) after opening any connection to guarantee
the schema is current.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "Create decisions table with FTS5 and sync triggers",
        [
            """CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                context TEXT,
                alternatives TEXT,
                consequences TEXT,
                status TEXT NOT NULL DEFAULT 'accepted',
                superseded_by INTEGER REFERENCES decisions(id),
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_decisions_project_status ON decisions(project, status)",
            """CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
                title, context, alternatives, consequences,
                content='decisions', content_rowid='id'
            )""",
            """CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
                INSERT INTO decisions_fts(rowid, title, context, alternatives, consequences)
                VALUES (new.id, new.title, new.context, new.alternatives, new.consequences);
            END""",
            """CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
                INSERT INTO decisions_fts(decisions_fts, rowid, title, context, alternatives, consequences)
                VALUES ('delete', old.id, old.title, old.context, old.alternatives, old.consequences);
            END""",
            """CREATE TRIGGER IF NOT EXISTS decisions_au AFTER UPDATE ON decisions BEGIN
                INSERT INTO decisions_fts(decisions_fts, rowid, title, context, alternatives, consequences)
                VALUES ('delete', old.id, old.title, old.context, old.alternatives, old.consequences);
                INSERT INTO decisions_fts(rowid, title, context, alternatives, consequences)
                VALUES (new.id, new.title, new.context, new.alternatives, new.consequences);
            END""",
        ],
    ),
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """
    Apply any pending migrations to the database.

    Safe to call on every connection open — checks a single integer
    and returns immediately if the schema is current.
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

    for version, description, statements in MIGRATIONS:
        if version <= current_version:
            continue

        for sql in statements:
            conn.execute(sql)

        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, description),
        )
        conn.commit()
        logger.info("Migration %d: %s", version, description)
