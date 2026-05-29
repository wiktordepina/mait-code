"""CLI tool for the board — create, refine, pick up, move, and complete cards.

A single cross-project kanban board stored in ``board.db``. Cards carry a
``project`` field and move through a fixed workflow: backlog → refined →
in_progress → done, with ``blocked`` and hidden ``archived`` side-states.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from mait_code.logging import log_invocation, setup_logging
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    ARCHIVED,
    BACKLOG,
    BLOCKED,
    BOARD_ORDER,
    DONE,
    IN_PROGRESS,
    REFINED,
    label,
)
from mait_code.tools.board.db import connection, get_project

logger = logging.getLogger(__name__)

PRIORITIES = ("low", "medium", "high")
AUTHORS = ("me", "claude")
_PRIORITY_ORDER = "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
_CARD_COLS = (
    "id, project, title, description, acceptance_criteria, status, priority, "
    "completion_summary, created_at, updated_at, completed_at"
)
_CARD_KEYS = (
    "id",
    "project",
    "title",
    "description",
    "acceptance_criteria",
    "status",
    "priority",
    "completion_summary",
    "created_at",
    "updated_at",
    "completed_at",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _card_dict(row) -> dict:
    """Map a row selected with ``_CARD_COLS`` to a JSON-friendly dict."""
    return dict(zip(_CARD_KEYS, row))


def _fetch_card(conn, card_id):
    return conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE id = ?", (card_id,)
    ).fetchone()


def _require_card(conn, card_id):
    """Fetch a card or exit(1) with a not-found error."""
    row = _fetch_card(conn, card_id)
    if row is None:
        logger.error("card #%d not found", card_id)
        print(f"Error: card #{card_id} not found.", file=sys.stderr)
        sys.exit(1)
    return row


# --- Card CRUD ---


def cmd_add(args):
    title = " ".join(args.title).strip()
    if not title:
        logger.error("card title cannot be empty")
        print("Error: card title cannot be empty.", file=sys.stderr)
        sys.exit(1)

    project = args.project or get_project()
    now = _now().isoformat()
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO cards (project, title, description, status, priority, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project, title, args.description, BACKLOG, args.priority, now, now),
        )
        conn.commit()
        card_id = cursor.lastrowid

    print(f"Card #{card_id} added ({args.priority}): {title}")


def cmd_list(args):
    where = []
    params = []
    if not args.all:
        where.append("project = ?")
        params.append(get_project())
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    elif not args.archived:
        where.append("status != ?")
        params.append(ARCHIVED)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    with connection() as conn:
        rows = conn.execute(
            f"SELECT {_CARD_COLS} FROM cards{clause} "
            f"ORDER BY {_PRIORITY_ORDER}, created_at, id",
            params,
        ).fetchall()

    cards = [_card_dict(r) for r in rows]
    if args.json:
        print(json.dumps(cards, indent=2))
        return

    if not cards:
        print("No cards." if not args.all else "No cards on the board.")
        return

    show_archived = args.archived or args.status == ARCHIVED
    order = list(BOARD_ORDER) + ([ARCHIVED] if show_archived else [])
    by_status: dict[str, list[dict]] = {}
    for card in cards:
        by_status.setdefault(card["status"], []).append(card)

    for status in order:
        group = by_status.get(status)
        if not group:
            continue
        print(f"{label(status)} ({len(group)}):")
        for card in group:
            project = f" [{card['project']}]" if args.all else ""
            print(f"  [#{card['id']}] ({card['priority']}) {card['title']}{project}")
        print()


def cmd_show(args):
    with connection() as conn:
        row = _require_card(conn, args.id)
        comments = conn.execute(
            "SELECT author, body, created_at FROM card_comments "
            "WHERE card_id = ? ORDER BY id",
            (args.id,),
        ).fetchall()

    card = _card_dict(row)
    if args.json:
        card["comments"] = [
            {"author": a, "body": b, "created_at": c} for a, b, c in comments
        ]
        print(json.dumps(card, indent=2))
        return

    print(f"#{card['id']} ({card['priority']}) {card['title']}")
    print(f"  project: {card['project']}   status: {label(card['status'])}")
    if card["description"]:
        print(f"\nDescription:\n{card['description']}")
    if card["acceptance_criteria"]:
        print(f"\nAcceptance criteria:\n{card['acceptance_criteria']}")
    if card["completion_summary"]:
        print(f"\nCompletion summary:\n{card['completion_summary']}")
    if comments:
        print(f"\nComments ({len(comments)}):")
        for author, body, _created_at in comments:
            print(f"  [{author}] {body}")


def cmd_edit(args):
    fields: dict[str, str] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.description is not None:
        fields["description"] = args.description
    if args.priority is not None:
        fields["priority"] = args.priority
    if args.acceptance is not None:
        fields["acceptance_criteria"] = args.acceptance

    if not fields:
        print("Error: nothing to edit (pass at least one field).", file=sys.stderr)
        sys.exit(1)

    fields["updated_at"] = _now().isoformat()
    with connection() as conn:
        _require_card(conn, args.id)
        cols = ", ".join(f"{key} = ?" for key in fields)
        conn.execute(
            f"UPDATE cards SET {cols} WHERE id = ?", (*fields.values(), args.id)
        )
        conn.commit()

    print(f"Card #{args.id} updated.")


def cmd_remove(args):
    with connection() as conn:
        _require_card(conn, args.id)
        conn.execute("DELETE FROM cards WHERE id = ?", (args.id,))
        conn.commit()

    print(f"Card #{args.id} removed.")


def cmd_comment(args):
    body = " ".join(args.body).strip()
    if not body:
        print("Error: comment body cannot be empty.", file=sys.stderr)
        sys.exit(1)

    now = _now().isoformat()
    with connection() as conn:
        _require_card(conn, args.id)
        conn.execute(
            "INSERT INTO card_comments (card_id, author, body, created_at) "
            "VALUES (?, ?, ?, ?)",
            (args.id, args.author, body, now),
        )
        conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (now, args.id))
        conn.commit()

    print(f"Comment added to card #{args.id}.")


# --- Workflow verbs ---


def cmd_move(args):
    new_status = args.status  # argparse choices=ALL_STATUSES guarantees validity
    with connection() as conn:
        row = _require_card(conn, args.id)
        old_status = row[5]
        now = _now().isoformat()
        if new_status == DONE and old_status != DONE:
            conn.execute(
                "UPDATE cards SET status = ?, completed_at = ?, updated_at = ? "
                "WHERE id = ?",
                (new_status, now, now, args.id),
            )
        elif new_status != DONE and old_status == DONE:
            conn.execute(
                "UPDATE cards SET status = ?, completed_at = NULL, updated_at = ? "
                "WHERE id = ?",
                (new_status, now, args.id),
            )
        else:
            conn.execute(
                "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, args.id),
            )
        conn.commit()

    print(f"Card #{args.id} → {label(new_status)}.")


def cmd_refine(args):
    now = _now().isoformat()
    fields: dict[str, str] = {"status": REFINED, "updated_at": now}
    if args.description is not None:
        fields["description"] = args.description
    if args.acceptance is not None:
        fields["acceptance_criteria"] = args.acceptance

    with connection() as conn:
        row = _require_card(conn, args.id)
        cols = ", ".join(f"{key} = ?" for key in fields)
        conn.execute(
            f"UPDATE cards SET {cols} WHERE id = ?", (*fields.values(), args.id)
        )
        conn.commit()

    # Warn if the card lands in Refined with no acceptance criteria at all.
    if args.acceptance is None and not row[4]:
        print(f"Warning: card #{args.id} has no acceptance criteria.", file=sys.stderr)
    print(f"Card #{args.id} → {label(REFINED)}.")


def cmd_next(args):
    """Print the next refined card; with --claim, move it to in_progress."""
    project = args.project or get_project()
    with connection() as conn:
        row = conn.execute(
            f"SELECT {_CARD_COLS} FROM cards "
            f"WHERE project = ? AND status = ? "
            f"ORDER BY {_PRIORITY_ORDER}, created_at, id LIMIT 1",
            (project, REFINED),
        ).fetchone()

        if row is None:
            if args.json:
                print("null")
            else:
                print(f"No refined cards for {project}.")
            return

        if args.claim:
            now = _now().isoformat()
            # Guard on status so a concurrent claim can't double-move.
            conn.execute(
                "UPDATE cards SET status = ?, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (IN_PROGRESS, now, row[0], REFINED),
            )
            conn.commit()
            row = _fetch_card(conn, row[0])

    card = _card_dict(row)
    if args.json:
        print(json.dumps(card, indent=2))
        return

    verb = "Picked up" if args.claim else "Next"
    print(f"{verb}: #{card['id']} ({card['priority']}) {card['title']}")
    if card["acceptance_criteria"]:
        print(f"\nAcceptance criteria:\n{card['acceptance_criteria']}")


def cmd_complete(args):
    summary = " ".join(args.summary).strip()
    with connection() as conn:
        _require_card(conn, args.id)
        now = _now().isoformat()
        conn.execute(
            "UPDATE cards SET status = ?, completion_summary = ?, completed_at = ?, "
            "updated_at = ? WHERE id = ?",
            (DONE, summary or None, now, now, args.id),
        )
        conn.commit()

    print(f"Card #{args.id} completed.")


def cmd_block(args):
    reason = " ".join(args.reason).strip()
    now = _now().isoformat()
    with connection() as conn:
        _require_card(conn, args.id)
        conn.execute(
            "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
            (BLOCKED, now, args.id),
        )
        if reason:
            conn.execute(
                "INSERT INTO card_comments (card_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (args.id, "me", f"Blocked: {reason}", now),
            )
        conn.commit()

    print(f"Card #{args.id} → {label(BLOCKED)}.")


def cmd_unblock(args):
    now = _now().isoformat()
    with connection() as conn:
        _require_card(conn, args.id)
        conn.execute(
            "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
            (REFINED, now, args.id),
        )
        conn.commit()

    print(f"Card #{args.id} → {label(REFINED)}.")


def cmd_archive(args):
    now = _now().isoformat()
    with connection() as conn:
        _require_card(conn, args.id)
        conn.execute(
            "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
            (ARCHIVED, now, args.id),
        )
        conn.commit()

    print(f"Card #{args.id} → {label(ARCHIVED)}.")


def cmd_summary(args):
    project = args.project or (None if args.all else get_project())
    with connection() as conn:
        if project is None:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM cards WHERE status != ? GROUP BY status",
                (ARCHIVED,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM cards "
                "WHERE project = ? AND status != ? GROUP BY status",
                (project, ARCHIVED),
            ).fetchall()

    counts = {status: 0 for status in BOARD_ORDER}
    for status, count in rows:
        if status in counts:
            counts[status] = count

    if args.json:
        print(json.dumps({"project": project, "counts": counts}, indent=2))
        return

    if sum(counts.values()) == 0:
        print("No cards." if project is None else f"No cards for {project}.")
        return

    parts = " · ".join(f"{label(s)}: {counts[s]}" for s in BOARD_ORDER)
    header = "All projects" if project is None else project
    print(f"{header} — {parts}")


@log_invocation(name="mc-tool-board")
def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="mc-tool-board", description="Project kanban board CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Add a card to the backlog")
    p_add.add_argument("--description", help="Card description")
    p_add.add_argument("--priority", choices=PRIORITIES, default="medium")
    p_add.add_argument("--project", help="Project (defaults to git root or cwd)")
    p_add.add_argument("title", nargs="+", help="Card title")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List cards grouped by column")
    p_list.add_argument("--all", action="store_true", help="Span all projects")
    p_list.add_argument("--status", choices=ALL_STATUSES, help="Filter to one column")
    p_list.add_argument("--archived", action="store_true", help="Include archived")
    p_list.add_argument("--json", action="store_true", help="Emit JSON")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show a card and its comments")
    p_show.add_argument("id", type=int, help="Card ID")
    p_show.add_argument("--json", action="store_true", help="Emit JSON")
    p_show.set_defaults(func=cmd_show)

    p_move = sub.add_parser("move", help="Move a card to a column")
    p_move.add_argument("id", type=int, help="Card ID")
    p_move.add_argument("status", choices=ALL_STATUSES, help="Target column")
    p_move.set_defaults(func=cmd_move)

    p_refine = sub.add_parser(
        "refine", help="Set description/acceptance and move to refined"
    )
    p_refine.add_argument("id", type=int, help="Card ID")
    p_refine.add_argument("--description", help="Card description")
    p_refine.add_argument("--acceptance", help="Acceptance criteria")
    p_refine.set_defaults(func=cmd_refine)

    p_next = sub.add_parser("next", help="Show (or --claim) the next refined card")
    p_next.add_argument("--project", help="Project (defaults to git root or cwd)")
    p_next.add_argument("--claim", action="store_true", help="Move it to in_progress")
    p_next.add_argument("--json", action="store_true", help="Emit JSON")
    p_next.set_defaults(func=cmd_next)

    p_complete = sub.add_parser("complete", help="Complete a card with a summary")
    p_complete.add_argument("id", type=int, help="Card ID")
    p_complete.add_argument("--summary", nargs="+", default=[], help="Handoff summary")
    p_complete.set_defaults(func=cmd_complete)

    p_block = sub.add_parser("block", help="Block a card, optionally with a reason")
    p_block.add_argument("id", type=int, help="Card ID")
    p_block.add_argument("reason", nargs="*", help="Reason (recorded as a comment)")
    p_block.set_defaults(func=cmd_block)

    p_unblock = sub.add_parser("unblock", help="Return a blocked card to refined")
    p_unblock.add_argument("id", type=int, help="Card ID")
    p_unblock.set_defaults(func=cmd_unblock)

    p_archive = sub.add_parser("archive", help="Archive a card (hide it)")
    p_archive.add_argument("id", type=int, help="Card ID")
    p_archive.set_defaults(func=cmd_archive)

    p_comment = sub.add_parser("comment", help="Append a comment to a card")
    p_comment.add_argument("id", type=int, help="Card ID")
    p_comment.add_argument("--author", choices=AUTHORS, default="me")
    p_comment.add_argument("body", nargs="+", help="Comment text")
    p_comment.set_defaults(func=cmd_comment)

    p_edit = sub.add_parser("edit", help="Edit card fields")
    p_edit.add_argument("id", type=int, help="Card ID")
    p_edit.add_argument("--title", help="New title")
    p_edit.add_argument("--description", help="New description")
    p_edit.add_argument("--priority", choices=PRIORITIES, help="New priority")
    p_edit.add_argument("--acceptance", help="New acceptance criteria")
    p_edit.set_defaults(func=cmd_edit)

    p_remove = sub.add_parser("remove", help="Delete a card permanently")
    p_remove.add_argument("id", type=int, help="Card ID")
    p_remove.set_defaults(func=cmd_remove)

    p_summary = sub.add_parser(
        "summary", help="Per-column counts (used by the session hook)"
    )
    p_summary.add_argument("--all", action="store_true", help="Span all projects")
    p_summary.add_argument("--project", help="Project (defaults to git root or cwd)")
    p_summary.add_argument("--json", action="store_true", help="Emit JSON")
    p_summary.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    args.func(args)
