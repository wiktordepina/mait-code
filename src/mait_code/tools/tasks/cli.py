"""CLI tool for tasks — add, list, complete, remove, and check open tasks."""

import argparse
import logging
import sys
from datetime import datetime, timezone

from mait_code.logging import log_invocation, setup_logging

from mait_code.tools.tasks.db import ensure_project, get_connection, get_project

logger = logging.getLogger(__name__)

PRIORITIES = ("low", "medium", "high")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cmd_add(args):
    title = " ".join(args.title)
    if not title.strip():
        logger.error("task title cannot be empty")
        print("Error: task title cannot be empty.", file=sys.stderr)
        sys.exit(1)

    priority = args.priority
    if priority not in PRIORITIES:
        print(f"Error: priority must be one of {PRIORITIES}.", file=sys.stderr)
        sys.exit(1)

    project = get_project()
    conn = get_connection()
    try:
        ensure_project(conn, project)
        cursor = conn.execute(
            "INSERT INTO tasks (project, title, priority, created_at) VALUES (?, ?, ?, ?)",
            (project, title.strip(), priority, _now().isoformat()),
        )
        conn.commit()
        task_id = cursor.lastrowid
    finally:
        conn.close()

    print(f"Task #{task_id} added ({priority}): {title.strip()}")


def cmd_list(args):
    project = get_project()
    conn = get_connection()
    try:
        ensure_project(conn, project)
        if args.all:
            rows = conn.execute(
                "SELECT id, title, priority, status, completed_at FROM tasks "
                "WHERE project = ? ORDER BY status, "
                "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id",
                (project,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, priority, status, completed_at FROM tasks "
                "WHERE project = ? AND status = 'open' ORDER BY "
                "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id",
                (project,),
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No tasks." if not args.all else "No tasks for this project.")
        return

    open_tasks = [r for r in rows if r[3] == "open"]
    done_tasks = [r for r in rows if r[3] == "done"]

    if open_tasks:
        print(f"Open tasks ({len(open_tasks)}):\n")
        for tid, title, priority, _status, _completed in open_tasks:
            print(f"  [#{tid}] ({priority}) {title}")
        print()

    if done_tasks:
        print(f"Completed ({len(done_tasks)}):\n")
        for tid, title, priority, _status, completed_at in done_tasks:
            completed = datetime.fromisoformat(completed_at).strftime("%Y-%m-%d")
            print(f"  [#{tid}] ({priority}) {title} — done {completed}")
        print()


def cmd_done(args):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (args.id,)
        ).fetchone()

        if row is None:
            logger.error("task #%d not found", args.id)
            print(f"Error: task #{args.id} not found.", file=sys.stderr)
            sys.exit(1)

        if row[0] == "done":
            print(f"Task #{args.id} is already completed.")
            return

        conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
            (_now().isoformat(), args.id),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"Task #{args.id} completed.")


def cmd_remove(args):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (args.id,)
        ).fetchone()

        if row is None:
            logger.error("task #%d not found", args.id)
            print(f"Error: task #{args.id} not found.", file=sys.stderr)
            sys.exit(1)

        conn.execute("DELETE FROM tasks WHERE id = ?", (args.id,))
        conn.commit()
    finally:
        conn.close()

    print(f"Task #{args.id} removed.")


def cmd_check(args):
    """List open tasks for current project. Used by session_start hook."""
    project = args.project if args.project else get_project()
    conn = get_connection()
    try:
        ensure_project(conn, project)
        rows = conn.execute(
            "SELECT id, title, priority FROM tasks "
            "WHERE project = ? AND status = 'open' ORDER BY "
            "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id",
            (project,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return

    print(f"You have {len(rows)} open task(s):\n")
    for tid, title, priority in rows:
        print(f"  [#{tid}] ({priority}) {title}")


def cmd_list_all(_args):
    """List open tasks across all projects."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT t.id, t.project, t.title, t.priority FROM tasks t "
            "WHERE t.status = 'open' ORDER BY t.project, "
            "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, t.id",
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No open tasks across any project.")
        return

    current_project = None
    for tid, project, title, priority in rows:
        if project != current_project:
            if current_project is not None:
                print()
            print(f"{project}:")
            current_project = project
        print(f"  [#{tid}] ({priority}) {title}")
    print()


def cmd_projects(_args):
    """List all registered projects."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT name, path, github_url, added_at FROM projects ORDER BY name",
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No projects registered yet.")
        return

    print(f"Registered projects ({len(rows)}):\n")
    for name, path, github_url, added_at in rows:
        print(f"  {name}")
        print(f"    path: {path}")
        if github_url:
            print(f"    github: {github_url}")
        print(f"    added: {added_at[:10]}")
        print()


@log_invocation(name="mc-tool-tasks")
def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="mc-tool-tasks", description="Project tasks CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a task")
    p_add.add_argument(
        "--priority",
        choices=PRIORITIES,
        default="medium",
        help="Priority (low/medium/high, default: medium)",
    )
    p_add.add_argument("title", nargs="+", help="Task title")
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = sub.add_parser("list", help="List open tasks")
    p_list.add_argument(
        "--all", action="store_true", help="Include completed tasks"
    )
    p_list.set_defaults(func=cmd_list)

    # done
    p_done = sub.add_parser("done", help="Mark a task as completed")
    p_done.add_argument("id", type=int, help="Task ID")
    p_done.set_defaults(func=cmd_done)

    # remove
    p_remove = sub.add_parser("remove", help="Remove a task")
    p_remove.add_argument("id", type=int, help="Task ID")
    p_remove.set_defaults(func=cmd_remove)

    # check (for hooks)
    p_check = sub.add_parser("check", help="Check open tasks for current project")
    p_check.add_argument(
        "--project", help="Project path (defaults to git root or cwd)"
    )
    p_check.set_defaults(func=cmd_check)

    # list-all
    p_list_all = sub.add_parser("list-all", help="List open tasks across all projects")
    p_list_all.set_defaults(func=cmd_list_all)

    # projects
    p_projects = sub.add_parser("projects", help="List all registered projects")
    p_projects.set_defaults(func=cmd_projects)

    args = parser.parse_args()
    args.func(args)
