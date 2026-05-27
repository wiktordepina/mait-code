"""Shared project/branch context detection.

Provides functions that detect the current git project and branch, used by
memory, tasks, and hooks for scope-aware operations.
"""

import json
import os
import subprocess
from pathlib import Path

__all__ = [
    "DEFAULT_BRANCHES",
    "canonical_project",
    "get_branch",
    "get_context",
    "get_project",
    "load_project_aliases",
]

# Branches that are considered "default" — work on these is project-scoped, not branch-scoped.
DEFAULT_BRANCHES = {"main", "master"}


def get_project() -> str | None:
    """Return the current project identifier (basename of git root or cwd).

    The raw slug is resolved through the project-alias map (see
    :func:`canonical_project`) so a renamed working directory maps back to its
    canonical project.

    Returns:
        The canonical project identifier, or ``None`` only if cwd resolution
        fails (extremely unlikely).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return canonical_project(Path(result.stdout.strip()).name)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return canonical_project(Path.cwd().name)


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


_PROJECT_ALIASES_FILENAME = "project-aliases.json"
_alias_cache: dict[str, dict[str, str]] = {}


def load_project_aliases() -> dict[str, str]:
    """Load the project-alias map from the mait-code data directory.

    The map lives at ``project-aliases.json`` in the data directory and maps an
    old or alternate project slug to its canonical form, e.g.
    ``{"h-cc-bridge": "hermes-cc-bridge"}``. A missing or malformed file yields
    an empty map. The result is cached per data directory for the process
    lifetime.

    Returns:
        A mapping of alias slug to canonical slug (possibly empty).
    """
    key = os.environ.get(
        "MAIT_CODE_DATA_DIR", str(Path.home() / ".claude" / "mait-code-data")
    )
    cached = _alias_cache.get(key)
    if cached is None:
        try:
            data = json.loads((Path(key) / _PROJECT_ALIASES_FILENAME).read_text())
            cached = (
                {str(k): str(v) for k, v in data.items()}
                if isinstance(data, dict)
                else {}
            )
        except (OSError, json.JSONDecodeError):
            cached = {}
        _alias_cache[key] = cached
    return cached


def canonical_project(project: str | None) -> str | None:
    """Resolve a project slug to its canonical form via the alias map.

    Args:
        project: A project slug, or ``None``.

    Returns:
        The canonical slug when ``project`` is a known alias, otherwise
        ``project`` unchanged. ``None`` passes through.
    """
    if project is None:
        return None
    return load_project_aliases().get(project, project)
