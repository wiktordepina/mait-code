"""
Schema migration for tasks database.

Forward-only, idempotent migrations for tasks.db.
Call ensure_schema(conn) after opening any connection to guarantee
the schema is current.
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

type MigrationBody = list[str] | Callable[[sqlite3.Connection], None]


def _migrate_3_drop_projects(conn: sqlite3.Connection) -> None:
    """Remove projects table and FK constraint from tasks."""
    conn.execute("ALTER TABLE tasks RENAME TO tasks_old")
    conn.execute(
        """CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            title TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            completed_at TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO tasks (id, project, title, priority, status, created_at, completed_at)
           SELECT id, project, title, priority, status, created_at, completed_at
           FROM tasks_old"""
    )
    conn.execute("DROP TABLE tasks_old")
    conn.execute("CREATE INDEX idx_tasks_project_status ON tasks(project, status)")
    conn.execute("DROP TABLE IF EXISTS projects")


MIGRATIONS: list[tuple[int, str, MigrationBody]] = [
    (
        1,
        "Create tasks table with indexes",
        [
            """CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                completed_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project, status)",
        ],
    ),
    (
        2,
        "Create projects table and recreate tasks with foreign key",
        [
            """CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                github_url TEXT,
                added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            "DROP TABLE IF EXISTS tasks",
            "DROP INDEX IF EXISTS idx_tasks_project_status",
            """CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL REFERENCES projects(name),
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                completed_at TEXT
            )""",
            "CREATE INDEX idx_tasks_project_status ON tasks(project, status)",
        ],
    ),
    (
        3,
        "Remove projects table and FK constraint",
        _migrate_3_drop_projects,
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
