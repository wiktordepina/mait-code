"""Read-only access to Claude Code's native per-project auto memory.

Claude Code keeps a memory directory per project under
``~/.claude/projects/<munged-path>/memory/`` — a ``MEMORY.md`` index plus one
markdown file per fact, auto-loaded into that project's sessions. This module
enumerates those directories across *all* projects so the memory browser can
surface the native layer beside mait-code's own store. Everything here reads;
nothing writes — the native layer is Claude Code's to maintain.

The directory name is the project's absolute path with ``/`` replaced by
``-`` (``/home/w/mait-code`` → ``-home-w-mait-code``). That munging is lossy —
a ``-`` may be a path separator or a literal dash — so :func:`resolve_slug`
recovers the original path by walking the filesystem for an existing directory
chain that consumes the slug, and labels fall back to the raw slug when
nothing resolves.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

__all__ = [
    "list_native_memories",
    "native_projects_dir",
    "resolve_slug",
]


def native_projects_dir() -> Path:
    """Claude Code's per-project state root, usually ``~/.claude/projects``.

    Honours ``CLAUDE_CONFIG_DIR`` when set (Claude Code's own override for
    relocating ``~/.claude``).

    Returns:
        The projects directory path; it may not exist.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
    return base / "projects"


def resolve_slug(slug: str, root: Path = Path("/")) -> Path | None:
    """Best-effort reverse of Claude Code's path munging, filesystem-guided.

    Walks from ``root``, consuming the slug's ``-``-separated tokens: each
    path component is the shortest token run naming an existing directory,
    backtracking to longer runs (literal dashes) when the walk dead-ends —
    so ``-home-w-mait-code`` resolves to ``/home/w/mait-code`` even though
    the leaf contains a dash.

    Args:
        slug: A munged directory name from the projects dir.
        root: Filesystem root the munged path is relative to (tests inject a
            temporary tree here).

    Returns:
        The resolved original path, or ``None`` when no existing directory
        chain consumes every token (e.g. the project has since been deleted).
    """
    tokens = slug.split("-")
    if tokens and tokens[0] == "":
        tokens = tokens[1:]  # the leading "-" is the root "/"
    if not tokens or "" in tokens:
        # Consecutive dashes mean a munged non-slash character (e.g. a dot)
        # this walk can't reconstruct — let the caller fall back to the slug.
        return None

    def walk(base: Path, index: int) -> Path | None:
        if index == len(tokens):
            return base
        component = ""
        for end in range(index, len(tokens)):
            component = f"{component}-{tokens[end]}" if component else tokens[end]
            candidate = base / component
            if candidate.is_dir():
                resolved = walk(candidate, end + 1)
                if resolved is not None:
                    return resolved
        return None

    return walk(root, 0)


def _file_record(memory_dir: Path, path: Path) -> dict:
    """One file entry: name relative to the memory dir, path, modified date."""
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        modified = ""
    return {
        "name": path.relative_to(memory_dir).as_posix(),
        "path": path,
        "modified": modified,
    }


def list_native_memories(
    projects_dir: Path | None = None, *, root: Path = Path("/")
) -> list[dict]:
    """Enumerate every project's native memory files, across all projects.

    Scans ``projects_dir`` (default :func:`native_projects_dir`) for
    ``<slug>/memory/**/*.md``. Projects without a memory directory, or whose
    memory directory holds no markdown, are skipped — only projects with
    something to read appear. A missing or unreadable projects dir yields an
    empty list rather than an error.

    Args:
        projects_dir: The Claude Code projects directory to scan.
        root: Filesystem root for :func:`resolve_slug` label resolution.

    Returns:
        One dict per project, sorted by label: ``slug`` (the munged dir
        name), ``label`` (the resolved project name, or the slug when
        unresolvable), ``path`` (the resolved original project path as a
        string, or ``None``), ``memory_dir``, and ``files`` — ``MEMORY.md``
        first, the rest alphabetical, each ``{name, path, modified}``.
    """
    base = projects_dir if projects_dir is not None else native_projects_dir()
    projects: list[dict] = []
    try:
        slug_dirs = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return []
    for slug_dir in slug_dirs:
        memory_dir = slug_dir / "memory"
        if not memory_dir.is_dir():
            continue
        files = sorted(
            (_file_record(memory_dir, p) for p in memory_dir.rglob("*.md")),
            key=lambda f: (f["name"] != "MEMORY.md", f["name"].casefold()),
        )
        if not files:
            continue
        resolved = resolve_slug(slug_dir.name, root=root)
        projects.append(
            {
                "slug": slug_dir.name,
                "label": resolved.name if resolved else slug_dir.name,
                "path": str(resolved) if resolved else None,
                "memory_dir": memory_dir,
                "files": files,
            }
        )
    projects.sort(key=lambda p: (p["label"].casefold(), p["slug"]))
    return projects
