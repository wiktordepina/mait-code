"""CLI tool for memory search and storage."""

import argparse
import logging
import sys

from mait_code.logging import log_invocation, setup_logging

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.embeddings import embed_texts, is_available, serialize_f32
from mait_code.tools.memory.entities import (
    find_entity_by_name,
    get_entity_relationships,
    search_entities as _search_entities,
)
from mait_code.tools.memory.scoring import composite_score
from mait_code.tools.memory.search import (
    delete_entry,
    hybrid_search,
    list_entries,
    search_entries,
    vector_search_entries,
)
from mait_code.tools.memory.writer import VALID_ENTRY_TYPES
from mait_code.tools.memory.writer import store_memory as _store_memory

logger = logging.getLogger(__name__)


def cmd_search(args):
    query = " ".join(args.query)
    if not query.strip():
        logger.error("query cannot be empty")
        print("Error: query cannot be empty.", file=sys.stderr)
        sys.exit(1)

    mode = getattr(args, "mode", "hybrid")

    conn = get_connection()
    try:
        if mode == "fts":
            results = search_entries(
                conn, query, limit=args.limit * 2, entry_type=args.type
            )
            for r in results:
                r["relevance"] = 0.7
        elif mode == "vector":
            results = vector_search_entries(
                conn, query, limit=args.limit * 2, entry_type=args.type
            )
            for r in results:
                r["relevance"] = r.pop("similarity", 0.5)
        else:
            results = hybrid_search(
                conn, query, limit=args.limit * 2, entry_type=args.type
            )

        if not results:
            print(f"No memories found matching '{query}'.")
            return

        scored = []
        for r in results:
            score = composite_score(
                r["created_at"],
                r["importance"],
                relevance=r.get("relevance", 0.5),
                memory_class=r.get("memory_class"),
            )
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[: args.limit]

        print(f"Found {len(scored)} memories matching '{query}':\n")
        for score, r in scored:
            print(
                f"[#{r['id']}] ({r['entry_type']}, importance={r['importance']}, "
                f"score={score:.2f}) {r['created_at'][:10]}"
            )
            print(f"  {r['content']}")
            print()
    finally:
        conn.close()


def cmd_store(args):
    content = " ".join(args.content)
    if not content.strip():
        logger.error("content cannot be empty")
        print("Error: content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    if args.type not in VALID_ENTRY_TYPES:
        logger.error("invalid type '%s'", args.type)
        print(
            f"Error: invalid type '{args.type}'. "
            f"Valid types: {', '.join(sorted(VALID_ENTRY_TYPES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = get_connection()
    try:
        result = _store_memory(conn, content.strip(), args.type, args.importance)
        if result["action"] == "deduplicated":
            print(
                f"Memory deduplicated (updated entry #{result['id']}): {content[:80]}"
            )
        else:
            print(
                f"Memory stored (#{result['id']}): "
                f"[{args.type}, importance={args.importance}] {content[:80]}"
            )
    finally:
        conn.close()


def cmd_list(args):
    conn = get_connection()
    try:
        results = list_entries(
            conn, limit=args.limit, entry_type=args.type, since=args.since
        )
        if not results:
            print("No memories found." if args.since else "No memories stored yet.")
            return

        header = f"Recent {len(results)} memories"
        if args.since:
            header += f" (since {args.since})"
        print(f"{header}:\n")
        for r in results:
            print(
                f"[#{r['id']}] ({r['entry_type']}, importance={r['importance']}) "
                f"{r['created_at'][:10]}"
            )
            print(f"  {r['content'][:120]}")
            print()
    finally:
        conn.close()


def cmd_delete(args):
    conn = get_connection()
    try:
        if delete_entry(conn, args.id):
            print(f"Memory #{args.id} deleted.")
        else:
            logger.error("memory #%d not found", args.id)
            print(f"Error: memory #{args.id} not found.", file=sys.stderr)
            sys.exit(1)
    finally:
        conn.close()


def cmd_stats(_args):
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        if total == 0:
            print("No memories stored yet.")
            return

        by_type = conn.execute(
            "SELECT entry_type, COUNT(*) FROM memory_entries "
            "GROUP BY entry_type ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_class = conn.execute(
            "SELECT memory_class, COUNT(*) FROM memory_entries GROUP BY memory_class"
        ).fetchall()

        # Embedding stats
        try:
            embedded = conn.execute(
                "SELECT COUNT(*) FROM memory_vec"
            ).fetchone()[0]
        except Exception:
            embedded = 0

        print(f"Memory Statistics ({total} total entries)\n")
        print("By type:")
        for row in by_type:
            print(f"  {row[0]}: {row[1]}")
        print("\nBy class:")
        for row in by_class:
            print(f"  {row[0]}: {row[1]}")

        pct = round(100 * embedded / total) if total else 0
        available = "yes" if is_available() else "no"
        print(f"\nEmbeddings: {embedded}/{total} entries ({pct}%)")
        print(f"Embedding model available: {available}")
    finally:
        conn.close()


def cmd_entities(args):
    query = " ".join(args.query) if args.query else ""
    conn = get_connection()
    try:
        if not query:
            results = _search_entities(conn, "", limit=args.limit)
        else:
            results = _search_entities(conn, query, limit=args.limit)

        if not results:
            print(f"No entities found{' matching ' + repr(query) if query else ''}.")
            return

        print(
            f"Entities{' matching ' + repr(query) if query else ''} ({len(results)}):\n"
        )
        for e in results:
            rels = get_entity_relationships(conn, e["id"])
            print(
                f"[#{e['id']}] {e['name']} ({e['entity_type']}) "
                f"— {e['mention_count']} mentions, {len(rels)} relationships"
            )
    finally:
        conn.close()


def cmd_relationships(args):
    entity_name = " ".join(args.entity)
    conn = get_connection()
    try:
        entity = find_entity_by_name(conn, entity_name)
        if not entity:
            logger.error("entity '%s' not found", entity_name)
            print(f"Entity '{entity_name}' not found.", file=sys.stderr)
            sys.exit(1)

        rels = get_entity_relationships(conn, entity["id"])
        if not rels:
            print(f"No relationships found for '{entity['name']}'.")
            return

        print(f"Relationships for '{entity['name']}' ({len(rels)}):\n")
        for r in rels:
            if r["source_entity_id"] == entity["id"]:
                print(f"  → {r['relationship_type']} → {r['target_name']}")
            else:
                print(f"  ← {r['relationship_type']} ← {r['source_name']}")
            if r["context"]:
                print(f"    {r['context']}")
    finally:
        conn.close()


def _reindex_embeddings(conn):
    """Recompute all vector embeddings. Returns count or exits on failure."""
    total = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
    if total == 0:
        print("No memory entries to embed.")
        return 0

    # Clear existing embeddings
    try:
        conn.execute("DELETE FROM memory_vec")
        conn.commit()
    except Exception:
        pass  # Table may not exist

    batch_size = 64
    embedded = 0

    for offset in range(0, total, batch_size):
        rows = conn.execute(
            "SELECT id, content FROM memory_entries ORDER BY id LIMIT ? OFFSET ?",
            (batch_size, offset),
        ).fetchall()

        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]

        vectors = embed_texts(texts, prefix="search_document")
        if vectors is None:
            logger.error("embedding failed")
            print("Error: embedding failed.", file=sys.stderr)
            sys.exit(1)

        for entry_id, vec in zip(ids, vectors):
            conn.execute(
                "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
                (entry_id, serialize_f32(vec)),
            )

        conn.commit()
        embedded += len(rows)
        print(f"Embedded {embedded}/{total} entries...")

    return embedded


def cmd_reindex(_args):
    """Recompute vector embeddings for all memory entries."""
    if not is_available():
        logger.error("embedding model unavailable")
        print(
            "Error: embedding model unavailable. "
            "Ensure fastembed is installed: pip install fastembed",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = get_connection()
    try:
        embedded = _reindex_embeddings(conn)
        if embedded:
            print(f"\nDone. {embedded} embeddings stored.")
    finally:
        conn.close()


def cmd_restore(args):
    """Restore memory database from observation JSONL log files."""
    import json

    from mait_code.tools.memory.db import get_data_dir
    from mait_code.tools.memory.entities import upsert_entity, upsert_relationship
    from mait_code.tools.memory.writer import store_memory as _store

    obs_dir = get_data_dir() / "memory" / "observations"
    if not obs_dir.exists():
        logger.error("no observation logs found")
        print("No observation logs found.", file=sys.stderr)
        sys.exit(1)

    log_files = sorted(obs_dir.glob("*.jsonl"))
    if not log_files:
        logger.error("no observation log files found")
        print("No observation log files found.", file=sys.stderr)
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)

    category_to_type = {
        "facts": "fact",
        "preferences": "preference",
        "decisions": "insight",
        "bugs_fixed": "event",
    }

    total_records = 0
    total_memories = 0
    total_entities = 0
    total_relationships = 0
    errors = 0

    conn = None if dry_run else get_connection()
    try:
        for log_file in log_files:
            file_records = 0
            with open(log_file) as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("invalid JSON in %s:%d", log_file.name, line_num)
                        print(f"Warning: invalid JSON in {log_file.name}:{line_num}")
                        errors += 1
                        continue

                    extraction = record.get("extraction", {})
                    total_records += 1
                    file_records += 1

                    # Replay memory entries
                    for category, entry_type in category_to_type.items():
                        for item in extraction.get(category, []):
                            content = item.get("content", "").strip()
                            if not content:
                                continue
                            importance = item.get("importance", 5)
                            if dry_run:
                                total_memories += 1
                            else:
                                try:
                                    _store(conn, content, entry_type, importance)
                                    total_memories += 1
                                except Exception as e:
                                    logger.warning("failed to store %s: %s", entry_type, e)
                                    print(
                                        f"Warning: failed to store {entry_type}: {e}",
                                        file=sys.stderr,
                                    )
                                    errors += 1

                    # Replay entities
                    entity_ids: dict[str, int] = {}
                    for entity in extraction.get("entities", []):
                        name = entity.get("name", "").strip()
                        if not name:
                            continue
                        entity_type = entity.get("entity_type", "unknown")
                        if dry_run:
                            total_entities += 1
                        else:
                            try:
                                entity_ids[name.lower()] = upsert_entity(
                                    conn, name, entity_type
                                )
                                total_entities += 1
                            except Exception as e:
                                logger.warning("failed to upsert entity '%s': %s", name, e)
                                print(
                                    f"Warning: failed to upsert entity '{name}': {e}",
                                    file=sys.stderr,
                                )
                                errors += 1

                    # Replay relationships
                    for rel in extraction.get("relationships", []):
                        source = rel.get("source", "").strip()
                        target = rel.get("target", "").strip()
                        if not source or not target:
                            continue

                        if dry_run:
                            total_relationships += 1
                            continue

                        source_id = entity_ids.get(source.lower())
                        target_id = entity_ids.get(target.lower())
                        if source_id is None:
                            try:
                                source_id = upsert_entity(conn, source, "unknown")
                                entity_ids[source.lower()] = source_id
                            except Exception:
                                errors += 1
                                continue
                        if target_id is None:
                            try:
                                target_id = upsert_entity(conn, target, "unknown")
                                entity_ids[target.lower()] = target_id
                            except Exception:
                                errors += 1
                                continue

                        rel_type = rel.get("relationship_type", "related_to")
                        context = rel.get("context", "")
                        try:
                            upsert_relationship(
                                conn, source_id, target_id, rel_type, context
                            )
                            total_relationships += 1
                        except Exception:
                            errors += 1

            print(f"{'[dry-run] ' if dry_run else ''}{log_file.name}: {file_records} records")

        prefix = "[dry-run] " if dry_run else ""
        print(f"\n{prefix}Restore complete:")
        print(f"  Log files: {len(log_files)}")
        print(f"  Records processed: {total_records}")
        print(f"  Memories stored: {total_memories}")
        print(f"  Entities upserted: {total_entities}")
        print(f"  Relationships upserted: {total_relationships}")
        if errors:
            print(f"  Errors: {errors}")

        # Reindex embeddings after restore
        if not dry_run and is_available() and total_memories > 0:
            print("\nReindexing embeddings...")
            embedded = _reindex_embeddings(conn)
            if embedded:
                print(f"Done. {embedded} embeddings stored.")
    finally:
        if conn is not None:
            conn.close()


def cmd_reflect(args):
    """Synthesise recent observations into insights, update MEMORY.md."""
    from mait_code.tools.memory.reflect import reflect

    conn = get_connection()
    try:
        result = reflect(conn, days=args.days, min_new=args.min_new)
    finally:
        conn.close()

    if result["skipped"]:
        reason = result.get("reason", "not enough new signal")
        print(f"Reflection skipped — {reason}.")
        return

    if not result["insights"]:
        print(f"No insights generated from last {args.days} days of data.")
        return

    print(f"Generated {len(result['insights'])} insights from last {args.days} days:\n")
    for i, insight in enumerate(result["insights"], 1):
        print(f"  {i}. {insight}")
    print(f"\nStored {result['stored']} insights to memory database.")

    if result["memory_diff"]:
        print(f"\n{result['memory_diff']}")
        print("\nReview and apply these changes manually or approve when prompted.")


@log_invocation(name="mc-tool-memory")
def main():
    setup_logging()
    parser = argparse.ArgumentParser(prog="mc-tool-memory", description="Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search memories")
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--type", choices=sorted(VALID_ENTRY_TYPES), default=None)
    p_search.add_argument(
        "--mode",
        choices=["hybrid", "fts", "vector"],
        default="hybrid",
        help="Search mode: hybrid (default), fts (keyword only), vector (semantic only)",
    )
    p_search.set_defaults(func=cmd_search)

    # store
    p_store = sub.add_parser("store", help="Store a memory")
    p_store.add_argument("content", nargs="+", help="Memory content")
    p_store.add_argument("--type", choices=sorted(VALID_ENTRY_TYPES), default="fact")
    p_store.add_argument("--importance", type=int, default=5, choices=range(1, 11))
    p_store.set_defaults(func=cmd_store)

    # list
    p_list = sub.add_parser("list", help="List recent memories")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--type", choices=sorted(VALID_ENTRY_TYPES), default=None)
    p_list.add_argument(
        "--since",
        default=None,
        help="Time period filter (e.g. 24h, 7d, 1w)",
    )
    p_list.set_defaults(func=cmd_list)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a memory by ID")
    p_delete.add_argument("id", type=int, help="Memory entry ID")
    p_delete.set_defaults(func=cmd_delete)

    # stats
    p_stats = sub.add_parser("stats", help="Show memory statistics")
    p_stats.set_defaults(func=cmd_stats)

    # entities
    p_entities = sub.add_parser("entities", help="Search entities")
    p_entities.add_argument("query", nargs="*", help="Search query (optional)")
    p_entities.add_argument("--limit", type=int, default=20)
    p_entities.set_defaults(func=cmd_entities)

    # relationships
    p_rels = sub.add_parser("relationships", help="Show relationships for an entity")
    p_rels.add_argument("entity", nargs="+", help="Entity name")
    p_rels.set_defaults(func=cmd_relationships)

    # reindex
    p_reindex = sub.add_parser(
        "reindex", help="Recompute vector embeddings for all memory entries"
    )
    p_reindex.set_defaults(func=cmd_reindex)

    # restore
    p_restore = sub.add_parser(
        "restore",
        help="Restore memory database from observation JSONL log files",
    )
    p_restore.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be restored without writing to the database",
    )
    p_restore.set_defaults(func=cmd_restore)

    # reflect
    p_reflect = sub.add_parser(
        "reflect", help="Synthesise recent observations into insights"
    )
    p_reflect.add_argument(
        "--days", type=int, default=7, help="Days of history to reflect on"
    )
    p_reflect.add_argument(
        "--min-new",
        type=int,
        default=3,
        help="Minimum new observations to trigger reflection",
    )
    p_reflect.set_defaults(func=cmd_reflect)

    args = parser.parse_args()
    args.func(args)
