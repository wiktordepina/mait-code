"""CLI tool for the board — create, refine, pick up, move, and complete cards.

A single cross-project kanban board stored in ``board.db``. Cards carry a
``project`` field and move through a fixed workflow: backlog → refined →
in_progress → in_review → done, with a hidden ``archived`` side-state. ``blocked`` is a tag
carried in place (via ``block``/``unblock``), not a column.

Cards relate to each other two ways. An *epic* (``add --epic``, ``epic …``) is
an umbrella over member cards in any project, named by each member's
``--parent``; epics stay off ``list`` and ``next``. ``link A blocks B`` records
that B can't start until A is done — ``next`` and ``list --ready`` skip a card
while it waits.

Run from inside a Claude Code session, ``move N in_progress`` and
``next --claim`` also bind the card to that session (``bind``/``unbind`` do it
explicitly, in any open column), so parallel sessions can each tell their own
card from the rest; ``next`` and ``list --ready`` pass over a card another live
session holds.

The handlers here are thin: argument parsing, the not-found/exit helper, and
presentation (text vs ``--json``). Every query and mutation — including the
done-invariant — lives in :mod:`mait_code.tools.board.service`, the shared core
the interactive TUI sits on too.
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

from mait_code.logging import log_invocation, setup_logging
from mait_code.tools.board import export, service
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    ARCHIVED,
    BOARD_ORDER,
    DONE,
    EPIC,
    IN_REVIEW,
    LINK_TYPES,
    REFINED,
    STEP_PAUSED,
    STEP_SKIPPED,
    STEP_STATUSES,
    label,
)
from mait_code.tools.board.db import connection, get_project
from mait_code.tools.board.sessions import (
    PID_ENV,
    SESSION_ENV,
    SessionRef,
    current_session,
)

logger = logging.getLogger(__name__)

PRIORITIES = ("low", "medium", "high")
#: ``edit --parent`` value that clears a card's epic.
NO_PARENT = "none"
AUTHORS = ("me", "claude")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fail(message: str) -> NoReturn:
    """Print an error to stderr and exit(1)."""
    logger.warning("%s", message)
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def _session_label(binding: dict) -> str:
    """A compact ``<id prefix> (pid N)`` label for one session binding."""
    return f"{binding['session_id'][:8]} (pid {binding['pid']})"


def _not_found(card_id: int) -> NoReturn:
    """Print a not-found error to stderr and exit(1)."""
    logger.warning("card #%d not found", card_id)
    print(f"Error: card #{card_id} not found.", file=sys.stderr)
    sys.exit(1)


def _relation_failed(exc: Exception) -> NoReturn:
    """Exit(1) on a refused relationship change or a missing related card.

    ``CardNotFound`` here may name a card other than the one the command was
    about (a ``--parent`` or the far end of a link), so its own id is used.
    """
    if isinstance(exc, service.CardNotFound):
        _not_found(exc.card_id)
    _fail(f"{exc}.")


def _parent_arg(value: str) -> int | str:
    """argparse type for ``edit --parent``: an epic id, or ``none`` to clear it."""
    if value.strip().lower() == NO_PARENT:
        return NO_PARENT
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected an epic id or 'none', got {value!r}"
        ) from None


def _require_epic_arg(conn, epic_id: int) -> None:
    """Exit(1) unless *epic_id* names an epic."""
    try:
        service.epic_members(conn, epic_id)
    except (service.CardNotFound, service.RelationError) as exc:
        _relation_failed(exc)


def _remind_epic(conn, card_id: int) -> None:
    """Note on stderr when *card_id*'s epic has no open members left.

    stderr so a ``--json`` caller's stdout stays one parseable document. The
    epic itself is never moved — its status is set by hand.
    """
    epic_id = service.epic_without_open_members(conn, card_id)
    if epic_id is None:
        return
    # All members dropped rather than finished suggests archiving, not completing.
    finished = any(m["status"] == DONE for m in service.epic_members(conn, epic_id))
    verb, why = (
        ("complete", "it's finished") if finished else ("archive", "it's dropped")
    )
    print(
        f"Note: epic #{epic_id} has no open members — "
        f"{verb} it with 'mc-tool-board {verb} {epic_id}' if {why}.",
        file=sys.stderr,
    )


def _note_closed_epic(conn, card_id: int) -> None:
    """Note on stderr when *card_id* inherited an epic that is done or archived.

    ``--from`` joins the origin's epic unasked, and an open card under a closed
    initiative is easy to miss — redirect it with ``edit --parent``.
    """
    card = service.get_card(conn, card_id)
    epic = card and card["parent"] and service.get_card(conn, card["parent"]["id"])
    if not epic or epic["status"] not in (DONE, ARCHIVED):
        return
    print(
        f"Note: #{card_id} joined epic #{epic['id']}, which is "
        f"{label(epic['status'])} — move it with "
        f"'mc-tool-board edit {card_id} --parent <epic|none>' if it belongs elsewhere.",
        file=sys.stderr,
    )


def _card_payload(conn, card_id: int) -> dict:
    """Return a card in the ``show --json`` shape (comments included)."""
    card = service.get_card(conn, card_id)
    if card is None:
        _not_found(card_id)
    card["comments"] = service.get_comments(conn, card_id)
    return card


def _print_card(conn, args, card_id: int, message: str) -> None:
    """Print *message*, or with ``--json`` the affected card instead.

    Mutating subcommands route their success output through here so scripted
    callers get the card back (same shape as ``show --json``) instead of
    having to parse ids out of prose.
    """
    if args.json:
        print(json.dumps(_card_payload(conn, card_id), indent=2))
    else:
        print(message)


# --- Card CRUD ---


def cmd_add(args):
    title = " ".join(args.title).strip()
    if not title:
        logger.warning("card title cannot be empty")
        print("Error: card title cannot be empty.", file=sys.stderr)
        sys.exit(1)

    if args.epic:
        if args.project:
            _fail("an epic belongs to no project; drop --project.")
        if args.parent is not None:
            _fail("an epic can't have a parent; drop --parent.")
        if args.origin is not None:
            _fail("an epic can't come from a card; drop --from.")
        project, kind, noun = None, EPIC, "Epic"
    else:
        project, kind, noun = args.project or get_project(), "card", "Card"
    # Left out, the epic is --from's to inherit (and none without it).
    parent = {}
    if args.parent is not None:
        parent["parent_id"] = None if args.parent == NO_PARENT else args.parent
    with connection() as conn:
        try:
            card_id = service.add_card(
                conn,
                project=project,
                title=title,
                description=args.description,
                priority=args.priority,
                kind=kind,
                origin_id=args.origin,
                **parent,
            )
        except (service.CardNotFound, service.RelationError) as exc:
            _relation_failed(exc)
        _print_card(
            conn, args, card_id, f"{noun} #{card_id} added ({args.priority}): {title}"
        )
        if args.origin is not None and args.parent is None:
            _note_closed_epic(conn, card_id)


def cmd_list(args):
    statuses = [args.status] if args.status else None
    session = args.session
    if args.mine:
        current = current_session()
        if current is None:
            _fail(
                f"--mine needs ${SESSION_ENV} and ${PID_ENV} (run inside Claude Code)."
            )
        session = current.session_id
    # A session's cards are its cards whichever directory it was asked from,
    # and an epic's members are its members whichever project they sit in.
    spans = bool(args.all or session or args.epic is not None)
    project = None if spans else get_project()
    with connection() as conn:
        if args.epic is not None:
            _require_epic_arg(conn, args.epic)
        cards = service.list_cards(
            conn,
            project=project,
            statuses=statuses,
            include_archived=args.archived,
            search=args.search,
            session=session,
            parent_id=args.epic,
            ready=args.ready,
            claimant=current.session_id if (current := current_session()) else None,
        )

    if args.json:
        print(json.dumps(cards, indent=2))
        return

    if not cards:
        print("No cards." if not args.all else "No cards on the board.")
        return

    _print_grouped(
        cards,
        show_project=spans,
        show_archived=args.archived or args.status == ARCHIVED,
    )


def _print_grouped(
    cards: list[dict], *, show_project: bool, show_archived: bool
) -> None:
    """Print cards grouped by column, one row each, in board order."""
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
            project = f" [{card['project']}]" if show_project else ""
            tags = "".join(f"  #{t}" for t in card["tags"])
            waiting = (
                "  waiting on " + ", ".join(f"#{i}" for i in card["waiting_on"])
                if card["waiting_on"]
                else ""
            )
            print(
                f"  [#{card['id']}] ({card['priority']}) {card['title']}"
                f"{project}{tags}{waiting}"
            )
        print()


def cmd_show(args):
    with connection() as conn:
        card = service.get_card(conn, args.id)
        if card is None:
            _not_found(args.id)
        comments = service.get_comments(conn, args.id)
        progress = (
            service.get_epic(conn, args.id)["progress"]
            if card["kind"] == EPIC
            else None
        )

    if args.json:
        card["comments"] = comments
        print(json.dumps(card, indent=2))
        return

    print(f"#{card['id']} ({card['priority']}) {card['title']}")
    if progress is not None:
        print(
            f"  epic   status: {label(card['status'])}   {export.progress_text(progress)}"
        )
    else:
        print(f"  project: {card['project']}   status: {label(card['status'])}")
    if card["parent"]:
        print(f"  epic: #{card['parent']['id']} {card['parent']['title']}")
    if card["blocked_by"]:
        # Every blocker, each with its status, so a link to a finished one
        # stays visible; an archived one gets a nudge to look again.
        nudge = (
            " — archived ones are worth another look"
            if card["archived_blockers"]
            else ""
        )
        print(f"  blocked by: {export.related_text(card['blocked_by'])}{nudge}")
    if card["blocks"]:
        print(f"  blocks: {export.related_text(card['blocks'])}")
    if card["created_by"]:
        print(f"  created by: {card['created_by']}")
    if card["tags"]:
        print(f"  tags: {', '.join(card['tags'])}")
    if card["sessions"]:
        labels = ", ".join(_session_label(b) for b in card["sessions"])
        print(f"  sessions: {labels}")
    if card["description"]:
        print(f"\nDescription:\n{card['description']}")
    if card["acceptance_criteria"]:
        print(f"\nAcceptance criteria:\n{card['acceptance_criteria']}")
    if card["completion_summary"]:
        print(f"\nCompletion summary:\n{card['completion_summary']}")
    if card["run"]:
        print("")
        print("\n".join(export.run_lines(card["run"])))
    if card["references"]:
        print(f"\nReferences ({len(card['references'])}):")
        for position, ref in enumerate(card["references"], 1):
            print(f"  {position}. {ref['label']}: {ref['value']}")
    if comments:
        print(f"\nComments ({len(comments)}):")
        for comment in comments:
            print(f"  [{comment['author']}] {comment['body']}")


def cmd_export(args):
    if args.id is not None and args.epic is not None:
        _fail("pass a card id or --epic, not both.")
    if args.epic is not None:
        board_filters = {
            "--all": args.all,
            "--project": args.project,
            "--status": args.status,
            "--archived": args.archived,
            "--search": args.search,
        }
        used = [flag for flag, value in board_filters.items() if value]
        if used:
            _fail(
                f"--epic exports the whole epic; {', '.join(used)} filter a board export."
            )
    with connection() as conn:
        if args.epic is not None:
            try:
                document = export.export_epic(conn, args.epic, fmt=args.format)
            except (service.CardNotFound, service.RelationError) as exc:
                _relation_failed(exc)
        elif args.id is not None:
            try:
                document = export.export_card(conn, args.id, fmt=args.format)
            except service.CardNotFound:
                _not_found(args.id)
        else:
            project = None if args.all else (args.project or get_project())
            statuses = [args.status] if args.status else None
            document = export.export_board(
                conn,
                fmt=args.format,
                project=project,
                statuses=statuses,
                include_archived=args.archived,
                search=args.search,
            )

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.write_text(document + "\n", encoding="utf-8")
        print(f"Exported to {out_path}")
    else:
        print(document)


def cmd_edit(args):
    # Any, not str: unpacked beside parent_id=, which a str-valued dict could shadow.
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.description is not None:
        fields["description"] = args.description
    if args.priority is not None:
        fields["priority"] = args.priority
    if args.acceptance is not None:
        fields["acceptance_criteria"] = args.acceptance
    if args.project is not None:
        project = args.project.strip()
        if not project:
            print("Error: --project cannot be blank.", file=sys.stderr)
            sys.exit(1)
        fields["project"] = project

    set_parent = args.parent is not None
    if not fields and not set_parent:
        print("Error: nothing to edit (pass at least one field).", file=sys.stderr)
        sys.exit(1)

    with connection() as conn:
        if service.get_card(conn, args.id) is None:
            _not_found(args.id)
        try:
            if set_parent:
                epic_id = None if args.parent == NO_PARENT else args.parent
                service.edit_card(conn, args.id, parent_id=epic_id, **fields)
            else:
                service.edit_card(conn, args.id, **fields)
        except (service.CardNotFound, service.RelationError) as exc:
            _relation_failed(exc)
        _print_card(conn, args, args.id, f"Card #{args.id} updated.")


def cmd_remove(args):
    with connection() as conn:
        # With --json the card is emitted as it was, so snapshot it first.
        payload = _card_payload(conn, args.id) if args.json else None
        try:
            service.remove_card(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)

    if payload is not None:
        print(json.dumps(payload, indent=2))
    else:
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
        _print_card(conn, args, args.id, f"Comment added to card #{args.id}.")


# --- Workflow verbs ---


def cmd_move(args):
    new_status = args.status  # argparse choices=ALL_STATUSES guarantees validity
    with connection() as conn:
        try:
            service.move_card(conn, args.id, new_status, session=current_session())
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id} → {label(new_status)}.")
        _remind_epic(conn, args.id)


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
        # An epic's criteria are optional: its members carry the contracts.
        if args.acceptance is None and not had_acceptance and card["kind"] != EPIC:
            print(
                f"Warning: card #{args.id} has no acceptance criteria.",
                file=sys.stderr,
            )
        _print_card(conn, args, args.id, f"Card #{args.id} → {label(REFINED)}.")


def cmd_next(args):
    """Print the next ready card; with --claim, move it to in_progress."""
    if args.epic is not None and args.project:
        _fail("pass --project or --epic, not both.")
    project = None if args.epic is not None else (args.project or get_project())
    with connection() as conn:
        try:
            card = service.next_refined(
                conn,
                project,
                claim=args.claim,
                session=current_session(),
                epic_id=args.epic,
            )
        except (service.CardNotFound, service.RelationError) as exc:
            _relation_failed(exc)

    if card is None:
        if args.json:
            print("null")
        else:
            scope = (
                f"in epic #{args.epic}" if args.epic is not None else f"for {project}"
            )
            print(
                f"No ready cards {scope} — none refined, or every refined "
                f"card is tagged blocked, waiting on an unfinished blocker, "
                f"or held by another session."
            )
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
        _print_card(conn, args, args.id, f"Card #{args.id} completed.")
        _remind_epic(conn, args.id)


def cmd_review(args):
    pr = (args.pr or "").strip()
    with connection() as conn:
        try:
            service.review_card(conn, args.id, pr=pr or None)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id} → {label(IN_REVIEW)}.")


def cmd_block(args):
    reason = " ".join(args.reason).strip()
    with connection() as conn:
        try:
            service.block_card(conn, args.id, reason=reason or None)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id} tagged 'blocked'.")


def cmd_unblock(args):
    with connection() as conn:
        try:
            service.unblock_card(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id}: 'blocked' tag removed.")


def cmd_tag(args):
    tag = args.tag.strip()
    if not tag:
        logger.warning("tag cannot be empty")
        print("Error: tag cannot be empty.", file=sys.stderr)
        sys.exit(1)

    with connection() as conn:
        try:
            service.add_tag(conn, args.id, tag)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id} tagged '{tag}'.")


def cmd_untag(args):
    tag = args.tag.strip()
    with connection() as conn:
        try:
            service.remove_tag(conn, args.id, tag)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id}: '{tag}' tag removed.")


def cmd_ref_add(args):
    ref_label = args.label.strip()
    value = " ".join(args.value).strip()
    if not ref_label:
        print("Error: reference label cannot be empty.", file=sys.stderr)
        sys.exit(1)
    if not value:
        print("Error: reference value cannot be empty.", file=sys.stderr)
        sys.exit(1)

    with connection() as conn:
        try:
            service.add_reference(conn, args.id, ref_label, value)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(
            conn, args, args.id, f"Card #{args.id}: added reference '{ref_label}'."
        )


def cmd_ref_remove(args):
    with connection() as conn:
        try:
            removed = service.remove_reference(conn, args.id, args.position)
        except service.CardNotFound:
            _not_found(args.id)

        if not removed:
            print(
                f"Error: card #{args.id} has no reference at position {args.position}.",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_card(
            conn, args, args.id, f"Card #{args.id}: removed reference {args.position}."
        )


def cmd_ref_list(args):
    with connection() as conn:
        card = service.get_card(conn, args.id)
        if card is None:
            _not_found(args.id)
        refs = card["references"]

    if args.json:
        print(json.dumps(refs, indent=2))
        return

    if not refs:
        print(f"Card #{args.id} has no references.")
        return

    print(f"References for card #{args.id}:")
    for position, ref in enumerate(refs, 1):
        print(f"  {position}. {ref['label']}: {ref['value']}")


# --- Playbook runs ---


def cmd_run_start(args):
    with connection() as conn:
        try:
            service.start_run(
                conn, args.id, args.playbook, args.steps, replace=args.replace
            )
        except service.CardNotFound:
            _not_found(args.id)
        except service.RunRefused as exc:
            _fail(f"{exc}.")
        _print_card(
            conn,
            args,
            args.id,
            f"Card #{args.id}: started run '{args.playbook.strip()}' "
            f"({len(args.steps)} steps).",
        )


def cmd_run_step(args):
    reason = " ".join(args.reason).strip() if args.reason else None
    with connection() as conn:
        try:
            position, name = service.set_step(
                conn, args.id, args.step, args.status, reason=reason
            )
        except service.CardNotFound:
            _not_found(args.id)
        except service.RunRefused as exc:
            _fail(f"{exc}.")
        _print_card(
            conn,
            args,
            args.id,
            f"Card #{args.id}: step {position} ({name}) → "
            f"{args.status.replace('_', ' ')}.",
        )


def cmd_run_end(args):
    with connection() as conn:
        try:
            service.end_run(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)
        except service.RunRefused as exc:
            _fail(f"{exc}.")
        _print_card(conn, args, args.id, f"Card #{args.id}: run ended.")


def cmd_run_show(args):
    with connection() as conn:
        try:
            run = service.get_run(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)

    if args.json:
        print(json.dumps(run, indent=2))
    elif run is None:
        print(f"Card #{args.id} has no open run.")
    else:
        print("\n".join(export.run_lines(run)))


def cmd_archive(args):
    with connection() as conn:
        try:
            service.archive_card(conn, args.id)
        except service.CardNotFound:
            _not_found(args.id)
        _print_card(conn, args, args.id, f"Card #{args.id} → {label(ARCHIVED)}.")
        _remind_epic(conn, args.id)


def cmd_bind(args):
    """Bind a Claude Code session (default: the current one) to an open card."""
    if args.session and args.pid is None:
        # Never pair another session's id with this process's pid: the binding
        # would live, die and follow a /clear with the wrong process.
        _fail("--session needs --pid (the pid of the Claude Code process serving it).")
    current = current_session()
    session_id = args.session or (current.session_id if current else None)
    pid = args.pid if args.pid is not None else (current.pid if current else None)
    if not session_id or pid is None:
        _fail(
            f"bind needs a session id and a pid: run inside Claude Code "
            f"(${SESSION_ENV}, ${PID_ENV}) or pass --session and --pid."
        )
    if pid <= 0:
        _fail("--pid must be a positive integer.")

    with connection() as conn:
        try:
            service.bind_session(conn, args.id, SessionRef(session_id, pid))
        except service.CardNotFound:
            _not_found(args.id)
        except service.CardClosed as exc:
            _fail(f"card #{args.id} is {label(exc.status)}; only open cards bind.")
        except service.RelationError as exc:
            _fail(f"{exc}.")
        _print_card(
            conn, args, args.id, f"Card #{args.id} bound to session {session_id[:8]}."
        )


def cmd_unbind(args):
    """Remove a session's binding (default: the current one) from a card."""
    current = current_session()
    session_id = args.session or (current.session_id if current else None)
    if not session_id:
        _fail(
            f"unbind needs a session id: run inside Claude Code (${SESSION_ENV}) "
            f"or pass --session."
        )

    with connection() as conn:
        try:
            removed = service.unbind_session(conn, args.id, session_id)
        except service.CardNotFound:
            _not_found(args.id)
        message = (
            f"Card #{args.id} unbound from session {session_id[:8]}."
            if removed
            else f"Card #{args.id} was not bound to session {session_id[:8]}."
        )
        _print_card(conn, args, args.id, message)


# --- Relationships ---


def cmd_link(args):
    with connection() as conn:
        try:
            service.add_link(conn, args.from_id, args.to_id, args.type)
        except (service.CardNotFound, service.RelationError) as exc:
            _relation_failed(exc)
        _print_card(
            conn, args, args.to_id, f"#{args.from_id} {args.type} #{args.to_id}."
        )


def cmd_unlink(args):
    with connection() as conn:
        if not service.remove_link(conn, args.from_id, args.to_id, args.type):
            _fail(f"#{args.from_id} doesn't {args.type.rstrip('s')} #{args.to_id}.")
        _print_card(
            conn,
            args,
            args.to_id,
            f"#{args.from_id} no longer {args.type} #{args.to_id}.",
        )


def cmd_epic_list(args):
    with connection() as conn:
        epics = service.list_epics(conn, include_done=args.done)

    if args.json:
        print(json.dumps(epics, indent=2))
        return
    if not epics:
        print("No epics.")
        return
    for epic in epics:
        print(
            f"[#{epic['id']}] ({epic['priority']}) {epic['title']} — "
            f"{label(epic['status'])} — {export.progress_text(epic['progress'])}"
        )


def cmd_epic_show(args):
    with connection() as conn:
        try:
            epic = service.get_epic(conn, args.id)
        except (service.CardNotFound, service.RelationError) as exc:
            _relation_failed(exc)
        epic["comments"] = service.get_comments(conn, args.id)

    if args.json:
        print(json.dumps(epic, indent=2))
        return
    print(f"#{epic['id']} ({epic['priority']}) {epic['title']}")
    print(
        f"  status: {label(epic['status'])}   {export.progress_text(epic['progress'])}"
    )
    if epic["description"]:
        print(f"\nDescription:\n{epic['description']}")
    print()
    if epic["members"]:
        _print_grouped(epic["members"], show_project=True, show_archived=False)
    else:
        print(
            "No members yet — add one with 'mc-tool-board edit N --parent "
            f"{epic['id']}'."
        )


def cmd_epic_promote(args):
    with connection() as conn:
        card = service.get_card(conn, args.id)
        if card is None:
            _not_found(args.id)
        try:
            service.promote_epic(conn, args.id)
        except service.RelationError as exc:
            _relation_failed(exc)
        _print_card(
            conn,
            args,
            args.id,
            f"Card #{args.id} is now an epic (was in project {card['project']}).",
        )


def _brief(cards: list[dict]) -> list[dict]:
    return [{"id": c["id"], "title": c["title"]} for c in cards]


_JIRA_KEY = re.compile(r"[A-Z][A-Z0-9]+-\d+")


def _jira_links(references: list[dict]) -> list[dict]:
    """A card's ``JIRA`` references as ``{"key", "url"}`` for the status bar.

    A full ``https://`` value is linked as it stands, keyed by the issue key
    in it. A bare key is linked under the ``jira-base-url`` setting, or gets
    ``url: None`` while that is unset (the bar shows it unlinked). Anything
    else under the label is skipped.
    """
    from mait_code import config

    base = config.get("jira-base-url").strip().rstrip("/")
    if not base.startswith("https://"):
        base = ""
    links: list[dict] = []
    for ref in references:
        if ref["label"].strip().lower() != "jira":
            continue
        value = ref["value"].strip()
        if value.startswith("https://"):
            found = _JIRA_KEY.search(value)
            links.append({"key": found.group() if found else value, "url": value})
        elif _JIRA_KEY.fullmatch(value):
            links.append(
                {"key": value, "url": f"{base}/browse/{value}" if base else None}
            )
    return links


def _session_brief(conn, session: str, project: str | None) -> dict:
    """What a status surface (the Claude Code mod) shows, in one payload.

    The session's bound cards (any project or open column) with their status,
    Jira links and open playbook run, the In
    Review cards (scoped like the counts) and the global inbox count.
    """
    from mait_code.tools.inbox import service as inbox_service
    from mait_code.tools.inbox.db import connection as inbox_connection

    with inbox_connection() as inbox_conn:
        inbox = inbox_service.count_items(inbox_conn)
    return {
        "bound": [
            {
                "id": card["id"],
                "title": card["title"],
                "status": card["status"],
                "jira": _jira_links(card["references"]),
                "run": card["run"],
            }
            for card in service.list_cards(conn, session=session)
        ],
        "in_review": _brief(
            service.list_cards(conn, project=project, statuses=[IN_REVIEW])
        ),
        "inbox": inbox,
    }


def cmd_summary(args):
    if args.session and not args.json:
        _fail("--session needs --json (it adds fields to the JSON summary).")
    project = args.project or (None if args.all else get_project())
    with connection() as conn:
        counts = service.summary_counts(conn, project=project)
        payload: dict = {"project": project, "counts": counts}
        if args.json and args.session:
            payload |= _session_brief(conn, args.session, project)

    if args.json:
        print(json.dumps(payload, indent=2))
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
    p_add.add_argument(
        "--epic", action="store_true", help="Add an epic (spans projects; no --project)"
    )
    p_add.add_argument(
        "--parent",
        type=_parent_arg,
        metavar="EPIC",
        help="Epic the card is in ('none' to drop the one --from would inherit)",
    )
    p_add.add_argument(
        "--from",
        dest="origin",
        type=int,
        metavar="N",
        help="Card this one was split from or follows up; inherits its epic",
    )
    p_add.add_argument("title", nargs="+", help="Card title")
    p_add.add_argument("--json", action="store_true", help="Emit the new card as JSON")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List cards grouped by column")
    p_list.add_argument("--all", action="store_true", help="Span all projects")
    p_list.add_argument("--status", choices=ALL_STATUSES, help="Filter to one column")
    p_list.add_argument("--archived", action="store_true", help="Include archived")
    p_list.add_argument(
        "--search",
        "-q",
        metavar="TEXT",
        help="Filter by title substring (case-insensitive)",
    )
    p_list_session = p_list.add_mutually_exclusive_group()
    p_list_session.add_argument(
        "--session", metavar="ID", help="Only cards bound to this Claude Code session"
    )
    p_list_session.add_argument(
        "--mine", action="store_true", help="Only cards bound to the current session"
    )
    p_list.add_argument(
        "--epic", type=int, metavar="ID", help="Only this epic's members (any project)"
    )
    p_list.add_argument(
        "--ready",
        action="store_true",
        help="Only ready cards (refined, not blocked, not waiting)",
    )
    p_list.add_argument("--json", action="store_true", help="Emit JSON")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show a card and its comments")
    p_show.add_argument("id", type=int, help="Card ID")
    p_show.add_argument("--json", action="store_true", help="Emit JSON")
    p_show.set_defaults(func=cmd_show)

    p_export = sub.add_parser(
        "export", help="Export a card or the board to markdown/JSON"
    )
    p_export.add_argument(
        "id", type=int, nargs="?", help="Card ID (omit to export the board)"
    )
    p_export.add_argument("--format", choices=export.FORMATS, default=export.MARKDOWN)
    p_export.add_argument("--out", help="Write to a file instead of stdout")
    p_export.add_argument(
        "--all", action="store_true", help="Span all projects (board export)"
    )
    p_export.add_argument("--project", help="Project (defaults to git root or cwd)")
    p_export.add_argument(
        "--status", choices=ALL_STATUSES, help="Filter to one column (board export)"
    )
    p_export.add_argument(
        "--archived", action="store_true", help="Include archived (board export)"
    )
    p_export.add_argument(
        "--search",
        "-q",
        metavar="TEXT",
        help="Filter by title substring (board export)",
    )
    p_export.add_argument(
        "--epic", type=int, metavar="ID", help="Export an epic and its members"
    )
    p_export.set_defaults(func=cmd_export)

    p_move = sub.add_parser("move", help="Move a card to a column")
    p_move.add_argument("id", type=int, help="Card ID")
    p_move.add_argument("status", choices=ALL_STATUSES, help="Target column")
    p_move.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_move.set_defaults(func=cmd_move)

    p_refine = sub.add_parser(
        "refine", help="Set description/acceptance and move to refined"
    )
    p_refine.add_argument("id", type=int, help="Card ID")
    p_refine.add_argument("--description", help="Card description")
    p_refine.add_argument("--acceptance", help="Acceptance criteria")
    p_refine.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_refine.set_defaults(func=cmd_refine)

    p_next = sub.add_parser("next", help="Show (or --claim) the next ready card")
    p_next.add_argument("--project", help="Project (defaults to git root or cwd)")
    p_next.add_argument(
        "--epic", type=int, metavar="ID", help="Search this epic's members instead"
    )
    p_next.add_argument("--claim", action="store_true", help="Move it to in_progress")
    p_next.add_argument("--json", action="store_true", help="Emit JSON")
    p_next.set_defaults(func=cmd_next)

    p_complete = sub.add_parser("complete", help="Complete a card with a summary")
    p_complete.add_argument("id", type=int, help="Card ID")
    p_complete.add_argument("--summary", nargs="+", default=[], help="Handoff summary")
    p_complete.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_complete.set_defaults(func=cmd_complete)

    p_review = sub.add_parser(
        "review", help="Move a card to in_review, optionally recording its PR"
    )
    p_review.add_argument("id", type=int, help="Card ID")
    p_review.add_argument("--pr", help="Pull request URL (added as a 'PR' reference)")
    p_review.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_review.set_defaults(func=cmd_review)

    p_block = sub.add_parser(
        "block", help="Tag a card 'blocked' in place, optionally with a reason"
    )
    p_block.add_argument("id", type=int, help="Card ID")
    p_block.add_argument("reason", nargs="*", help="Reason (recorded as a comment)")
    p_block.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_block.set_defaults(func=cmd_block)

    p_unblock = sub.add_parser("unblock", help="Remove the 'blocked' tag from a card")
    p_unblock.add_argument("id", type=int, help="Card ID")
    p_unblock.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_unblock.set_defaults(func=cmd_unblock)

    p_tag = sub.add_parser("tag", help="Add a tag to a card")
    p_tag.add_argument("id", type=int, help="Card ID")
    p_tag.add_argument("tag", help="Tag to add")
    p_tag.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_tag.set_defaults(func=cmd_tag)

    p_untag = sub.add_parser("untag", help="Remove a tag from a card")
    p_untag.add_argument("id", type=int, help="Card ID")
    p_untag.add_argument("tag", help="Tag to remove")
    p_untag.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_untag.set_defaults(func=cmd_untag)

    p_ref = sub.add_parser("ref", help="Manage a card's references (label→value links)")
    ref_sub = p_ref.add_subparsers(dest="ref_command", required=True)

    p_ref_add = ref_sub.add_parser("add", help="Add a reference to a card")
    p_ref_add.add_argument("id", type=int, help="Card ID")
    p_ref_add.add_argument("label", help="Reference label (e.g. JIRA, PR)")
    p_ref_add.add_argument(
        "value", nargs="+", help="Reference value (URL, file:// path, or bare ID)"
    )
    p_ref_add.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_ref_add.set_defaults(func=cmd_ref_add)

    p_ref_remove = ref_sub.add_parser("remove", help="Remove a reference by position")
    p_ref_remove.add_argument("id", type=int, help="Card ID")
    p_ref_remove.add_argument(
        "position", type=int, help="1-based position (see 'ref list')"
    )
    p_ref_remove.add_argument(
        "--json", action="store_true", help="Emit the card as JSON"
    )
    p_ref_remove.set_defaults(func=cmd_ref_remove)

    p_ref_list = ref_sub.add_parser("list", help="List a card's references")
    p_ref_list.add_argument("id", type=int, help="Card ID")
    p_ref_list.add_argument("--json", action="store_true", help="Emit JSON")
    p_ref_list.set_defaults(func=cmd_ref_list)

    p_run = sub.add_parser("run", help="Record a playbook run's steps on a card")
    run_sub = p_run.add_subparsers(dest="run_command", required=True)

    p_run_start = run_sub.add_parser(
        "start", help="Start a run: its ordered steps, all pending"
    )
    p_run_start.add_argument("id", type=int, help="Card ID")
    p_run_start.add_argument(
        "--playbook", required=True, help="The playbook's name (e.g. work)"
    )
    p_run_start.add_argument(
        "--steps", nargs="+", required=True, metavar="NAME", help="Step names, in order"
    )
    p_run_start.add_argument(
        "--replace", action="store_true", help="End the card's open run first"
    )
    p_run_start.add_argument(
        "--json", action="store_true", help="Emit the card as JSON"
    )
    p_run_start.set_defaults(func=cmd_run_start)

    p_run_step = run_sub.add_parser("step", help="Set one step's status")
    p_run_step.add_argument("id", type=int, help="Card ID")
    p_run_step.add_argument("step", help="1-based position or exact step name")
    p_run_step.add_argument("status", choices=STEP_STATUSES, help="New status")
    p_run_step.add_argument(
        "--reason",
        nargs="+",
        help=f"Why ({STEP_SKIPPED}: required; {STEP_PAUSED}: optional)",
    )
    p_run_step.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_run_step.set_defaults(func=cmd_run_step)

    p_run_end = run_sub.add_parser("end", help="End the card's open run")
    p_run_end.add_argument("id", type=int, help="Card ID")
    p_run_end.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_run_end.set_defaults(func=cmd_run_end)

    p_run_show = run_sub.add_parser("show", help="Show the card's open run")
    p_run_show.add_argument("id", type=int, help="Card ID")
    p_run_show.add_argument(
        "--json", action="store_true", help="Emit the run as JSON (null if none)"
    )
    p_run_show.set_defaults(func=cmd_run_show)

    p_bind = sub.add_parser("bind", help="Bind a Claude Code session to an open card")
    p_bind.add_argument("id", type=int, help="Card ID")
    p_bind.add_argument(
        "--session", metavar="ID", help=f"Session id (default: ${SESSION_ENV})"
    )
    p_bind.add_argument(
        "--pid", type=int, help=f"Claude Code process id (default: ${PID_ENV})"
    )
    p_bind.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_bind.set_defaults(func=cmd_bind)

    p_unbind = sub.add_parser("unbind", help="Remove a session's binding from a card")
    p_unbind.add_argument("id", type=int, help="Card ID")
    p_unbind.add_argument(
        "--session", metavar="ID", help=f"Session id (default: ${SESSION_ENV})"
    )
    p_unbind.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_unbind.set_defaults(func=cmd_unbind)

    p_archive = sub.add_parser("archive", help="Archive a card (hide it)")
    p_archive.add_argument("id", type=int, help="Card ID")
    p_archive.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_archive.set_defaults(func=cmd_archive)

    p_comment = sub.add_parser("comment", help="Append a comment to a card")
    p_comment.add_argument("id", type=int, help="Card ID")
    p_comment.add_argument("--author", choices=AUTHORS, default="me")
    p_comment.add_argument("body", nargs="+", help="Comment text")
    p_comment.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_comment.set_defaults(func=cmd_comment)

    p_edit = sub.add_parser("edit", help="Edit card fields")
    p_edit.add_argument("id", type=int, help="Card ID")
    p_edit.add_argument("--title", help="New title")
    p_edit.add_argument("--description", help="New description")
    p_edit.add_argument("--priority", choices=PRIORITIES, help="New priority")
    p_edit.add_argument("--acceptance", help="New acceptance criteria")
    p_edit.add_argument("--project", help="New project")
    p_edit.add_argument(
        "--parent",
        type=_parent_arg,
        metavar="EPIC|none",
        help="Epic the card is in, or 'none' to clear it",
    )
    p_edit.add_argument("--json", action="store_true", help="Emit the card as JSON")
    p_edit.set_defaults(func=cmd_edit)

    p_link = sub.add_parser("link", help="Record that one card blocks another")
    p_link.add_argument("from_id", type=int, metavar="A", help="The blocking card")
    p_link.add_argument("type", choices=LINK_TYPES, help="Link type")
    p_link.add_argument("to_id", type=int, metavar="B", help="The card that waits")
    p_link.add_argument("--json", action="store_true", help="Emit card B as JSON")
    p_link.set_defaults(func=cmd_link)

    p_unlink = sub.add_parser("unlink", help="Remove a link between two cards")
    p_unlink.add_argument("from_id", type=int, metavar="A", help="The blocking card")
    p_unlink.add_argument("type", choices=LINK_TYPES, help="Link type")
    p_unlink.add_argument("to_id", type=int, metavar="B", help="The card that waits")
    p_unlink.add_argument("--json", action="store_true", help="Emit card B as JSON")
    p_unlink.set_defaults(func=cmd_unlink)

    p_epic = sub.add_parser("epic", help="List, show or promote epics")
    epic_sub = p_epic.add_subparsers(dest="epic_command", required=True)

    p_epic_list = epic_sub.add_parser("list", help="Epics with member progress")
    p_epic_list.add_argument("--done", action="store_true", help="Include done epics")
    p_epic_list.add_argument("--json", action="store_true", help="Emit JSON")
    p_epic_list.set_defaults(func=cmd_epic_list)

    p_epic_show = epic_sub.add_parser("show", help="An epic and its members")
    p_epic_show.add_argument("id", type=int, help="Epic ID")
    p_epic_show.add_argument("--json", action="store_true", help="Emit JSON")
    p_epic_show.set_defaults(func=cmd_epic_show)

    p_epic_promote = epic_sub.add_parser(
        "promote", help="Turn an existing card into an epic"
    )
    p_epic_promote.add_argument("id", type=int, help="Card ID")
    p_epic_promote.add_argument(
        "--json", action="store_true", help="Emit the epic as JSON"
    )
    p_epic_promote.set_defaults(func=cmd_epic_promote)

    p_remove = sub.add_parser("remove", help="Delete a card permanently")
    p_remove.add_argument("id", type=int, help="Card ID")
    p_remove.add_argument(
        "--json", action="store_true", help="Emit the removed card as JSON"
    )
    p_remove.set_defaults(func=cmd_remove)

    p_summary = sub.add_parser(
        "summary", help="Per-column counts (used by the session hook)"
    )
    p_summary.add_argument("--all", action="store_true", help="Span all projects")
    p_summary.add_argument("--project", help="Project (defaults to git root or cwd)")
    p_summary.add_argument(
        "--session",
        metavar="ID",
        help="Add this session's bound cards, the In Review cards and the inbox "
        "count (requires --json)",
    )
    p_summary.add_argument("--json", action="store_true", help="Emit JSON")
    p_summary.set_defaults(func=cmd_summary)

    args = parser.parse_args()
    args.func(args)
