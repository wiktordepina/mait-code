"""Bridge extraction results to memory.db and daily observation logs."""

import json
import logging
from datetime import datetime, timezone

from mait_code.hooks.observe.scope import resolve_scope
from mait_code.tools.memory.db import connection, get_data_dir
from mait_code.tools.memory.entities import (
    DEFAULT_ENTITY_TYPE,
    DEFAULT_RELATIONSHIP_TYPE,
    VALID_ENTITY_TYPES,
    VALID_RELATIONSHIP_TYPES,
    upsert_entity,
    upsert_relationship,
)
from mait_code.tools.memory.writer import store_memory

logger = logging.getLogger(__name__)

CATEGORY_TO_TYPE = {
    "facts": "fact",
    "preferences": "preference",
    "decisions": "decision",
    "procedures": "procedure",
    "bugs_fixed": "event",
}


def write_raw_extraction(
    extraction: dict,
    trigger: str,
    *,
    project: str | None = None,
    branch: str | None = None,
    source: str | None = None,
) -> None:
    """Append an extraction record to the day's JSONL log file.

    Args:
        extraction: Parsed extraction dict returned by the LLM.
        trigger: The hook trigger name (e.g. ``"precompact"``).
        project: Project identifier captured from the transcript.
        branch: Branch name captured from the transcript.
        source: Provenance for the stored memories (see :func:`store_extraction`).
            Recorded only when set, so ``restore`` can carry it back.
    """
    data_dir = get_data_dir()
    obs_dir = data_dir / "memory" / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = obs_dir / f"{today}.jsonl"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "project": project,
        "branch": branch,
        "extraction": extraction,
    }
    if source is not None:
        record["source"] = source
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def store_extraction(
    extraction: dict,
    *,
    project: str | None = None,
    branch: str | None = None,
    source: str | None = None,
) -> dict[str, dict[str, int]]:
    """Store extracted facts, preferences, decisions, and bugs to ``memory.db``.

    A failed write is logged and counted, never raised, so one bad item can't
    lose the rest of the window.

    Args:
        extraction: Parsed extraction dict with category keys.
        project: Project identifier used to resolve scope and assign entries.
        branch: Branch name used to resolve scope and assign entries.
        source: Provenance recorded on new entries (e.g. ``"job"``); ``None``
            for a session's own hook.

    Returns:
        Per category in :data:`CATEGORY_TO_TYPE`, how many items were
        ``created``, ``deduplicated`` or ``failed``. Items with blank content
        are skipped and not counted.
    """
    counts = {
        category: {"created": 0, "deduplicated": 0, "failed": 0}
        for category in CATEGORY_TO_TYPE
    }
    with connection() as conn:
        for category, entry_type in CATEGORY_TO_TYPE.items():
            for item in extraction.get(category, []):
                content = item.get("content", "").strip()
                if not content:
                    continue
                importance = item.get("importance", 5)
                scope = resolve_scope(item, category, project, branch)
                try:
                    result = store_memory(
                        conn,
                        content,
                        entry_type,
                        importance,
                        scope=scope,
                        project=project if scope != "global" else None,
                        branch=branch if scope == "branch" else None,
                        source=source,
                    )
                    counts[category][result["action"]] += 1
                except Exception as e:
                    logger.warning("failed to store %s: %s", entry_type, e)
                    counts[category]["failed"] += 1
    return counts


def store_entities_and_relationships(extraction: dict) -> None:
    """Upsert entities and relationships from an extraction dict.

    Entities referenced by relationships but absent from the ``entities``
    list are auto-created with type ``"unknown"``.

    Args:
        extraction: Parsed extraction dict with ``entities`` and
            ``relationships`` keys.
    """
    with connection() as conn:
        # Upsert entities and build name->id map
        entity_ids: dict[str, int] = {}
        for entity in extraction.get("entities", []):
            name = entity.get("name", "").strip()
            if not name:
                continue
            entity_type = entity.get("entity_type", DEFAULT_ENTITY_TYPE)
            if entity_type not in VALID_ENTITY_TYPES:
                logger.debug(
                    "coercing unknown entity type '%s' to '%s'",
                    entity_type,
                    DEFAULT_ENTITY_TYPE,
                )
                entity_type = DEFAULT_ENTITY_TYPE
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

            rel_type = rel.get("relationship_type", DEFAULT_RELATIONSHIP_TYPE)
            if rel_type not in VALID_RELATIONSHIP_TYPES:
                logger.debug(
                    "coercing unknown relationship type '%s' to '%s'",
                    rel_type,
                    DEFAULT_RELATIONSHIP_TYPE,
                )
                rel_type = DEFAULT_RELATIONSHIP_TYPE
            context = rel.get("context", "")
            try:
                upsert_relationship(conn, source_id, target_id, rel_type, context)
            except Exception as e:
                logger.warning("failed to upsert relationship: %s", e)


def confine_extraction(extraction: dict) -> dict:
    """Cap what an extraction from prepared text may write.

    Text handed in by another program (a job digest) carries no user voice
    and may carry untrusted content, so its reach is limited: the
    ``preferences`` category is dropped, and every memory item's scope is
    pinned to ``branch`` (when it asked for that) or ``project`` — never
    ``global``. Pinning the scope in the dict itself, before it is logged,
    means ``restore`` replays the same caps.

    Args:
        extraction: Parsed extraction dict returned by the LLM.

    Returns:
        A new extraction dict with the caps applied; the input is not modified.
    """
    confined = {k: v for k, v in extraction.items() if k != "preferences"}
    for category in CATEGORY_TO_TYPE:
        if category == "preferences" or category not in confined:
            continue
        items = []
        for item in confined[category]:
            asked = str(item.get("scope", "")).strip().lower()
            items.append(
                {**item, "scope": "branch" if asked == "branch" else "project"}
            )
        confined[category] = items
    return confined


def record_extraction(
    extraction: dict,
    trigger: str,
    *,
    project: str | None = None,
    branch: str | None = None,
    source: str | None = None,
) -> dict[str, dict[str, int]]:
    """Log an extraction and store its memories, entities and relationships.

    The shared tail of every extraction path — the observe hook and
    ``mc-tool-memory observe`` — so the two can't drift apart.

    Args:
        extraction: Parsed extraction dict returned by the LLM.
        trigger: What ran the extraction, recorded in the raw log.
        project: Project the memories belong to.
        branch: Branch for branch-scoped memories.
        source: Provenance recorded on new entries; ``None`` for the hook.

    Returns:
        The per-category counts from :func:`store_extraction`.
    """
    write_raw_extraction(
        extraction, trigger, project=project, branch=branch, source=source
    )
    counts = store_extraction(extraction, project=project, branch=branch, source=source)
    store_entities_and_relationships(extraction)
    return counts
