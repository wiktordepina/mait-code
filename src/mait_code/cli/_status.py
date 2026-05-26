"""``mait-code status`` &mdash; read-only summary of the current install.

Surfaces what's where: install record, CLAUDE.md target, count of
linked skills and agents, hooks registered in settings.json, data dir
size, and the ``mait-code`` binary location.

Renders human-readable or JSON depending on the ``--json`` flag.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._record import RecordError, read_record

__all__ = [
    "Status",
    "collect_status",
    "render_json",
    "render_text",
]


@dataclass
class Status:
    """Snapshot of the current mait-code install state."""

    record_present: bool = False
    source_dir: str | None = None
    version: str | None = None
    embedding_provider: str | None = None
    installed_at: str | None = None
    record_error: str | None = None

    claude_md_path: str | None = None
    claude_md_target: str | None = None
    claude_md_is_symlink: bool = False

    skills_linked: int = 0
    skills_total: int = 0
    agents_linked: int = 0
    agents_total: int = 0

    hooks_registered: list[str] = field(default_factory=list)

    data_dir_path: str | None = None
    data_dir_size_bytes: int = 0
    has_soul_document: bool = False
    has_user_context: bool = False
    has_memory_md: bool = False

    binary_path: str | None = None


def _dir_size_bytes(path: Path) -> int:
    """Sum the sizes of every file under ``path``. 0 if missing."""
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return total


def _count_linked(symlink_dir: Path, source_dir: Path | None) -> int:
    """Count symlinks in ``symlink_dir`` that resolve into ``source_dir``."""
    if not symlink_dir.is_dir() or source_dir is None:
        return 0
    source_abs = source_dir.resolve()
    count = 0
    for entry in symlink_dir.iterdir():
        if not entry.is_symlink():
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(source_abs)
            count += 1
        except ValueError:
            continue
    return count


def _count_total(source_subdir: Path) -> int:
    """Count non-``.gitkeep`` entries in a source skill/agent dir."""
    if not source_subdir.is_dir():
        return 0
    return sum(1 for entry in source_subdir.iterdir() if entry.name != ".gitkeep")


def collect_status(
    *,
    claude_dir: Path | None = None,
    data_dir: Path | None = None,
) -> Status:
    """Build a :class:`Status` snapshot. Read-only; no IO except stat/readlink."""
    cdir = (claude_dir if claude_dir is not None else default_claude_dir()).resolve()
    ddir = (data_dir if data_dir is not None else default_data_dir()).resolve()

    status = Status()

    # Install record.
    try:
        record = read_record()
        status.record_present = True
        status.source_dir = record.source_dir
        status.version = record.version
        status.embedding_provider = record.embedding_provider
        status.installed_at = record.installed_at
    except RecordError as exc:
        status.record_error = str(exc)

    source_dir = Path(status.source_dir) if status.source_dir else None

    # CLAUDE.md.
    claude_md = cdir / "CLAUDE.md"
    if claude_md.exists() or claude_md.is_symlink():
        status.claude_md_path = str(claude_md)
        if claude_md.is_symlink():
            status.claude_md_is_symlink = True
            try:
                status.claude_md_target = str(claude_md.readlink())
            except OSError:
                pass

    # Skills + agents.
    if source_dir is not None:
        status.skills_linked = _count_linked(cdir / "skills", source_dir)
        status.skills_total = _count_total(source_dir / "skills")
        status.agents_linked = _count_linked(cdir / "agents", source_dir)
        status.agents_total = _count_total(source_dir / "agents")

    # Hooks registered in settings.json.
    settings_path = cdir / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            hooks_section = settings.get("hooks", {})
            if isinstance(hooks_section, dict):
                status.hooks_registered = sorted(hooks_section.keys())
        except (json.JSONDecodeError, OSError):
            pass

    # Data dir.
    status.data_dir_path = str(ddir)
    status.data_dir_size_bytes = _dir_size_bytes(ddir)
    status.has_soul_document = (ddir / "soul_document.md").exists()
    status.has_user_context = (ddir / "user_context.md").exists()
    status.has_memory_md = (ddir / "memory" / "MEMORY.md").exists()

    # Binary location.
    binary = shutil.which("mait-code")
    if binary:
        status.binary_path = binary

    return status


def render_text(status: Status) -> str:
    """Format ``status`` as a short multi-line text block."""
    lines = []
    if status.record_present:
        lines.append(f"Installed: mait-code {status.version}")
        lines.append(f"  Source:   {status.source_dir}")
        lines.append(f"  Embedding: {status.embedding_provider}")
        lines.append(f"  Installed at: {status.installed_at}")
    else:
        lines.append("Installed: no install record found")
        if status.record_error:
            lines.append(f"  ({status.record_error})")

    if status.binary_path:
        lines.append(f"Binary:    {status.binary_path}")

    lines.append("")
    if status.claude_md_is_symlink:
        lines.append(f"CLAUDE.md: {status.claude_md_path} → {status.claude_md_target}")
    elif status.claude_md_path:
        lines.append(f"CLAUDE.md: {status.claude_md_path} (not a symlink)")
    else:
        lines.append("CLAUDE.md: missing")

    lines.append(
        f"Skills:    {status.skills_linked} linked / {status.skills_total} available"
    )
    lines.append(
        f"Agents:    {status.agents_linked} linked / {status.agents_total} available"
    )

    if status.hooks_registered:
        lines.append(f"Hooks:     {', '.join(status.hooks_registered)}")
    else:
        lines.append("Hooks:     (none registered)")

    lines.append("")
    size_mb = status.data_dir_size_bytes / (1024 * 1024)
    lines.append(f"Data dir:  {status.data_dir_path} ({size_mb:.1f} MB)")
    lines.append(
        f"  soul_document.md: {'present' if status.has_soul_document else 'missing'}"
    )
    lines.append(
        f"  user_context.md:  {'present' if status.has_user_context else 'missing'}"
    )
    lines.append(
        f"  MEMORY.md:        {'present' if status.has_memory_md else 'missing'}"
    )

    return "\n".join(lines)


def render_json(status: Status) -> str:
    """Format ``status`` as a JSON document."""
    return json.dumps(asdict(status), indent=2)
