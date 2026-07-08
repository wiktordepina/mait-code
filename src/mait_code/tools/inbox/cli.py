"""CLI tool for the quick-capture inbox — capture now, triage later.

A single frictionless holding pen (``inbox.db``) for thoughts you don't want to
classify upfront. One verb (``add``) dumps an item; the ``/triage`` skill later
routes each out to the board, tasks, decisions, or memory and removes it,
keeping the inbox near-empty.

The handlers here are thin: argument parsing, the not-found/exit helper, and
presentation (text vs ``--json``). Every query and mutation lives in
:mod:`mait_code.tools.inbox.service`.
"""

import argparse
import json
import logging
import sys
from typing import NoReturn

from mait_code.logging import log_invocation, setup_logging
from mait_code.tools.inbox import service
from mait_code.tools.inbox.db import connection, get_project

logger = logging.getLogger(__name__)


def _not_found(item_id: int) -> NoReturn:
    """Print a not-found error to stderr and exit(1)."""
    logger.warning("inbox item #%d not found", item_id)
    print(f"Error: inbox item #{item_id} not found.", file=sys.stderr)
    sys.exit(1)


def cmd_add(args):
    body = " ".join(args.body).strip()
    if not body:
        logger.warning("inbox item cannot be empty")
        print("Error: inbox item cannot be empty.", file=sys.stderr)
        sys.exit(1)

    project = get_project()
    with connection() as conn:
        item_id = service.add_item(conn, body=body, project=project)

    print(f"Captured #{item_id}: {body}")


def cmd_list(args):
    with connection() as conn:
        items = service.list_items(conn)

    if args.json:
        print(json.dumps(items, indent=2))
        return

    if not items:
        print("Inbox is empty.")
        return

    print(f"Inbox ({len(items)}):")
    for item in items:
        hint = f"  [{item['project']}]" if item["project"] else ""
        print(f"  [#{item['id']}] {item['body']}{hint}")


def cmd_remove(args):
    with connection() as conn:
        try:
            service.remove_item(conn, args.id)
        except service.ItemNotFound:
            _not_found(args.id)

    print(f"Inbox item #{args.id} removed.")


def cmd_count(args):
    """Print the inbox item count (used by the session-start hook)."""
    with connection() as conn:
        print(service.count_items(conn))


def cmd_drain(args):
    """Pull captures from the Bridge channel into the inbox.

    Off by default: does nothing unless the Bridge gate is enabled (configure
    it in the Bridge screen of `mait-code`). Reports what happened without
    leaking a transport error as a stack trace.
    """
    from mait_code.bridge.service import run_drain

    outcome = run_drain()
    if outcome.status == "disabled":
        print("Bridge is disabled — enable it in `mait-code` settings to drain.")
    elif outcome.status == "unconfigured":
        print(f"Bridge is not configured: {outcome.detail}")
    elif outcome.status == "error":
        print(f"Bridge drain failed: {outcome.detail}", file=sys.stderr)
        sys.exit(1)
    elif outcome.count:
        print(f"Drained {outcome.count} item(s) into the inbox.")
    else:
        print("Nothing new to drain.")


@log_invocation(name="mc-tool-inbox")
def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="mc-tool-inbox", description="Quick-capture inbox CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Capture an item to the inbox")
    p_add.add_argument("body", nargs="+", help="The thought to capture")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List captured items (oldest first)")
    p_list.add_argument("--json", action="store_true", help="Emit JSON")
    p_list.set_defaults(func=cmd_list)

    p_remove = sub.add_parser("remove", help="Remove an item (triage drains it out)")
    p_remove.add_argument("id", type=int, help="Item ID")
    p_remove.set_defaults(func=cmd_remove)

    p_count = sub.add_parser("count", help="Print the inbox count (used by hooks)")
    p_count.set_defaults(func=cmd_count)

    p_drain = sub.add_parser(
        "drain", help="Pull captures from the Bridge into the inbox (if enabled)"
    )
    p_drain.set_defaults(func=cmd_drain)

    args = parser.parse_args()
    args.func(args)
