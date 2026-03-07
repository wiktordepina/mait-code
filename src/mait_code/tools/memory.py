"""CLI tool for memory search and storage."""

import argparse
import sys

from mait_code.memory.db import get_connection
from mait_code.memory.scoring import composite_score
from mait_code.memory.search import delete_entry, list_entries, search_entries
from mait_code.memory.writer import VALID_ENTRY_TYPES
from mait_code.memory.writer import store_memory as _store_memory


def cmd_search(args):
    query = " ".join(args.query)
    if not query.strip():
        print("Error: query cannot be empty.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection()
    try:
        results = search_entries(
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
                relevance=0.7,
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
        print("Error: content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    if args.type not in VALID_ENTRY_TYPES:
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
            print(f"Memory deduplicated (updated entry #{result['id']}): {content[:80]}")
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
        results = list_entries(conn, limit=args.limit, entry_type=args.type)
        if not results:
            print("No memories stored yet.")
            return

        print(f"Recent {len(results)} memories:\n")
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

        print(f"Memory Statistics ({total} total entries)\n")
        print("By type:")
        for row in by_type:
            print(f"  {row[0]}: {row[1]}")
        print("\nBy class:")
        for row in by_class:
            print(f"  {row[0]}: {row[1]}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(prog="mc-tool-memory", description="Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search memories")
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--type", choices=sorted(VALID_ENTRY_TYPES), default=None)
    p_search.set_defaults(func=cmd_search)

    # store
    p_store = sub.add_parser("store", help="Store a memory")
    p_store.add_argument("content", nargs="+", help="Memory content")
    p_store.add_argument(
        "--type", choices=sorted(VALID_ENTRY_TYPES), default="fact"
    )
    p_store.add_argument("--importance", type=int, default=5, choices=range(1, 11))
    p_store.set_defaults(func=cmd_store)

    # list
    p_list = sub.add_parser("list", help="List recent memories")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--type", choices=sorted(VALID_ENTRY_TYPES), default=None)
    p_list.set_defaults(func=cmd_list)

    # delete
    p_delete = sub.add_parser("delete", help="Delete a memory by ID")
    p_delete.add_argument("id", type=int, help="Memory entry ID")
    p_delete.set_defaults(func=cmd_delete)

    # stats
    p_stats = sub.add_parser("stats", help="Show memory statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)
