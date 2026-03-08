"""Bridge extraction results to memory.db and daily observation logs."""

import json
import logging
from datetime import datetime, timezone

from mait_code.tools.memory.db import get_connection, get_data_dir
from mait_code.tools.memory.entities import upsert_entity, upsert_relationship
from mait_code.tools.memory.writer import store_memory

logger = logging.getLogger(__name__)

CATEGORY_TO_TYPE = {
    "facts": "fact",
    "preferences": "preference",
    "decisions": "insight",
    "bugs_fixed": "event",
}


def write_raw_extraction(extraction: dict, trigger: str) -> None:
    """Append extraction to daily JSONL log file."""
    data_dir = get_data_dir()
    obs_dir = data_dir / "memory" / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = obs_dir / f"{today}.jsonl"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "extraction": extraction,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def store_extraction(extraction: dict) -> None:
    """Store extracted facts, preferences, decisions, bugs to memory.db."""
    conn = get_connection()
    try:
        for category, entry_type in CATEGORY_TO_TYPE.items():
            for item in extraction.get(category, []):
                content = item.get("content", "").strip()
                if not content:
                    continue
                importance = item.get("importance", 5)
                try:
                    store_memory(conn, content, entry_type, importance)
                except Exception as e:
                    logger.warning("failed to store %s: %s", entry_type, e)
    finally:
        conn.close()


def store_entities_and_relationships(extraction: dict) -> None:
    """Upsert entities and relationships from extraction."""
    conn = get_connection()
    try:
        # Upsert entities and build name->id map
        entity_ids: dict[str, int] = {}
        for entity in extraction.get("entities", []):
            name = entity.get("name", "").strip()
            if not name:
                continue
            entity_type = entity.get("entity_type", "unknown")
            try:
                entity_ids[name.lower()] = upsert_entity(conn, name, entity_type)
            except Exception as e:
                logger.warning("failed to upsert entity '%s': %s", name, e)

        # Upsert relationships
        for rel in extraction.get("relationships", []):
            source = rel.get("source", "").strip()
            target = rel.get("target", "").strip()
            if not source or not target:
                continue

            source_id = entity_ids.get(source.lower())
            target_id = entity_ids.get(target.lower())

            # Auto-create entities referenced in relationships but not in entities list
            if source_id is None:
                try:
                    source_id = upsert_entity(conn, source, "unknown")
                    entity_ids[source.lower()] = source_id
                except Exception as e:
                    logger.warning("failed to create entity '%s': %s", source, e)
                    continue
            if target_id is None:
                try:
                    target_id = upsert_entity(conn, target, "unknown")
                    entity_ids[target.lower()] = target_id
                except Exception as e:
                    logger.warning("failed to create entity '%s': %s", target, e)
                    continue

            rel_type = rel.get("relationship_type", "related_to")
            context = rel.get("context", "")
            try:
                upsert_relationship(conn, source_id, target_id, rel_type, context)
            except Exception as e:
                logger.warning("failed to upsert relationship: %s", e)
    finally:
        conn.close()
