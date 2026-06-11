"""Entity and relationship CRUD operations for the memory knowledge graph."""

import sqlite3

# Canonical relationship vocabulary. The extraction prompt is built from this
# tuple, and extracted relationships are coerced to it on write (see
# ``mait_code.hooks.observe.storage``). Keep the ordering stable — it is what
# the prompt presents to the model.
RELATIONSHIP_TYPES: tuple[str, ...] = (
    "uses",
    "owns",
    "contributes_to",
    "depends_on",
    "manages",
    "related_to",
)
VALID_RELATIONSHIP_TYPES: frozenset[str] = frozenset(RELATIONSHIP_TYPES)
DEFAULT_RELATIONSHIP_TYPE: str = "related_to"

# Canonical entity vocabulary, mirroring the relationship pattern. The
# extraction prompt enum is built from this tuple; types outside it are
# coerced to ``DEFAULT_ENTITY_TYPE`` on write. ``unknown`` is the write-time
# fallback (and the type given to entities auto-created from relationship
# endpoints) — deliberately not offered to the model, so it stays out of
# ENTITY_TYPES but counts as valid.
ENTITY_TYPES: tuple[str, ...] = (
    "person",
    "project",
    "tool",
    "service",
    "concept",
    "org",
)
DEFAULT_ENTITY_TYPE: str = "unknown"
VALID_ENTITY_TYPES: frozenset[str] = frozenset(ENTITY_TYPES) | {DEFAULT_ENTITY_TYPE}


def upsert_entity(conn: sqlite3.Connection, name: str, entity_type: str) -> int:
    """Insert or update an entity by name and return its id.

    On conflict, increments ``mention_count``, refreshes ``last_seen``, and
    upgrades ``entity_type`` from ``"unknown"`` if a more specific type is
    provided.

    Args:
        conn: Open memory database connection.
        name: Entity name (case-insensitive unique key).
        entity_type: Entity type (e.g. ``"person"``, ``"project"``).

    Returns:
        The entity's primary-key id.
    """
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
    """Insert or update a relationship and return its id.

    On conflict (same source/target/type), refreshes ``last_seen`` and
    updates ``context`` when the new value differs from the stored one.

    Args:
        conn: Open memory database connection.
        source_entity_id: Source entity id.
        target_entity_id: Target entity id.
        relationship_type: Relationship label (e.g. ``"uses"``).
        context: Free-text context describing the relationship.

    Returns:
        The relationship's primary-key id.
    """
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
    """Look up an entity by name (case-insensitive).

    Args:
        conn: Open memory database connection.
        name: Entity name to find.

    Returns:
        A dict with entity fields, or ``None`` if no match.
    """
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
    """Return all relationships involving an entity (as source or target).

    Args:
        conn: Open memory database connection.
        entity_id: Entity id to look up.

    Returns:
        A list of relationship dicts, each including the source and target
        entity names.
    """
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
    """Search entities by name using a ``LIKE`` substring match.

    Args:
        conn: Open memory database connection.
        query: Substring to match against entity names.
        limit: Maximum number of results to return.

    Returns:
        A list of entity dicts ordered by ``mention_count`` descending,
        then ``last_seen`` descending.
    """
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


def list_graph_entities(
    conn: sqlite3.Connection,
    query: str = "",
    *,
    min_mentions: int = 1,
    require_relationship: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """List entities with their relationship degree, for graph surfaces.

    The graph explorer's entity list: every entity matching *query*, each
    carrying a ``degree`` (the number of relationships it participates in)
    so callers can filter or weight by connectedness. The default filters
    are permissive; pass ``min_mentions=2`` and ``require_relationship=True``
    for the noise-hiding defaults the explorer uses (84% of entities are
    single-mention tail).

    Args:
        conn: Open memory database connection.
        query: Substring to match against entity names ("" matches all).
        min_mentions: Keep entities mentioned at least this many times.
        require_relationship: Drop entities with no relationships (degree 0).
        limit: Maximum number of results, or ``None`` for all.

    Returns:
        A list of entity dicts (including ``degree``), ordered by
        ``mention_count`` descending, then ``last_seen`` descending, then id
        — a deterministic order for rendering and tests.
    """
    cursor = conn.execute(
        """SELECT e.id, e.name, e.entity_type, e.first_seen, e.last_seen,
                  e.mention_count,
                  (SELECT COUNT(*) FROM memory_relationships r
                    WHERE r.source_entity_id = e.id
                       OR r.target_entity_id = e.id) AS degree
           FROM memory_entities e
           WHERE e.name LIKE ?
             AND e.mention_count >= ?
             AND (? = 0 OR EXISTS (
                 SELECT 1 FROM memory_relationships r
                  WHERE r.source_entity_id = e.id
                     OR r.target_entity_id = e.id))
           ORDER BY e.mention_count DESC, e.last_seen DESC, e.id
           LIMIT ?""",
        (
            f"%{query}%",
            min_mentions,
            1 if require_relationship else 0,
            -1 if limit is None else limit,
        ),
    )
    return [
        {
            "id": row[0],
            "name": row[1],
            "entity_type": row[2],
            "first_seen": row[3],
            "last_seen": row[4],
            "mention_count": row[5],
            "degree": row[6],
        }
        for row in cursor.fetchall()
    ]


def get_ego_graph(conn: sqlite3.Connection, name: str) -> dict | None:
    """The 1-hop neighbourhood of an entity: its node, neighbours, and edges.

    The graph explorer's centre query. Both orderings are deterministic
    (neighbours by mention count then name; relationships with the centre's
    own edges first, then by source/type/target) so renders and snapshot
    tests are stable for a given database state.

    Args:
        conn: Open memory database connection.
        name: Centre entity name (case-insensitive).

    Returns:
        A dict with ``centre`` (the entity's fields), ``entities`` (centre
        first, then neighbours), and ``relationships`` (every edge incident
        to the centre, with source/target names) — or ``None`` if no entity
        matches *name*.
    """
    centre = find_entity_by_name(conn, name)
    if centre is None:
        return None

    relationships = get_entity_relationships(conn, centre["id"])
    relationships.sort(
        key=lambda r: (
            r["source_entity_id"] != centre["id"],
            r["source_name"].casefold(),
            r["relationship_type"],
            r["target_name"].casefold(),
        )
    )

    neighbour_ids = sorted(
        (
            {r["source_entity_id"] for r in relationships}
            | {r["target_entity_id"] for r in relationships}
        )
        - {centre["id"]}
    )
    entities = [centre]
    if neighbour_ids:
        marks = ",".join("?" * len(neighbour_ids))
        cursor = conn.execute(
            f"""SELECT id, name, entity_type, first_seen, last_seen, mention_count
                FROM memory_entities
                WHERE id IN ({marks})
                ORDER BY mention_count DESC, name COLLATE NOCASE, id""",
            neighbour_ids,
        )
        entities.extend(
            {
                "id": row[0],
                "name": row[1],
                "entity_type": row[2],
                "first_seen": row[3],
                "last_seen": row[4],
                "mention_count": row[5],
            }
            for row in cursor.fetchall()
        )

    return {"centre": centre, "entities": entities, "relationships": relationships}


def merge_entities(
    conn: sqlite3.Connection, source_name: str, target_name: str
) -> dict:
    """Merge one entity into another, repointing its relationships.

    Aliases accumulate in the graph (e.g. ``"User"`` alongside the user's real
    name) and split what should be one node. Merging folds the source entity
    into the target: relationships are repointed (deduplicating against the
    target's existing edges on the ``(source, target, type)`` unique index),
    mention counts are summed, the seen window widens to span both, the
    target's type is upgraded from ``"unknown"`` if the source's is more
    specific, and the source entity is deleted. Edges directly between the
    two (which would become self-loops) are dropped.

    Args:
        conn: Open memory database connection.
        source_name: Name of the entity to fold in (case-insensitive).
        target_name: Name of the surviving entity (case-insensitive).

    Returns:
        A summary dict: ``target`` (the surviving entity's fields, post-merge),
        ``relationships_repointed``, ``relationships_deduplicated``, and
        ``self_loops_dropped``.

    Raises:
        ValueError: If either entity does not exist, or both names resolve to
            the same entity.
    """
    source = find_entity_by_name(conn, source_name)
    if source is None:
        raise ValueError(f"entity '{source_name}' not found")
    target = find_entity_by_name(conn, target_name)
    if target is None:
        raise ValueError(f"entity '{target_name}' not found")
    if source["id"] == target["id"]:
        raise ValueError(f"'{source_name}' and '{target_name}' are the same entity")

    src_id, dst_id = source["id"], target["id"]
    repointed = deduplicated = self_loops = 0

    # Drop edges between the pair — they would become self-loops.
    cursor = conn.execute(
        """DELETE FROM memory_relationships
           WHERE (source_entity_id = ? AND target_entity_id = ?)
              OR (source_entity_id = ? AND target_entity_id = ?)""",
        (src_id, dst_id, dst_id, src_id),
    )
    self_loops = cursor.rowcount

    # Repoint the source's remaining edges one by one: an edge whose repointed
    # form already exists on the target merges into it (widening the seen
    # window) instead of violating the unique index.
    for rel_id, s, t, rel_type in conn.execute(
        """SELECT id, source_entity_id, target_entity_id, relationship_type
           FROM memory_relationships
           WHERE source_entity_id = ? OR target_entity_id = ?""",
        (src_id, src_id),
    ).fetchall():
        new_s = dst_id if s == src_id else s
        new_t = dst_id if t == src_id else t
        existing = conn.execute(
            """SELECT id FROM memory_relationships
               WHERE source_entity_id = ? AND target_entity_id = ?
                 AND relationship_type = ?""",
            (new_s, new_t, rel_type),
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
            deduplicated += 1
        else:
            conn.execute(
                """UPDATE memory_relationships
                   SET source_entity_id = ?, target_entity_id = ?
                   WHERE id = ?""",
                (new_s, new_t, rel_id),
            )
            repointed += 1

    conn.execute(
        """UPDATE memory_entities SET
               mention_count = mention_count + ?,
               first_seen = MIN(first_seen, ?),
               last_seen = MAX(last_seen, ?),
               entity_type = CASE
                   WHEN entity_type = 'unknown' THEN ?
                   ELSE entity_type
               END
           WHERE id = ?""",
        (
            source["mention_count"],
            source["first_seen"],
            source["last_seen"],
            source["entity_type"],
            dst_id,
        ),
    )
    conn.execute("DELETE FROM memory_entities WHERE id = ?", (src_id,))
    conn.commit()

    merged = find_entity_by_name(conn, target["name"])
    return {
        "target": merged,
        "relationships_repointed": repointed,
        "relationships_deduplicated": deduplicated,
        "self_loops_dropped": self_loops,
    }
