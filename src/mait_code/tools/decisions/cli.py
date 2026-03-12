"""CLI tool for decisions — record, list, show, amend, supersede, search, remove, sync."""

import argparse
import logging
import sys
from datetime import datetime, timezone

from mait_code.logging import log_invocation, setup_logging

from mait_code.tools.decisions.db import connection, get_project
from mait_code.tools.decisions.render import write_decisions_md

logger = logging.getLogger(__name__)

STATUSES = ("accepted", "proposed", "deprecated", "superseded")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cmd_record(args):
    title = " ".join(args.title)
    if not title.strip():
        logger.error("decision title cannot be empty")
        print("Error: decision title cannot be empty.", file=sys.stderr)
        sys.exit(1)

    project = get_project()
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO decisions (project, title, context, alternatives, consequences, "
            "status, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project,
                title.strip(),
                args.context,
                args.alternatives,
                args.consequences,
                args.status,
                args.tags,
                _now().isoformat(),
            ),
        )
        conn.commit()
        decision_id = cursor.lastrowid
        write_decisions_md(conn)

    print(f"Decision #{decision_id} recorded: {title.strip()}")


def cmd_list(args):
    project = get_project()
    with connection() as conn:
        if args.all:
            query = "SELECT id, title, status, tags, created_at FROM decisions WHERE project = ?"
            params = [project]
        else:
            query = (
                "SELECT id, title, status, tags, created_at FROM decisions "
                "WHERE project = ? AND status IN ('accepted', 'proposed')"
            )
            params = [project]

        if args.tag:
            query += " AND tags LIKE ?"
            params.append(f"%{args.tag}%")

        if args.status:
            if not args.all:
                query = (
                    "SELECT id, title, status, tags, created_at FROM decisions "
                    "WHERE project = ? AND status = ?"
                )
                params = [project, args.status]
            else:
                query += " AND status = ?"
                params.append(args.status)

            if args.tag:
                query += " AND tags LIKE ?"
                params.append(f"%{args.tag}%")

        query += " ORDER BY id"
        rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No decisions found.")
        return

    print(f"Decisions ({len(rows)}):\n")
    for did, title, status, tags, created_at in rows:
        date = created_at[:10] if created_at else ""
        tags_str = f" [{tags}]" if tags else ""
        print(f"  DR-{did} ({status}) {title}{tags_str}  {date}")
    print()


def cmd_show(args):
    with connection() as conn:
        row = conn.execute(
            "SELECT id, project, title, context, alternatives, consequences, "
            "status, superseded_by, tags, created_at, updated_at "
            "FROM decisions WHERE id = ?",
            (args.id,),
        ).fetchone()

    if row is None:
        logger.error("decision #%d not found", args.id)
        print(f"Error: decision #{args.id} not found.", file=sys.stderr)
        sys.exit(1)

    (
        did,
        project,
        title,
        context,
        alternatives,
        consequences,
        status,
        superseded_by,
        tags,
        created_at,
        updated_at,
    ) = row

    print(f"DR-{did}: {title}")
    print(f"Project: {project}")
    print(f"Status: {status}")
    if tags:
        print(f"Tags: {tags}")
    print(f"Recorded: {created_at[:10]}")
    if updated_at:
        print(f"Updated: {updated_at[:10]}")
    if superseded_by:
        print(f"Superseded by: DR-{superseded_by}")
    if context:
        print(f"\nContext:\n{context}")
    if alternatives:
        print(f"\nAlternatives considered:\n{alternatives}")
    if consequences:
        print(f"\nConsequences:\n{consequences}")


def cmd_amend(args):
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (args.id,)
        ).fetchone()

        if row is None:
            logger.error("decision #%d not found", args.id)
            print(f"Error: decision #{args.id} not found.", file=sys.stderr)
            sys.exit(1)

        updates = []
        params = []

        if args.context is not None:
            updates.append("context = ?")
            params.append(args.context)
        if args.alternatives is not None:
            updates.append("alternatives = ?")
            params.append(args.alternatives)
        if args.consequences is not None:
            updates.append("consequences = ?")
            params.append(args.consequences)
        if args.status is not None:
            updates.append("status = ?")
            params.append(args.status)
        if args.tags is not None:
            updates.append("tags = ?")
            params.append(args.tags)

        if not updates:
            print("Nothing to update.")
            return

        updates.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(args.id)

        conn.execute(
            f"UPDATE decisions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        write_decisions_md(conn)

    print(f"Decision #{args.id} amended.")


def cmd_supersede(args):
    with connection() as conn:
        old = conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (args.old_id,)
        ).fetchone()
        if old is None:
            print(f"Error: decision #{args.old_id} not found.", file=sys.stderr)
            sys.exit(1)

        new = conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (args.new_id,)
        ).fetchone()
        if new is None:
            print(f"Error: decision #{args.new_id} not found.", file=sys.stderr)
            sys.exit(1)

        conn.execute(
            "UPDATE decisions SET status = 'superseded', superseded_by = ?, updated_at = ? "
            "WHERE id = ?",
            (args.new_id, _now().isoformat(), args.old_id),
        )
        conn.commit()
        write_decisions_md(conn)

    print(f"Decision #{args.old_id} superseded by #{args.new_id}.")


def cmd_search(args):
    query = " ".join(args.query)
    if not query.strip():
        print("Error: search query cannot be empty.", file=sys.stderr)
        sys.exit(1)

    project = get_project()
    with connection() as conn:
        rows = conn.execute(
            "SELECT d.id, d.title, d.status, d.tags, d.created_at "
            "FROM decisions d "
            "JOIN decisions_fts ON decisions_fts.rowid = d.id "
            "WHERE decisions_fts MATCH ? AND d.project = ? "
            "ORDER BY rank",
            (query.strip(), project),
        ).fetchall()

    if not rows:
        print("No matching decisions.")
        return

    print(f"Search results ({len(rows)}):\n")
    for did, title, status, tags, created_at in rows:
        date = created_at[:10] if created_at else ""
        tags_str = f" [{tags}]" if tags else ""
        print(f"  DR-{did} ({status}) {title}{tags_str}  {date}")
    print()


def cmd_remove(args):
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (args.id,)
        ).fetchone()

        if row is None:
            logger.error("decision #%d not found", args.id)
            print(f"Error: decision #{args.id} not found.", file=sys.stderr)
            sys.exit(1)

        conn.execute(
            "UPDATE decisions SET superseded_by = NULL WHERE superseded_by = ?",
            (args.id,),
        )
        conn.execute("DELETE FROM decisions WHERE id = ?", (args.id,))
        conn.commit()
        write_decisions_md(conn)

    print(f"Decision #{args.id} removed.")


def cmd_sync(_args):
    with connection() as conn:
        write_decisions_md(conn)
    print("docs/decisions.md regenerated.")


@log_invocation(name="mc-tool-decisions")
def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="mc-tool-decisions", description="Decision records CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # record
    p_record = sub.add_parser("record", help="Record a new decision")
    p_record.add_argument("title", nargs="+", help="Decision title")
    p_record.add_argument("--context", help="Problem or situation that prompted this")
    p_record.add_argument("--alternatives", help="Other options considered")
    p_record.add_argument("--consequences", help="Known trade-offs")
    p_record.add_argument(
        "--status", choices=STATUSES, default="accepted", help="Decision status"
    )
    p_record.add_argument("--tags", help="Comma-separated tags")
    p_record.set_defaults(func=cmd_record)

    # list
    p_list = sub.add_parser("list", help="List decisions")
    p_list.add_argument("--all", action="store_true", help="Include all statuses")
    p_list.add_argument("--tag", help="Filter by tag")
    p_list.add_argument("--status", choices=STATUSES, help="Filter by status")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Show full decision details")
    p_show.add_argument("id", type=int, help="Decision ID")
    p_show.set_defaults(func=cmd_show)

    # amend
    p_amend = sub.add_parser("amend", help="Update specific fields of a decision")
    p_amend.add_argument("id", type=int, help="Decision ID")
    p_amend.add_argument("--context", help="Update context")
    p_amend.add_argument("--alternatives", help="Update alternatives")
    p_amend.add_argument("--consequences", help="Update consequences")
    p_amend.add_argument("--status", choices=STATUSES, help="Update status")
    p_amend.add_argument("--tags", help="Update tags")
    p_amend.set_defaults(func=cmd_amend)

    # supersede
    p_supersede = sub.add_parser("supersede", help="Mark a decision as superseded")
    p_supersede.add_argument("old_id", type=int, help="Decision to supersede")
    p_supersede.add_argument("new_id", type=int, help="Replacement decision")
    p_supersede.set_defaults(func=cmd_supersede)

    # search
    p_search = sub.add_parser("search", help="Full-text search across decisions")
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.set_defaults(func=cmd_search)

    # remove
    p_remove = sub.add_parser("remove", help="Delete a decision")
    p_remove.add_argument("id", type=int, help="Decision ID")
    p_remove.set_defaults(func=cmd_remove)

    # sync
    sub.add_parser("sync", help="Regenerate docs/decisions.md").set_defaults(
        func=cmd_sync
    )

    args = parser.parse_args()
    args.func(args)
