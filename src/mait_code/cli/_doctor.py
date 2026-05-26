"""``mait-code doctor`` &mdash; validate the install, surface silent breakage.

Each check returns a :class:`Check` with a level (``ok`` / ``warn`` /
``fail``) and a one-line explanation. ``doctor`` exits ``1`` on any
``fail``, ``0`` otherwise.

With ``--fix``: applies the safe fixes &mdash; removing dangling skill /
agent symlinks, creating the data directory if missing.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from mait_code.cli._install import verify_source
from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._record import RecordError, read_record
from mait_code.cli._settings import MAIT_CODE_HOOK_PREFIX

__all__ = [
    "Check",
    "DoctorReport",
    "render_json",
    "render_text",
    "run_doctor",
]

Level = Literal["ok", "warn", "fail"]


@dataclass
class Check:
    """A single diagnostic outcome."""

    name: str
    level: Level
    message: str


@dataclass
class DoctorReport:
    """All diagnostic outcomes for one ``doctor`` run."""

    checks: list[Check]
    fixes_applied: list[str]

    @property
    def has_fail(self) -> bool:
        return any(c.level == "fail" for c in self.checks)


def _check_record() -> tuple[Check, Path | None]:
    """Validate the install record. Returns the check + the source dir."""
    try:
        record = read_record()
    except RecordError as exc:
        return Check("install-record", "fail", str(exc)), None
    source = Path(record.source_dir)
    return (
        Check("install-record", "ok", f"present at schema version 1, source {source}"),
        source,
    )


def _check_source(source: Path | None) -> Check:
    if source is None:
        return Check("source-dir", "warn", "skipped (no install record)")
    try:
        verify_source(source)
    except ValueError as exc:
        return Check("source-dir", "fail", str(exc))
    return Check(
        "source-dir", "ok", f"{source} exists and looks like a mait-code clone"
    )


def _check_settings(cdir: Path) -> Check:
    settings_path = cdir / "settings.json"
    if not settings_path.exists():
        return Check("settings", "warn", f"{settings_path} does not exist")
    try:
        json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return Check("settings", "fail", f"{settings_path}: {exc}")
    return Check("settings", "ok", f"{settings_path} parses as JSON")


def _check_hook_commands(cdir: Path) -> Check:
    """Every registered hook with the mait-code prefix should be on PATH."""
    settings_path = cdir / "settings.json"
    if not settings_path.exists():
        return Check("hooks-on-path", "warn", "skipped (no settings.json)")
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Check("hooks-on-path", "warn", "skipped (settings.json unparseable)")
    missing: list[str] = []
    seen: list[str] = []
    hooks_section = settings.get("hooks", {})
    if not isinstance(hooks_section, dict):
        return Check("hooks-on-path", "ok", "no hooks registered")
    for entries in hooks_section.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command", "")
                if not isinstance(cmd, str) or MAIT_CODE_HOOK_PREFIX not in cmd:
                    continue
                program = cmd.split()[0]
                if program in seen:
                    continue
                seen.append(program)
                if shutil.which(program) is None:
                    missing.append(program)
    if missing:
        return Check(
            "hooks-on-path",
            "fail",
            f"hook commands not on PATH: {', '.join(missing)}",
        )
    if seen:
        return Check(
            "hooks-on-path", "ok", f"{len(seen)} hook commands resolve on PATH"
        )
    return Check("hooks-on-path", "ok", "no mait-code hooks registered")


def _find_dangling_symlinks(cdir: Path) -> list[Path]:
    """Symlinks under skills/ or agents/ whose target no longer exists."""
    dangling: list[Path] = []
    for subdir in ("skills", "agents"):
        target_dir = cdir / subdir
        if not target_dir.is_dir():
            continue
        for entry in target_dir.iterdir():
            if not entry.is_symlink():
                continue
            try:
                if not entry.resolve(strict=True).exists():
                    dangling.append(entry)
            except (OSError, FileNotFoundError):
                dangling.append(entry)
    return dangling


def _check_symlinks(cdir: Path, fix: bool, fixes: list[str]) -> Check:
    dangling = _find_dangling_symlinks(cdir)
    if not dangling:
        return Check("symlinks", "ok", "no dangling symlinks under skills/ or agents/")
    if fix:
        for link in dangling:
            link.unlink(missing_ok=True)
            fixes.append(f"removed dangling symlink {link}")
        return Check("symlinks", "ok", f"removed {len(dangling)} dangling symlinks")
    return Check(
        "symlinks",
        "fail",
        f"{len(dangling)} dangling symlinks (use --fix to remove)",
    )


def _check_data_dir(ddir: Path, fix: bool, fixes: list[str]) -> Check:
    if not ddir.exists():
        if fix:
            ddir.mkdir(parents=True, exist_ok=True)
            (ddir / "memory" / "observations").mkdir(parents=True, exist_ok=True)
            (ddir / "memory" / "reflections").mkdir(parents=True, exist_ok=True)
            fixes.append(f"created {ddir} with memory subdirs")
            return Check("data-dir", "ok", f"created {ddir}")
        return Check("data-dir", "fail", f"{ddir} does not exist (use --fix to create)")
    if not _is_writable(ddir):
        return Check("data-dir", "fail", f"{ddir} is not writable")
    return Check("data-dir", "ok", f"{ddir} exists and is writable")


def _is_writable(path: Path) -> bool:
    test = path / ".__doctor-write-test"
    try:
        test.write_text("")
        test.unlink()
        return True
    except OSError:
        return False


def _check_uv(_ddir: Path) -> Check:
    """``uv`` must be on PATH for install/update to work."""
    if shutil.which("uv") is None:
        return Check("uv-on-path", "fail", "`uv` not found on PATH")
    return Check("uv-on-path", "ok", "`uv` is on PATH")


def run_doctor(
    *,
    fix: bool = False,
    claude_dir: Path | None = None,
    data_dir: Path | None = None,
) -> DoctorReport:
    """Run all diagnostic checks, optionally applying safe fixes.

    Args:
        fix: When ``True``, apply the fixes for the dangling-symlinks
            and missing-data-dir checks; otherwise leave them as
            findings.
        claude_dir: Override the Claude Code config dir.
        data_dir: Override the data dir.

    Returns:
        A :class:`DoctorReport` with the per-check outcomes and any
        fixes that were applied.
    """
    cdir = (claude_dir if claude_dir is not None else default_claude_dir()).resolve()
    ddir = (data_dir if data_dir is not None else default_data_dir()).resolve()
    fixes: list[str] = []

    record_check, source = _check_record()
    checks: list[Check] = [
        record_check,
        _check_source(source),
        _check_settings(cdir),
        _check_hook_commands(cdir),
        _check_symlinks(cdir, fix, fixes),
        _check_data_dir(ddir, fix, fixes),
        _check_uv(ddir),
    ]

    return DoctorReport(checks=checks, fixes_applied=fixes)


_LEVEL_GLYPH = {"ok": "✓", "warn": "!", "fail": "✗"}


def render_text(report: DoctorReport) -> str:
    """Render the report as a short multi-line text block."""
    lines = []
    for check in report.checks:
        glyph = _LEVEL_GLYPH[check.level]
        lines.append(f"  {glyph} {check.name}: {check.message}")
    if report.fixes_applied:
        lines.append("")
        lines.append("Fixes applied:")
        for fix in report.fixes_applied:
            lines.append(f"  - {fix}")
    return "\n".join(lines)


def render_json(report: DoctorReport) -> str:
    """Render the report as JSON."""
    return json.dumps(
        {
            "checks": [asdict(c) for c in report.checks],
            "fixes_applied": list(report.fixes_applied),
            "has_fail": report.has_fail,
        },
        indent=2,
    )
