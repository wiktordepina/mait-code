"""Schema migration for the board database.

Forward-only, idempotent migrations for ``board.db``. Call
``ensure_schema(conn)`` after opening any connection to guarantee the schema is
current.
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

type MigrationBody = list[str] | Callable[[sqlite3.Connection], None]

MIGRATIONS: list[tuple[int, str, MigrationBody]] = [
    (
        1,
        "Create cards and card_comments tables with indexes",
        [
            """CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                acceptance_criteria TEXT,
                status TEXT NOT NULL DEFAULT 'backlog',
                priority TEXT NOT NULL DEFAULT 'medium',
                completion_summary TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                completed_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_cards_project_status ON cards(project, status)",
            """CREATE TABLE IF NOT EXISTS card_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                author TEXT NOT NULL DEFAULT 'me',
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_card_comments_card ON card_comments(card_id)",
        ],
    ),
    (
        2,
        "Add card_tags; migrate blocked cards to refined + a 'blocked' tag",
        [
            """CREATE TABLE IF NOT EXISTS card_tags (
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                UNIQUE(card_id, tag)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_card_tags_tag ON card_tags(tag)",
            # Data migration: 'blocked' is no longer a valid status. Tag each
            # blocked card, then move it to refined (its pre-block column was
            # never stored, so refined matches the old unblock behaviour). The
            # 'blocked' literal is hardcoded, not imported from columns — a
            # migration is a frozen snapshot and must not drift when the
            # constants later change.
            "INSERT OR IGNORE INTO card_tags (card_id, tag) "
            "SELECT id, 'blocked' FROM cards WHERE status = 'blocked'",
            "UPDATE cards SET status = 'refined' WHERE status = 'blocked'",
        ],
    ),
    (
        3,
        "Add card_references for ordered label→value links on cards",
        [
            """CREATE TABLE IF NOT EXISTS card_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                label TEXT NOT NULL,
                value TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_card_references_card "
            "ON card_references(card_id)",
        ],
    ),
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations to the database.

    Safe to call on every connection open — checks a single integer and returns
    immediately if the schema is current.

    Args:
        conn: Open board database connection.
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

        if callable(body):
            body(conn)
        else:
            for sql in body:
                conn.execute(sql)

        conn.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (version, description),
        )
        conn.commit()
        logger.info("Migration %d: %s", version, description)
