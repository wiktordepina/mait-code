"""CLI tool for reminders — set, list, dismiss, and check overdue."""

import argparse
import logging
import sys
from datetime import datetime, timezone

import dateparser

from mait_code.logging import log_invocation, setup_logging

from mait_code.tools.reminders.db import connection
from mait_code.tools.reminders.service import (
    active_reminders,
    dismissed_reminders,
    overdue_reminders,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_when(when_str: str) -> datetime | None:
    parsed = dateparser.parse(
        when_str,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc)


def cmd_set(args):
    when_str = args.when
    what = " ".join(args.what)

    if not what.strip():
        logger.warning("reminder content cannot be empty")
        print("Error: reminder content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    due = _parse_when(when_str)
    if due is None:
        logger.warning("could not parse time '%s'", when_str)
        print(f"Error: could not parse time '{when_str}'.", file=sys.stderr)
        sys.exit(1)

    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
            (what.strip(), due.isoformat(), _now().isoformat()),
        )
        conn.commit()
        reminder_id = cursor.lastrowid

    print(
        f"Reminder #{reminder_id} set for "
        f"{due.strftime('%Y-%m-%d %H:%M %Z')}: {what.strip()}"
    )


def cmd_list(args):
    with connection() as conn:
        overdue, upcoming = active_reminders(conn)
        dismissed = dismissed_reminders(conn) if args.all else []

    if not (overdue or upcoming) and not dismissed:
        print("No active reminders.")
        return

    if overdue:
        print(f"OVERDUE ({len(overdue)}):\n")
        for r in overdue:
            print(f"  [#{r['id']}] {r['due'].strftime('%Y-%m-%d %H:%M')} — {r['what']}")
        print()

    if upcoming:
        print(f"Upcoming ({len(upcoming)}):\n")
        for r in upcoming:
            print(f"  [#{r['id']}] {r['due'].strftime('%Y-%m-%d %H:%M')} — {r['what']}")
        print()

    if dismissed:
        print(f"Dismissed ({len(dismissed)}):\n")
        for r in dismissed:
            print(f"  [#{r['id']}] {r['due'].strftime('%Y-%m-%d %H:%M')} — {r['what']}")
        print()


def cmd_dismiss(args):
    with connection() as conn:
        row = conn.execute(
            "SELECT dismissed FROM reminders WHERE id = ?", (args.id,)
        ).fetchone()

        if row is None:
            logger.warning("reminder #%d not found", args.id)
            print(f"Error: reminder #{args.id} not found.", file=sys.stderr)
            sys.exit(1)

        if row[0]:
            print(f"Reminder #{args.id} is already dismissed.")
            return

        conn.execute(
            "UPDATE reminders SET dismissed = 1, dismissed_at = ? WHERE id = ?",
            (_now().isoformat(), args.id),
        )
        conn.commit()

    print(f"Reminder #{args.id} dismissed.")


def cmd_check(_args):
    """Print any overdue reminders, and publish them outward via the Bridge.

    Publishing is a no-op unless the Bridge is enabled (it short-circuits before
    any network access), so this stays safe to run from a hook on any machine.
    """
    from mait_code.bridge.service import publish_due_reminders

    publish_due_reminders()

    with connection() as conn:
        overdue = overdue_reminders(conn)

    if not overdue:
        return

    print(f"You have {len(overdue)} overdue reminder(s):\n")
    for r in overdue:
        print(f"  [#{r['id']}] {r['due'].strftime('%Y-%m-%d %H:%M')} — {r['what']}")
    print("\nUse `mc-tool-reminders dismiss <id>` to dismiss.")


@log_invocation(name="mc-tool-reminders")
def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="mc-tool-reminders", description="Reminders CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # set
    p_set = sub.add_parser("set", help="Set a reminder")
    p_set.add_argument(
        "when", help="When (e.g. 'in 2 hours', 'tomorrow 9am', '2026-03-10')"
    )
    p_set.add_argument("what", nargs="+", help="Reminder content")
    p_set.set_defaults(func=cmd_set)

    # list
    p_list = sub.add_parser("list", help="List active reminders")
    p_list.add_argument(
        "--all", action="store_true", help="Include dismissed reminders"
    )
    p_list.set_defaults(func=cmd_list)

    # dismiss
    p_dismiss = sub.add_parser("dismiss", help="Dismiss a reminder")
    p_dismiss.add_argument("id", type=int, help="Reminder ID")
    p_dismiss.set_defaults(func=cmd_dismiss)

    # check (for hooks)
    p_check = sub.add_parser("check", help="Check for overdue reminders")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    args.func(args)
