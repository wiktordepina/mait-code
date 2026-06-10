"""CLI tool for memory search and storage."""

import argparse
import logging
import sys

from mait_code import config
from mait_code.context import get_context
from mait_code.logging import log_invocation, setup_logging

from mait_code.tools.memory.db import connection
from mait_code.tools.memory.embeddings import (
    check_dimension_match,
    embed_texts,
    is_available,
    serialize_f32,
)
from mait_code.tools.memory.embeddings import (
    _get_provider_name as _embedding_provider_name,
)
from mait_code.tools.memory.entities import (
    find_entity_by_name,
    get_entity_relationships,
    search_entities as _search_entities,
)
from mait_code.tools.memory.scoring import composite_score
from mait_code.tools.memory.stats import collect_stats
from mait_code.tools.memory.search import (
    delete_entry,
    hybrid_search,
    list_entries,
    search_entries,
    vector_search_entries,
)
from mait_code.tools.memory.writer import VALID_ENTRY_TYPES
from mait_code.tools.memory.writer import store_memory as _store_memory
from mait_code.tools.memory.writer import supersede_memory as _supersede_memory

logger = logging.getLogger(__name__)

VALID_SCOPES = {"global", "project", "branch"}


def _resolve_context(args) -> dict:
    """Resolve project/branch/scope from CLI args + auto-detection."""
    ctx = get_context()
    project = getattr(args, "project", None) or ctx["project"]
    branch = getattr(args, "branch", None) or ctx["branch"]
    scope_filter = getattr(args, "scope", None)

    # --scope all means no filtering
    if scope_filter == "all":
        project = None
        branch = None
        scope_filter = None

    return {
        "project": project,
        "branch": branch,
        "scope_filter": scope_filter,
    }


def _format_scope_label(r: dict) -> str:
    """Format scope info for display."""
    scope = r.get("scope", "global")
    project = r.get("project")
    branch = r.get("branch")
    if scope == "global":
        return "global"
    if scope == "branch" and branch:
        return f"{project}:{branch}"
    if project:
        return f"{project}"
    return scope


def cmd_search(args):
    query = " ".join(args.query)
    if not query.strip():
        logger.warning("query cannot be empty")
        print("Error: query cannot be empty.", file=sys.stderr)
        sys.exit(1)

    mode = getattr(args, "mode", "hybrid")
    ctx = _resolve_context(args)
    project = ctx["project"]
    branch = ctx["branch"]

    with connection() as conn:
        search_kwargs = dict(
            limit=args.limit * 2,
            entry_type=args.type,
            project=project,
            branch=branch,
        )
        if mode == "fts":
            results = search_entries(conn, query, **search_kwargs)
            for r in results:
                r["relevance"] = 0.7
        elif mode == "vector":
            results = vector_search_entries(conn, query, **search_kwargs)
            for r in results:
                r["relevance"] = r.pop("similarity", 0.5)
        else:
            results = hybrid_search(conn, query, **search_kwargs)

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
                entry_scope=r.get("scope"),
                entry_project=r.get("project"),
                entry_branch=r.get("branch"),
                query_project=project,
                query_branch=branch,
            )
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[: args.limit]

        print(f"Found {len(scored)} memories matching '{query}':\n")
        for score, r in scored:
            scope_label = _format_scope_label(r)
            print(
                f"[#{r['id']}] ({r['entry_type']}, importance={r['importance']}, "
                f"scope={scope_label}, score={score:.2f}) {r['created_at'][:10]}"
            )
            print(f"  {r['content']}")
            print()


def cmd_store(args):
    content = " ".join(args.content)
    if not content.strip():
        logger.warning("content cannot be empty")
        print("Error: content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    if args.type not in VALID_ENTRY_TYPES:
        logger.warning("invalid type '%s'", args.type)
        print(
            f"Error: invalid type '{args.type}'. "
            f"Valid types: {', '.join(sorted(VALID_ENTRY_TYPES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    ctx = _resolve_context(args)
    project = ctx["project"]
    branch = ctx["branch"]

    # Determine scope
    scope = getattr(args, "scope", None)
    if scope and scope in VALID_SCOPES:
        pass
    elif branch:
        scope = "branch"
    elif project:
        scope = "project"
    else:
        scope = "global"

    # Clear project/branch for global scope
    store_project = project if scope != "global" else None
    store_branch = branch if scope == "branch" else None

    with connection() as conn:
        result = _store_memory(
            conn,
            content.strip(),
            args.type,
            args.importance,
            scope=scope,
            project=store_project,
            branch=store_branch,
        )
        scope_label = _format_scope_label(result)
        if result["action"] == "deduplicated":
            print(
                f"Memory deduplicated (updated entry #{result['id']}): {content[:80]}"
            )
        else:
            print(
                f"Memory stored (#{result['id']}): "
                f"[{args.type}, importance={args.importance}, "
                f"scope={scope_label}] {content[:80]}"
            )

        conflicts = result.get("potential_conflicts") or []
        if conflicts:
            print(
                f"\n⚠ This may contradict {len(conflicts)} existing "
                f"{'entry' if len(conflicts) == 1 else 'entries'}:"
            )
            for c in conflicts:
                print(
                    f"  [#{c['id']}] (similarity {c['similarity']:.2f}) {c['content'][:80]}"
                )
            print(
                "  To replace one with the new entry: "
                f'mc-tool-memory supersede <old_id> "{content[:48]}…"'
            )


def cmd_supersede(args):
    content = " ".join(args.content)
    if not content.strip():
        logger.warning("content cannot be empty")
        print("Error: content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    with connection() as conn:
        result = _supersede_memory(
            conn,
            args.old_id,
            content.strip(),
            importance=args.importance,
        )
        if result["action"] == "not_found":
            logger.warning("memory #%d not found", args.old_id)
            print(f"Error: memory #{args.old_id} not found.", file=sys.stderr)
            sys.exit(1)
        print(
            f"Memory #{result['old_id']} superseded by #{result['id']}: {content[:80]}"
        )


def cmd_list(args):
    ctx = _resolve_context(args)

    with connection() as conn:
        results = list_entries(
            conn,
            limit=args.limit,
            entry_type=args.type,
            since=args.since,
            project=ctx["project"],
            branch=ctx["branch"],
            scope=ctx["scope_filter"],
            include_superseded=getattr(args, "include_superseded", False),
        )
        if not results:
            print("No memories found." if args.since else "No memories stored yet.")
            return

        header = f"Recent {len(results)} memories"
        if args.since:
            header += f" (since {args.since})"
        print(f"{header}:\n")
        for r in results:
            scope_label = _format_scope_label(r)
            superseded = (
                f" — superseded by #{r['superseded_by']}"
                if r.get("superseded_by")
                else ""
            )
            print(
                f"[#{r['id']}] ({r['entry_type']}, importance={r['importance']}, "
                f"scope={scope_label}) {r['created_at'][:10]}{superseded}"
            )
            print(f"  {r['content'][:120]}")
            print()


def cmd_delete(args):
    with connection() as conn:
        if delete_entry(conn, args.id):
            print(f"Memory #{args.id} deleted.")
        else:
            logger.warning("memory #%d not found", args.id)
            print(f"Error: memory #{args.id} not found.", file=sys.stderr)
            sys.exit(1)


def cmd_stats(_args):
    with connection() as conn:
        stats = collect_stats(conn)

    if stats.total == 0:
        print("No memories stored yet.")
        return

    print(f"Memory Statistics ({stats.total} total entries)\n")
    print("By type:")
    for name, count in stats.by_type:
        print(f"  {name}: {count}")
    print("\nBy class:")
    for name, count in stats.by_class:
        print(f"  {name}: {count}")
    print("\nBy scope:")
    for name, count in stats.by_scope:
        print(f"  {name}: {count}")
    print("\nBy project:")
    for name, count in stats.by_project:
        print(f"  {name}: {count}")

    if stats.superseded:
        print(f"\nSuperseded (hidden from default surfacing): {stats.superseded}")

    available = "yes" if is_available() else "no"
    print(
        f"\nEmbeddings: {stats.embedded}/{stats.total} entries ({stats.embedded_pct}%)"
    )
    print(f"Embedding provider: {stats.provider}")
    print(f"Embedding model: {stats.model}")
    print(f"Embedding dimension: {stats.dim}")
    print(f"Embedding model available: {available}")

    last = (
        stats.last_reflected_at.strftime("%Y-%m-%d %H:%M")
        if stats.last_reflected_at
        else "never"
    )
    print(f"\nUnreflected entries: {stats.unreflected}")
    print(f"Last reflection: {last}")


def cmd_entities(args):
    query = " ".join(args.query) if args.query else ""
    with connection() as conn:
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


def cmd_relationships(args):
    entity_name = " ".join(args.entity)
    with connection() as conn:
        entity = find_entity_by_name(conn, entity_name)
        if not entity:
            logger.warning("entity '%s' not found", entity_name)
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


class ReindexError(RuntimeError):
    """Reindex could not run (e.g. the embedding provider is unavailable)."""


#: SQL tail selecting entries that have no vector yet.
_MISSING_VEC = (
    "FROM memory_entries m WHERE NOT EXISTS "
    "(SELECT 1 FROM memory_vec v WHERE v.rowid = m.id)"
)


def _embed_missing(conn):
    """Embed the entries that lack a vector, in id order, 64 per commit.

    Each committed batch shrinks the missing set, so the query pages
    itself — no OFFSET bookkeeping. Returns the count written.

    Raises:
        ReindexError: if a batch fails to embed.
    """
    if conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0] == 0:
        print("No memory entries to embed.")
        return 0
    total = conn.execute(f"SELECT COUNT(*) {_MISSING_VEC}").fetchone()[0]
    if total == 0:
        print("Nothing to embed — every entry already has a vector.")
        return 0

    batch_size = 64
    embedded = 0
    while True:
        rows = conn.execute(
            f"SELECT m.id, m.content {_MISSING_VEC} ORDER BY m.id LIMIT ?",
            (batch_size,),
        ).fetchall()
        if not rows:
            break

        vectors = embed_texts([r[1] for r in rows], prefix="search_document")
        if vectors is None:
            logger.error("embedding failed")
            raise ReindexError("embedding failed")

        for (entry_id, _), vec in zip(rows, vectors):
            conn.execute(
                "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
                (entry_id, serialize_f32(vec)),
            )

        conn.commit()
        embedded += len(rows)
        print(f"Embedded {embedded}/{total} entries...")

    return embedded


def _reindex_embeddings(conn):
    """Recompute all vector embeddings from scratch. Returns the count written.

    Raises:
        ReindexError: if a batch fails to embed.
    """
    # Clear existing embeddings; every entry is then "missing".
    try:
        conn.execute("DELETE FROM memory_vec")
        conn.commit()
    except Exception:
        pass  # Table may not exist
    return _embed_missing(conn)


def _recreate_vec_table(conn, dim: int):
    """Drop and recreate the vec table with the given dimension."""
    conn.execute("DROP TRIGGER IF EXISTS memory_entries_vec_ad")
    conn.execute("DROP TABLE IF EXISTS memory_vec")
    conn.execute(
        f"CREATE VIRTUAL TABLE memory_vec "
        f"USING vec0(embedding float[{dim}] distance_metric=cosine)"
    )
    conn.execute(
        """CREATE TRIGGER memory_entries_vec_ad
           AFTER DELETE ON memory_entries BEGIN
             DELETE FROM memory_vec WHERE rowid = old.id;
           END"""
    )
    conn.commit()


def run_reindex(db_path=None, *, missing_only=False) -> int:
    """Recompute vector embeddings, recreating the vec table on a
    dimension change.

    The programmatic counterpart to :func:`cmd_reindex`: callers (the
    ``mait-code settings`` follow-up, the home hub, and ``doctor --fix``)
    get a return value instead of a process exit. Progress is still
    printed to stdout.

    Args:
        db_path: Override the memory database path (defaults to the
            configured ``{data_dir}/memory.db``).
        missing_only: Embed only the entries that lack a vector instead
            of re-embedding everything. A dimension mismatch still
            recreates (and so empties) the vec table first — at that
            point every entry is missing and the two modes converge.

    Returns:
        The number of embeddings written.

    Raises:
        ReindexError: if the embedding provider is unavailable or a
            batch fails to embed.
    """
    if not is_available():
        provider = _embedding_provider_name()
        if provider == "bedrock":
            hint = "Ensure boto3 is installed: pip install boto3"
        else:
            hint = "Ensure fastembed is installed: pip install fastembed"
        raise ReindexError(f"embedding model unavailable. {hint}")

    with connection(db_path) as conn:
        matches, table_dim, expected_dim = check_dimension_match(conn)
        if not matches:
            print(
                f"Dimension mismatch: vec table has {table_dim}d, "
                f"provider expects {expected_dim}d. Recreating vec table..."
            )
            _recreate_vec_table(conn, expected_dim)

        if missing_only:
            return _embed_missing(conn)
        return _reindex_embeddings(conn)


def cmd_reindex(_args):
    """Recompute vector embeddings for all memory entries."""
    try:
        embedded = run_reindex()
    except ReindexError as exc:
        logger.error("embedding model unavailable")
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if embedded:
        print(f"\nDone. {embedded} embeddings stored.")


def cmd_restore(args):
    """Restore memory database from observation JSONL log files."""
    import json

    from mait_code.hooks.observe.scope import resolve_scope
    from mait_code.hooks.observe.storage import CATEGORY_TO_TYPE
    from mait_code.tools.memory.db import get_data_dir
    from mait_code.tools.memory.entities import upsert_entity, upsert_relationship
    from mait_code.tools.memory.writer import store_memory as _store

    obs_dir = get_data_dir() / "memory" / "observations"
    if not obs_dir.exists():
        logger.warning("no observation logs found")
        print("No observation logs found.", file=sys.stderr)
        sys.exit(1)

    log_files = sorted(obs_dir.glob("*.jsonl"))
    if not log_files:
        logger.warning("no observation log files found")
        print("No observation log files found.", file=sys.stderr)
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)

    total_records = 0
    total_memories = 0
    total_entities = 0
    total_relationships = 0
    errors = 0

    from contextlib import ExitStack

    with ExitStack() as stack:
        conn = None if dry_run else stack.enter_context(connection())

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
                    rec_project = record.get("project")
                    rec_branch = record.get("branch")
                    total_records += 1
                    file_records += 1

                    # Replay memory entries
                    for category, entry_type in CATEGORY_TO_TYPE.items():
                        for item in extraction.get(category, []):
                            content = item.get("content", "").strip()
                            if not content:
                                continue
                            importance = item.get("importance", 5)
                            scope = resolve_scope(
                                item, category, rec_project, rec_branch
                            )
                            store_project = rec_project if scope != "global" else None
                            store_branch = rec_branch if scope == "branch" else None
                            if dry_run:
                                total_memories += 1
                            else:
                                assert conn is not None  # narrowed: not dry_run
                                try:
                                    _store(
                                        conn,
                                        content,
                                        entry_type,
                                        importance,
                                        scope=scope,
                                        project=store_project,
                                        branch=store_branch,
                                    )
                                    total_memories += 1
                                except Exception as e:
                                    logger.warning(
                                        "failed to store %s: %s", entry_type, e
                                    )
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
                            assert conn is not None  # narrowed: not dry_run
                            try:
                                entity_ids[name.lower()] = upsert_entity(
                                    conn, name, entity_type
                                )
                                total_entities += 1
                            except Exception as e:
                                logger.warning(
                                    "failed to upsert entity '%s': %s", name, e
                                )
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

                        assert conn is not None  # narrowed: not dry_run
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

            print(
                f"{'[dry-run] ' if dry_run else ''}{log_file.name}: {file_records} records"
            )

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


def cmd_reflect(args):
    """Synthesise recent observations into insights, update MEMORY.md."""
    from mait_code.tools.memory.reflect import reflect

    ctx = _resolve_context(args)
    total_insights = []
    total_stored = 0
    last_memory_diff = None
    iterations = 0
    max_iterations = 20

    with connection() as conn:
        while True:
            iterations += 1
            result = reflect(
                conn,
                days=args.days,
                min_new=args.min_new,
                batch_size=args.batch_size,
                project=ctx["project"],
                branch=ctx["branch"],
            )

            if result["skipped"]:
                if iterations == 1:
                    reason = result.get("reason", "not enough new signal")
                    print(f"Reflection skipped — {reason}.")
                break

            total_insights.extend(result["insights"])
            total_stored += result["stored"]
            if result["memory_diff"]:
                last_memory_diff = result["memory_diff"]

            batch_info = result.get("batch_info") or {}
            processed = batch_info.get("processed", 0)

            if not args.drain:
                break
            if processed < args.batch_size:
                break
            if iterations >= max_iterations:
                print(f"Reached maximum drain iterations ({max_iterations}).")
                break

    if not total_insights:
        if iterations > 1:
            print("Drain complete — no more unreflected entries.")
        return

    print(f"Generated {len(total_insights)} insights:\n")
    for i, insight in enumerate(total_insights, 1):
        print(f"  {i}. {insight}")
    print(f"\nStored {total_stored} insights to memory database.")

    if last_memory_diff:
        print(f"\n{last_memory_diff}")
        print("\nReview and apply these changes manually or approve when prompted.")


@log_invocation(name="mc-tool-memory")
def cmd_canonicalize_projects(args):
    """Rewrite stored project slugs to their canonical form per the alias map.

    Reads the project-alias map and, for each alias, rewrites matching
    ``memory_entries.project`` values to the canonical slug. Idempotent. The
    ``memory_entries_au`` trigger keeps the FTS shadow table in sync.
    """
    from mait_code.context import load_project_aliases
    from mait_code.tools.memory.db import get_data_dir

    aliases = {a: c for a, c in load_project_aliases().items() if a != c}
    if not aliases:
        path = get_data_dir() / "project-aliases.json"
        print(
            f"No project aliases configured. Create {path} with "
            '{"old-slug": "canonical-slug"} entries first.'
        )
        return

    dry_run = getattr(args, "dry_run", False)
    total = 0
    with connection() as conn:
        for alias, canonical in aliases.items():
            if dry_run:
                n = conn.execute(
                    "SELECT COUNT(*) FROM memory_entries WHERE project = ?", (alias,)
                ).fetchone()[0]
            else:
                n = conn.execute(
                    "UPDATE memory_entries SET project = ? WHERE project = ?",
                    (canonical, alias),
                ).rowcount
            total += n
            print(f"  {alias} -> {canonical}: {n} entr{'y' if n == 1 else 'ies'}")
        if not dry_run:
            conn.commit()
    verb = "Would rewrite" if dry_run else "Rewrote"
    print(f"{verb} {total} entr{'y' if total == 1 else 'ies'}.")


def main():
    setup_logging()

    from mait_code.ssl import setup_ssl

    setup_ssl()
    parser = argparse.ArgumentParser(prog="mc-tool-memory", description="Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_scope_args(p):
        """Add --project, --branch, --scope flags to a subparser."""
        p.add_argument(
            "--project", default=None, help="Project filter (default: auto-detected)"
        )
        p.add_argument(
            "--branch", default=None, help="Branch filter (default: auto-detected)"
        )
        p.add_argument(
            "--scope",
            choices=["global", "project", "branch", "all"],
            default=None,
            help="Scope filter (default: context-aware; 'all' disables filtering)",
        )

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
    _add_scope_args(p_search)
    p_search.set_defaults(func=cmd_search)

    # store
    p_store = sub.add_parser("store", help="Store a memory")
    p_store.add_argument("content", nargs="+", help="Memory content")
    p_store.add_argument("--type", choices=sorted(VALID_ENTRY_TYPES), default="fact")
    p_store.add_argument("--importance", type=int, default=5, choices=range(1, 11))
    _add_scope_args(p_store)
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
    p_list.add_argument(
        "--include-superseded",
        action="store_true",
        help="Include superseded entries (hidden by default)",
    )
    _add_scope_args(p_list)
    p_list.set_defaults(func=cmd_list)

    # supersede
    p_supersede = sub.add_parser(
        "supersede",
        help="Replace an entry with an evolved version (keeps the old one for audit)",
    )
    p_supersede.add_argument("old_id", type=int, help="ID of the entry to supersede")
    p_supersede.add_argument("content", nargs="+", help="New, current content")
    p_supersede.add_argument(
        "--importance",
        type=int,
        default=None,
        choices=range(1, 11),
        help="Importance for the new entry (default: inherit from the old one)",
    )
    p_supersede.set_defaults(func=cmd_supersede)

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
        default=config.get_int("reflection-novelty-gate"),
        help="Minimum new observations to trigger reflection",
    )
    p_reflect.add_argument(
        "--batch-size",
        type=int,
        default=config.get_int("reflection-batch-size"),
        help="Maximum entries to process per reflection",
    )
    p_reflect.add_argument(
        "--drain",
        action="store_true",
        help="Loop until all unreflected entries are processed",
    )
    _add_scope_args(p_reflect)
    p_reflect.set_defaults(func=cmd_reflect)

    # canonicalize-projects
    p_canon = sub.add_parser(
        "canonicalize-projects",
        help="Rewrite stored project slugs per the project-alias map",
    )
    p_canon.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database",
    )
    p_canon.set_defaults(func=cmd_canonicalize_projects)

    args = parser.parse_args()
    args.func(args)
