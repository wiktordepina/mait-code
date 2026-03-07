"""
Schema migration for reminders database.

Forward-only, idempotent migrations for reminders.db.
Call ensure_schema(conn) after opening any connection to guarantee
the schema is current.
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

type MigrationBody = list[str] | Callable[[sqlite3.Connection], None]

MIGRATIONS: list[tuple[int, str, MigrationBody]] = [
    (
        1,
        "Create reminders table with indexes",
        [
            """CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                what TEXT NOT NULL,
                due TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                dismissed INTEGER NOT NULL DEFAULT 0,
                dismissed_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due)",
            "CREATE INDEX IF NOT EXISTS idx_reminders_dismissed ON reminders(dismissed)",
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
