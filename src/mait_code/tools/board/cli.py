"""CLI tool for the board — create, refine, pick up, move, and complete cards.

A single cross-project kanban board stored in ``board.db``. Cards carry a
``project`` field and move through a fixed workflow: backlog → refined →
in_progress → done, with a hidden ``archived`` side-state. ``blocked`` is a tag
carried in place (via ``block``/``unblock``), not a column.

The handlers here are thin: argument parsing, the not-found/exit helper, and
presentation (text vs ``--json``). Every query and mutation — including the
done-invariant — lives in :mod:`mait_code.tools.board.service`, the shared core
the interactive TUI sits on too.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import NoReturn

from mait_code.logging import log_invocation, setup_logging
from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    ARCHIVED,
    BOARD_ORDER,
    REFINED,
    label,
)
from mait_code.tools.board.db import connection, get_project

logger = logging.getLogger(__name__)

PRIORITIES = ("low", "medium", "high")
AUTHORS = ("me", "claude")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _not_found(card_id: int) -> NoReturn:
    """Print a not-found error to stderr and exit(1)."""
    logger.warning("card #%d not found", card_id)
    print(f"Error: card #{card_id} not found.", file=sys.stderr)
    sys.exit(1)


# --- Card CRUD ---


def cmd_add(args):
    title = " ".join(args.title).strip()
    if not title:
        logger.warning("card title cannot be empty")
        print("Error: card title cannot be empty.", file=sys.stderr)
        sys.exit(1)

    project = args.project or get_project()
    with connection() as conn:
        card_id = service.add_card(
            conn,
            project=project,
            title=title,
            description=args.description,
            priority=args.priority,
        )

    print(f"Card #{card_id} added ({args.priority}): {title}")


def cmd_list(args):
    project = None if args.all else get_project()
    statuses = [args.status] if args.status else None
    with connection() as conn:
        cards = service.list_cards(
            conn,
            project=project,
            statuses=statuses,
            include_archived=args.archived,
        )

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
        card = service.get_card(conn, args.id)
        if card is None:
            _not_found(args.id)
        comments = service.get_comments(conn, args.id)

    if args.json:
        card["comments"] = comments
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
        for comment in comments:
            print(f"  [{comment['author']}] {comment['body']}")


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

    with connection() as conn:
        try:
            service.edit_card(conn, args.id, **fields)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id} updated.")


def cmd_remove(args):
    with connection() as conn:
        try:
            service.remove_card(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id} removed.")


def cmd_comment(args):
    body = " ".join(args.body).strip()
    if not body:
        print("Error: comment body cannot be empty.", file=sys.stderr)
        sys.exit(1)

    with connection() as conn:
        try:
            service.add_comment(conn, args.id, body, author=args.author)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Comment added to card #{args.id}.")


# --- Workflow verbs ---


def cmd_move(args):
    new_status = args.status  # argparse choices=ALL_STATUSES guarantees validity
    with connection() as conn:
        try:
            service.move_card(conn, args.id, new_status)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id} → {label(new_status)}.")


def cmd_refine(args):
    with connection() as conn:
        card = service.get_card(conn, args.id)
        if card is None:
            _not_found(args.id)
        had_acceptance = bool(card["acceptance_criteria"])
        service.refine_card(
            conn, args.id, description=args.description, acceptance=args.acceptance
        )

    # Warn if the card lands in Refined with no acceptance criteria at all.
    if args.acceptance is None and not had_acceptance:
        print(f"Warning: card #{args.id} has no acceptance criteria.", file=sys.stderr)
    print(f"Card #{args.id} → {label(REFINED)}.")


def cmd_next(args):
    """Print the next refined card; with --claim, move it to in_progress."""
    project = args.project or get_project()
    with connection() as conn:
        card = service.next_refined(conn, project, claim=args.claim)

    if card is None:
        if args.json:
            print("null")
        else:
            print(f"No refined cards for {project}.")
        return

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
        try:
            service.complete_card(conn, args.id, summary=summary or None)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id} completed.")


def cmd_block(args):
    reason = " ".join(args.reason).strip()
    with connection() as conn:
        try:
            service.block_card(conn, args.id, reason=reason or None)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id} tagged 'blocked'.")


def cmd_unblock(args):
    with connection() as conn:
        try:
            service.unblock_card(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id}: 'blocked' tag removed.")


def cmd_archive(args):
    with connection() as conn:
        try:
            service.archive_card(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)

    print(f"Card #{args.id} → {label(ARCHIVED)}.")


def cmd_summary(args):
    project = args.project or (None if args.all else get_project())
    with connection() as conn:
        counts = service.summary_counts(conn, project=project)

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

    p_block = sub.add_parser(
        "block", help="Tag a card 'blocked' in place, optionally with a reason"
    )
    p_block.add_argument("id", type=int, help="Card ID")
    p_block.add_argument("reason", nargs="*", help="Reason (recorded as a comment)")
    p_block.set_defaults(func=cmd_block)

    p_unblock = sub.add_parser("unblock", help="Remove the 'blocked' tag from a card")
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
