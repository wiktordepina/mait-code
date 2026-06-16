"""Shared project/branch context detection.

Provides functions that detect the current git project and branch, used by
memory, tasks, and hooks for scope-aware operations.
"""

import json
import re
import subprocess
from pathlib import Path

from mait_code.config import data_dir, get_int

__all__ = [
    "DEFAULT_BRANCHES",
    "canonical_project",
    "get_branch",
    "get_context",
    "get_project",
    "load_project_aliases",
    "munge_path",
]

# Branches that are considered "default" — work on these is project-scoped, not branch-scoped.
DEFAULT_BRANCHES = {"main", "master"}

#: Claude Code munges a path into a project-dir name by replacing every
#: character that is not an ASCII letter or digit with ``-``. A path separator,
#: a dot, an underscore and a space all collapse to the same ``-``.
_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")


def munge_path(path: str) -> str:
    """Apply Claude Code's path-to-slug sanitiser: every non-alphanumeric → ``-``.

    Mirrors Claude Code's own ``cwd.replace(/[^a-zA-Z0-9]/g, "-")``. An absolute
    path's leading ``/`` therefore becomes the leading ``-`` of the slug. Used
    both to find a project's native-memory dir (forward) and to reverse a slug
    back to a path (see :func:`mait_code.tools.memory.native.resolve_slug`).

    The 200-char truncation-plus-hash that Claude Code applies to very long
    paths is **not** reproduced here — such projects are unresolvable and fall
    back to their raw slug.

    Args:
        path: An absolute filesystem path (or a single path component).

    Returns:
        The munged slug.
    """
    return _NON_ALNUM.sub("-", path)


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
            timeout=get_int("git-timeout"),
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
            timeout=get_int("git-timeout"),
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
    data_path = data_dir()
    key = str(data_path)
    cached = _alias_cache.get(key)
    if cached is None:
        try:
            data = json.loads((data_path / _PROJECT_ALIASES_FILENAME).read_text())
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
