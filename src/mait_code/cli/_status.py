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
from typing import Literal

from rich.text import Text

import mait_code
from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._record import RecordError, read_record
from mait_code.config import get as config_get
from mait_code.console import GLYPH, console

__all__ = [
    "Status",
    "collect_status",
    "render",
    "render_json",
]


@dataclass
class Status:
    """Snapshot of the current mait-code install state."""

    record_present: bool = False
    source_dir: str | None = None
    version: str | None = None
    embedding_provider: str | None = None
    first_installed_at: str | None = None
    updated_at: str | None = None
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
        status.version = mait_code.__version__
        status.embedding_provider = config_get("embedding-provider")
        status.first_installed_at = record.first_installed_at
        status.updated_at = record.updated_at
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


_SECTION_W = 12
_KEY_W = 11

_Health = Literal["ok", "warn", "fail"]


def _tilde(path: str | None) -> str:
    """Abbreviate the home-dir prefix to ``~`` for readability."""
    if not path:
        return "—"
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


def _date_only(timestamp: str | None) -> str:
    """Show just the calendar day of an ISO install timestamp."""
    if not timestamp:
        return "—"
    return timestamp.split("T", 1)[0]


def _human_size(num_bytes: int) -> str:
    """Render a byte count as B / KB / MB / GB."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _health(status: Status) -> _Health:
    """Derive an at-a-glance health level from the collected state.

    Light-touch: ``fail`` only when nothing is installed, ``warn`` for
    fixable oddities (unlinked CLAUDE.md, missing identity files, no
    linked skills). Anything deeper is ``doctor``'s job.
    """
    if not status.record_present:
        return "fail"
    degraded = (
        not status.claude_md_is_symlink
        or (status.skills_total > 0 and status.skills_linked == 0)
        or not status.has_soul_document
        or not status.has_user_context
        or not status.has_memory_md
    )
    return "warn" if degraded else "ok"


def _health_badge(status: Status) -> Text:
    level = _health(status)
    label = {"ok": "healthy", "warn": "degraded", "fail": "not installed"}[level]
    badge = Text("● ", style=level)
    badge.append(label, style=level)
    return badge


def _line(section: str, key: str, value: Text) -> Text:
    """One grouped row: bold section (first row only), dim key, then value."""
    row = Text()
    if section:
        row.append(f"{section:<{_SECTION_W}}", style="bold")
    else:
        row.append(" " * _SECTION_W)
    row.append(f"{key:<{_KEY_W}}", style="muted")
    row.append_text(value)
    return row


def _hint(text: str) -> Text:
    row = Text(" " * _SECTION_W)
    row.append("↳ ", style="muted")
    row.append(text, style="muted")
    return row


def _flag(present: bool) -> Text:
    if present:
        return Text(GLYPH["ok"], style="ok")
    return Text(GLYPH["fail"], style="fail")


def _claude_value(status: Status) -> Text:
    if status.claude_md_is_symlink:
        value = Text("linked", style="ok")
        if status.claude_md_target:
            value.append(f"  → {_tilde(status.claude_md_target)}", style="muted")
        return value
    if status.claude_md_path:
        return Text("present, not linked", style="warn")
    return Text("missing", style="fail")


def _identity_files(status: Status) -> Text:
    value = Text()
    items = (
        ("soul", status.has_soul_document),
        ("context", status.has_user_context),
        ("memory", status.has_memory_md),
    )
    for index, (label, present) in enumerate(items):
        if index:
            value.append("   ")
        value.append(f"{label} ", style="muted")
        value.append_text(_flag(present))
    return value


def render(status: Status) -> None:
    """Print a grouped, coloured summary to the shared console.

    Prints rather than returning a string so colour handling stays with
    the console; tests capture via ``console.capture()``. JSON callers
    use :func:`render_json` instead.
    """
    header = Text("mait-code", style="accent")
    if status.version:
        header.append(f"  v{status.version}", style="bold")
    header.append("   ")
    header.append_text(_health_badge(status))
    console.print(header, soft_wrap=True)
    console.rule(style="muted")

    # Install.
    if status.record_present:
        console.print(
            _line("Install", "source", Text(_tilde(status.source_dir))),
            soft_wrap=True,
        )
        if status.binary_path:
            binary = Text(_tilde(status.binary_path))
        else:
            binary = Text("not on PATH", style="warn")
        console.print(_line("", "binary", binary), soft_wrap=True)
        console.print(
            _line("", "installed", Text(_date_only(status.first_installed_at))),
            soft_wrap=True,
        )
        console.print(
            _line("", "updated", Text(_date_only(status.updated_at))),
            soft_wrap=True,
        )
    else:
        console.print(
            _line("Install", "record", Text("no install record found", style="fail")),
            soft_wrap=True,
        )
        if status.record_error:
            console.print(_hint(status.record_error), soft_wrap=True)

    # Identity.
    console.print()
    console.print(_line("Identity", "CLAUDE.md", _claude_value(status)), soft_wrap=True)
    console.print(_line("", "files", _identity_files(status)), soft_wrap=True)
    if status.record_present and not status.claude_md_is_symlink:
        console.print(_hint("run mait-code install to link CLAUDE.md"), soft_wrap=True)

    # Components.
    console.print()
    skills = Text(str(status.skills_linked))
    skills.append(f" / {status.skills_total} linked", style="muted")
    console.print(_line("Components", "skills", skills), soft_wrap=True)
    agents = Text(str(status.agents_linked))
    agents.append(f" / {status.agents_total}", style="muted")
    console.print(_line("", "agents", agents), soft_wrap=True)
    if status.hooks_registered:
        hooks = Text(", ".join(status.hooks_registered))
    else:
        hooks = Text("(none registered)", style="muted")
    console.print(_line("", "hooks", hooks), soft_wrap=True)

    # Memory.
    console.print()
    console.print(
        _line("Memory", "embedding", Text(status.embedding_provider or "—")),
        soft_wrap=True,
    )
    data_dir_value = Text(_tilde(status.data_dir_path))
    data_dir_value.append(
        f"   {_human_size(status.data_dir_size_bytes)}", style="muted"
    )
    console.print(_line("", "data dir", data_dir_value), soft_wrap=True)


def render_json(status: Status) -> str:
    """Format ``status`` as a JSON document."""
    return json.dumps(asdict(status), indent=2)
