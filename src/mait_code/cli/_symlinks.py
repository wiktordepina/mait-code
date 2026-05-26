"""Symlink helpers for ``mait-code install`` and ``mait-code uninstall``.

Pure-ish functions that create or remove the three symlink fan-outs
``install`` manages: ``CLAUDE.md``, ``skills/*``, and ``agents/*``. Each
helper takes the source tree root and the Claude Code config dir as
inputs and returns a small structured summary of what it did so the
calling command can render that to the user.

The skill/agent helpers ignore the ``.gitkeep`` placeholder files used
to keep empty directories tracked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "SymlinkResult",
    "remove_agent_symlinks",
    "remove_claude_md_symlink",
    "remove_skill_symlinks",
    "symlink_agents",
    "symlink_claude_md",
    "symlink_skills",
]


@dataclass
class SymlinkResult:
    """Outcome summary returned by the symlink helpers.

    Attributes:
        created: Links that did not exist before this call.
        already_linked: Links that already pointed at the correct target.
        updated: Links that existed but pointed somewhere stale, now repointed.
        backed_up: Existing non-symlink files renamed to ``<name>.backup``.
    """

    created: list[Path] = field(default_factory=list)
    already_linked: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    backed_up: list[Path] = field(default_factory=list)


def _link_to(target: Path, link: Path, result: SymlinkResult) -> None:
    """Create or refresh a symlink, updating ``result`` in place."""
    if link.is_symlink():
        if link.readlink() == target:
            result.already_linked.append(link)
            return
        link.unlink()
        link.symlink_to(target)
        result.updated.append(link)
        return
    if link.exists():
        backup = link.with_suffix(link.suffix + ".backup")
        link.rename(backup)
        result.backed_up.append(backup)
    link.symlink_to(target)
    result.created.append(link)


def symlink_claude_md(source_dir: Path, claude_dir: Path) -> SymlinkResult:
    """Symlink ``config/CLAUDE.md`` to ``<claude_dir>/CLAUDE.md``.

    If a non-symlink ``CLAUDE.md`` already exists at the target, it is
    renamed to ``CLAUDE.md.backup`` first (preserving the user's
    pre-existing config).

    Args:
        source_dir: Absolute path to the cloned source tree.
        claude_dir: The Claude Code config dir (typically ``~/.claude``).

    Returns:
        A :class:`SymlinkResult` summarising what was done.
    """
    result = SymlinkResult()
    claude_dir.mkdir(parents=True, exist_ok=True)
    target = (source_dir / "config" / "CLAUDE.md").resolve()
    link = claude_dir / "CLAUDE.md"
    _link_to(target, link, result)
    return result


def symlink_skills(source_dir: Path, claude_dir: Path) -> SymlinkResult:
    """Symlink every ``skills/<name>/`` directory into ``<claude_dir>/skills/``.

    No-op if ``source_dir/skills`` is missing. ``.gitkeep`` placeholders
    are ignored.
    """
    result = SymlinkResult()
    skills_src = source_dir / "skills"
    if not skills_src.is_dir():
        return result
    skills_dst = claude_dir / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(skills_src.iterdir()):
        if entry.name == ".gitkeep" or not entry.is_dir():
            continue
        _link_to(entry.resolve(), skills_dst / entry.name, result)
    return result


def symlink_agents(source_dir: Path, claude_dir: Path) -> SymlinkResult:
    """Symlink every ``agents/<file>`` into ``<claude_dir>/agents/``.

    No-op if ``source_dir/agents`` is missing. ``.gitkeep`` placeholders
    are ignored. Agents are individual files, not directories.
    """
    result = SymlinkResult()
    agents_src = source_dir / "agents"
    if not agents_src.is_dir():
        return result
    agents_dst = claude_dir / "agents"
    agents_dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(agents_src.iterdir()):
        if entry.name == ".gitkeep" or not entry.is_file():
            continue
        _link_to(entry.resolve(), agents_dst / entry.name, result)
    return result


def remove_claude_md_symlink(source_dir: Path, claude_dir: Path) -> bool:
    """Remove the ``CLAUDE.md`` symlink if it points into ``source_dir``.

    Restores ``CLAUDE.md.backup`` to ``CLAUDE.md`` if the backup exists.

    Returns:
        ``True`` if the symlink was removed; ``False`` if nothing to do.
    """
    link = claude_dir / "CLAUDE.md"
    if not link.is_symlink():
        return False
    try:
        target = link.readlink()
    except OSError:
        return False
    # readlink() may be absolute or relative; resolve both for the check.
    target_abs = target if target.is_absolute() else (link.parent / target).resolve()
    try:
        target_abs.relative_to(source_dir.resolve())
    except ValueError:
        return False
    link.unlink()
    backup = claude_dir / "CLAUDE.md.backup"
    if backup.exists():
        backup.rename(link)
    return True


def _remove_links_into(target_dir: Path, source_dir: Path) -> list[Path]:
    """Remove every symlink under ``target_dir`` that resolves into ``source_dir``."""
    if not target_dir.is_dir():
        return []
    removed: list[Path] = []
    source_abs = source_dir.resolve()
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_symlink():
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            # Dangling symlink: only remove if its raw target lives under source.
            raw = entry.readlink()
            raw_abs = (
                raw if raw.is_absolute() else (entry.parent / raw).resolve(strict=False)
            )
            try:
                raw_abs.relative_to(source_abs)
            except ValueError:
                continue
            entry.unlink()
            removed.append(entry)
            continue
        try:
            resolved.relative_to(source_abs)
        except ValueError:
            continue
        entry.unlink()
        removed.append(entry)
    return removed


def remove_skill_symlinks(source_dir: Path, claude_dir: Path) -> list[Path]:
    """Remove every skill symlink under ``<claude_dir>/skills/`` that
    points into ``source_dir``. Returns the list of paths removed.
    """
    return _remove_links_into(claude_dir / "skills", source_dir)


def remove_agent_symlinks(source_dir: Path, claude_dir: Path) -> list[Path]:
    """Remove every agent symlink under ``<claude_dir>/agents/`` that
    points into ``source_dir``. Returns the list of paths removed.
    """
    return _remove_links_into(claude_dir / "agents", source_dir)
