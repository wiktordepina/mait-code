"""CLI tool for reminders — set, list, dismiss, and check overdue."""

import argparse
import sys
from datetime import datetime, timezone

import dateparser

from mait_code.tools.reminders.db import get_connection


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
        print("Error: reminder content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    due = _parse_when(when_str)
    if due is None:
        print(f"Error: could not parse time '{when_str}'.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
            (what.strip(), due.isoformat(), _now().isoformat()),
        )
        conn.commit()
        reminder_id = cursor.lastrowid
    finally:
        conn.close()

    print(
        f"Reminder #{reminder_id} set for "
        f"{due.strftime('%Y-%m-%d %H:%M %Z')}: {what.strip()}"
    )


def cmd_list(args):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, what, due, dismissed FROM reminders ORDER BY due"
        ).fetchall()
    finally:
        conn.close()

    active = [(r[0], r[1], r[2]) for r in rows if not r[3]]
    dismissed = [(r[0], r[1], r[2]) for r in rows if r[3]]

    if not active and not (args.all and dismissed):
        print("No active reminders.")
        return

    now = _now()
    overdue = []
    upcoming = []
    for rid, what, due_str in active:
        due = datetime.fromisoformat(due_str)
        if due <= now:
            overdue.append((rid, what, due))
        else:
            upcoming.append((rid, what, due))

    if overdue:
        print(f"OVERDUE ({len(overdue)}):\n")
        for rid, what, due in overdue:
            print(f"  [#{rid}] {due.strftime('%Y-%m-%d %H:%M')} — {what}")
        print()

    if upcoming:
        print(f"Upcoming ({len(upcoming)}):\n")
        for rid, what, due in upcoming:
            print(f"  [#{rid}] {due.strftime('%Y-%m-%d %H:%M')} — {what}")
        print()

    if args.all and dismissed:
        print(f"Dismissed ({len(dismissed)}):\n")
        for rid, what, due_str in dismissed:
            due = datetime.fromisoformat(due_str)
            print(f"  [#{rid}] {due.strftime('%Y-%m-%d %H:%M')} — {what}")
        print()


def cmd_dismiss(args):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT dismissed FROM reminders WHERE id = ?", (args.id,)
        ).fetchone()

        if row is None:
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
    finally:
        conn.close()

    print(f"Reminder #{args.id} dismissed.")


def cmd_check(_args):
    """Check for overdue reminders. Used by session_start hook."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, what, due FROM reminders "
            "WHERE dismissed = 0 AND due <= ? ORDER BY due",
            (_now().isoformat(),),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return

    print(f"You have {len(rows)} overdue reminder(s):\n")
    for rid, what, due_str in rows:
        due = datetime.fromisoformat(due_str)
        print(f"  [#{rid}] {due.strftime('%Y-%m-%d %H:%M')} — {what}")
    print("\nUse `mc-tool-reminders dismiss <id>` to dismiss.")


def main():
    parser = argparse.ArgumentParser(prog="mc-tool-reminders", description="Reminders CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # set
    p_set = sub.add_parser("set", help="Set a reminder")
    p_set.add_argument("when", help="When (e.g. 'in 2 hours', 'tomorrow 9am', '2026-03-10')")
    p_set.add_argument("what", nargs="+", help="Reminder content")
    p_set.set_defaults(func=cmd_set)

    # list
    p_list = sub.add_parser("list", help="List active reminders")
    p_list.add_argument("--all", action="store_true", help="Include dismissed reminders")
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
