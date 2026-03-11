"""Shared project/branch context detection.

Provides functions to detect the current git project and branch,
used by memory, tasks, and hooks for scope-aware operations.
"""

import subprocess
from pathlib import Path

# Branches that are considered "default" — work on these is project-scoped, not branch-scoped.
DEFAULT_BRANCHES = {"main", "master"}


def get_project() -> str | None:
    """Return the current project identifier (basename of git root or cwd).

    Returns None only if cwd resolution fails (extremely unlikely).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return Path.cwd().name


def get_branch() -> str | None:
    """Return the current git branch name, or None.

    Returns None if:
    - Not in a git repo
    - On a detached HEAD
    - On a default branch (main/master) — work there is project-scoped
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch == "HEAD":
                return None  # Detached HEAD
            if branch in DEFAULT_BRANCHES:
                return None  # Default branch — project-scoped
            return branch
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_context() -> dict:
    """Return current project and branch context.

    Returns:
        {"project": str|None, "branch": str|None}
    """
    return {"project": get_project(), "branch": get_branch()}
