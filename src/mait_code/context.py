"""Shared project/branch context detection.

Provides functions that detect the current git project and branch, used by
memory, tasks, and hooks for scope-aware operations.
"""

import subprocess
from pathlib import Path

__all__ = [
    "DEFAULT_BRANCHES",
    "get_branch",
    "get_context",
    "get_project",
]

# Branches that are considered "default" — work on these is project-scoped, not branch-scoped.
DEFAULT_BRANCHES = {"main", "master"}


def get_project() -> str | None:
    """Return the current project identifier (basename of git root or cwd).

    Returns:
        The project identifier, or ``None`` only if cwd resolution fails
        (extremely unlikely).
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
    """Return the current git branch name, or ``None``.

    Returns:
        The branch name, or ``None`` when not in a git repo, on a detached
        HEAD, or on a default branch (``main``/``master``) — work on default
        branches is treated as project-scoped rather than branch-scoped.
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
    """Return the current project and branch context.

    Returns:
        A dict with keys ``"project"`` and ``"branch"``, each mapping to a
        string or ``None``.
    """
    return {"project": get_project(), "branch": get_branch()}
