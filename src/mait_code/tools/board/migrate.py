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
