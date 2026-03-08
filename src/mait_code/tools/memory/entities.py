"""Entity and relationship CRUD operations for the memory knowledge graph."""

import sqlite3


def upsert_entity(conn: sqlite3.Connection, name: str, entity_type: str) -> int:
    """Insert or update an entity. Returns the entity id."""
    cursor = conn.execute(
        """INSERT INTO memory_entities (name, entity_type)
           VALUES (?, ?)
           ON CONFLICT(name) DO UPDATE SET
               mention_count = mention_count + 1,
               last_seen = CURRENT_TIMESTAMP,
               entity_type = CASE
                   WHEN memory_entities.entity_type = 'unknown' THEN excluded.entity_type
                   ELSE memory_entities.entity_type
               END
           RETURNING id""",
        (name.strip(), entity_type),
    )
    row = cursor.fetchone()
    conn.commit()
    return row[0]


def upsert_relationship(
    conn: sqlite3.Connection,
    source_entity_id: int,
    target_entity_id: int,
    relationship_type: str,
    context: str,
) -> int:
    """Insert or update a relationship. Returns the relationship id."""
    cursor = conn.execute(
        """INSERT INTO memory_relationships
               (source_entity_id, target_entity_id, relationship_type, context)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(source_entity_id, target_entity_id, relationship_type) DO UPDATE SET
               last_seen = CURRENT_TIMESTAMP,
               context = CASE
                   WHEN excluded.context != memory_relationships.context
                   THEN excluded.context
                   ELSE memory_relationships.context
               END
           RETURNING id""",
        (source_entity_id, target_entity_id, relationship_type, context),
    )
    row = cursor.fetchone()
    conn.commit()
    return row[0]


def find_entity_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    """Look up an entity by name (case-insensitive)."""
    cursor = conn.execute(
        """SELECT id, name, entity_type, first_seen, last_seen, mention_count
           FROM memory_entities WHERE name = ? COLLATE NOCASE""",
        (name,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "entity_type": row[2],
        "first_seen": row[3],
        "last_seen": row[4],
        "mention_count": row[5],
    }


def get_entity_relationships(conn: sqlite3.Connection, entity_id: int) -> list[dict]:
    """Get all relationships involving an entity (as source or target)."""
    cursor = conn.execute(
        """SELECT r.id, r.source_entity_id, s.name AS source_name,
                  r.target_entity_id, t.name AS target_name,
                  r.relationship_type, r.context, r.first_seen, r.last_seen
           FROM memory_relationships r
           JOIN memory_entities s ON r.source_entity_id = s.id
           JOIN memory_entities t ON r.target_entity_id = t.id
           WHERE r.source_entity_id = ? OR r.target_entity_id = ?""",
        (entity_id, entity_id),
    )
    return [
        {
            "id": row[0],
            "source_entity_id": row[1],
            "source_name": row[2],
            "target_entity_id": row[3],
            "target_name": row[4],
            "relationship_type": row[5],
            "context": row[6],
            "first_seen": row[7],
            "last_seen": row[8],
        }
        for row in cursor.fetchall()
    ]


def search_entities(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[dict]:
    """Search entities by name using LIKE."""
    cursor = conn.execute(
        """SELECT id, name, entity_type, first_seen, last_seen, mention_count
           FROM memory_entities
           WHERE name LIKE ?
           ORDER BY mention_count DESC, last_seen DESC
           LIMIT ?""",
        (f"%{query}%", limit),
    )
    return [
        {
            "id": row[0],
            "name": row[1],
            "entity_type": row[2],
            "first_seen": row[3],
            "last_seen": row[4],
            "mention_count": row[5],
        }
        for row in cursor.fetchall()
    ]
