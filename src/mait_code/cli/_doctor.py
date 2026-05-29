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
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from rich.text import Text

from mait_code.cli._install import verify_source
from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._paths import settings_path
from mait_code.cli._record import RecordError, read_record
from mait_code.cli._settings import MAIT_CODE_HOOK_PREFIX
from mait_code.config import validate_settings
from mait_code.console import GLYPH, console

__all__ = [
    "Check",
    "DoctorReport",
    "render",
    "render_json",
    "run_doctor",
]

Level = Literal["ok", "warn", "fail"]


@dataclass
class Check:
    """A single diagnostic outcome."""

    name: str
    level: Level
    message: str
    fix_hint: str | None = None


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
        return (
            Check(
                "install-record",
                "fail",
                str(exc),
                fix_hint="reinstall from your clone: mait-code install --from <path>",
            ),
            None,
        )
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
        return Check(
            "source-dir",
            "fail",
            str(exc),
            fix_hint="re-run mait-code install --from <clone-path>",
        )
    return Check(
        "source-dir", "ok", f"{source} exists and looks like a mait-code clone"
    )


def _check_settings(cdir: Path) -> Check:
    claude_settings_path = cdir / "settings.json"
    if not claude_settings_path.exists():
        return Check("settings", "warn", f"{claude_settings_path} does not exist")
    try:
        json.loads(claude_settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return Check(
            "settings",
            "fail",
            f"{claude_settings_path}: {exc}",
            fix_hint="repair the JSON syntax in that file",
        )
    return Check("settings", "ok", f"{claude_settings_path} parses as JSON")


def _check_mait_settings() -> Check:
    sp = settings_path()
    if not sp.exists():
        return Check(
            "settings-file",
            "fail",
            f"{sp} does not exist",
            fix_hint="run mait-code install to create it",
        )
    try:
        tomllib.loads(sp.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return Check(
            "settings-file",
            "fail",
            f"{sp}: {exc}",
            fix_hint="repair the TOML syntax in that file",
        )
    return Check("settings-file", "ok", f"{sp} parses as TOML")


def _check_setting_values() -> Check:
    errors = validate_settings()
    if errors:
        return Check(
            "settings-values",
            "fail",
            "; ".join(errors),
            fix_hint="edit settings.toml so the flagged values are valid "
            "(e.g. scoring weights must sum to 1.0)",
        )
    return Check("settings-values", "ok", "setting values are valid")


def _check_hook_commands(cdir: Path) -> Check:
    """Every registered hook with the mait-code prefix should be on PATH."""
    claude_settings_path = cdir / "settings.json"
    if not claude_settings_path.exists():
        return Check("hooks-on-path", "warn", "skipped (no settings.json)")
    try:
        settings = json.loads(claude_settings_path.read_text(encoding="utf-8"))
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
            fix_hint="refresh hooks: mait-code update",
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
    plural = "s" if len(dangling) != 1 else ""
    return Check(
        "symlinks",
        "warn",
        f"{len(dangling)} dangling symlink{plural} under skills/ or agents/",
        fix_hint="mait-code doctor --fix",
    )


def _check_data_dir(ddir: Path, fix: bool, fixes: list[str]) -> Check:
    if not ddir.exists():
        if fix:
            ddir.mkdir(parents=True, exist_ok=True)
            (ddir / "memory" / "observations").mkdir(parents=True, exist_ok=True)
            (ddir / "memory" / "reflections").mkdir(parents=True, exist_ok=True)
            fixes.append(f"created {ddir} with memory subdirs")
            return Check("data-dir", "ok", f"created {ddir}")
        return Check(
            "data-dir",
            "fail",
            f"{ddir} does not exist",
            fix_hint="mait-code doctor --fix",
        )
    if not _is_writable(ddir):
        return Check(
            "data-dir",
            "fail",
            f"{ddir} is not writable",
            fix_hint="check the directory permissions",
        )
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
        return Check(
            "uv-on-path",
            "fail",
            "`uv` not found on PATH",
            fix_hint="install uv — https://docs.astral.sh/uv/",
        )
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
        _check_mait_settings(),
        _check_setting_values(),
        _check_settings(cdir),
        _check_hook_commands(cdir),
        _check_symlinks(cdir, fix, fixes),
        _check_data_dir(ddir, fix, fixes),
        _check_uv(ddir),
    ]

    return DoctorReport(checks=checks, fixes_applied=fixes)


def _verdict(report: DoctorReport) -> Text:
    """Build the closing one-line pass/fail summary."""
    n_fail = sum(c.level == "fail" for c in report.checks)
    n_warn = sum(c.level == "warn" for c in report.checks)
    n_ok = sum(c.level == "ok" for c in report.checks)
    overall: Level = "fail" if n_fail else "warn" if n_warn else "ok"

    line = Text()
    line.append(f"{GLYPH[overall]}  ", style=overall)
    segments: list[tuple[str, str]] = []
    if n_fail:
        segments.append((f"{n_fail} failed", "fail"))
    if n_warn:
        segments.append((f"{n_warn} warning{'s' if n_warn != 1 else ''}", "warn"))
    segments.append((f"{n_ok} passed", "ok"))
    for i, (text, style) in enumerate(segments):
        if i:
            line.append(" · ", style="muted")
        line.append(text, style=style)
    return line


def render(report: DoctorReport) -> None:
    """Print the report to the shared console: colour, fix hints, verdict.

    Prints rather than returning a string so colour handling stays with
    the console (which disables colour off-TTY and under ``NO_COLOR``).
    Tests capture via ``console.capture()``; JSON callers use
    :func:`render_json` instead.
    """
    console.print(Text("mait-code doctor", style="accent"))
    console.rule(style="muted")
    for check in report.checks:
        line = Text("  ")
        line.append(f"{GLYPH[check.level]}  ", style=check.level)
        line.append(f"{check.name:<16}", style="bold")
        line.append(check.message)
        if check.fix_hint:
            line.append(f"   → {check.fix_hint}", style="muted")
        # soft_wrap keeps each finding on one logical line (long paths stay
        # greppable) and lets the terminal handle wrapping, rather than rich
        # hard-wrapping to its own width when piped.
        console.print(line, soft_wrap=True)
    console.rule(style="muted")
    console.print(_verdict(report), soft_wrap=True)
    if any(c.fix_hint and "--fix" in c.fix_hint for c in report.checks):
        tail = Text("   run ", style="muted")
        tail.append("mait-code doctor --fix", style="accent")
        tail.append(" to clear fixable issues", style="muted")
        console.print(tail, soft_wrap=True)
    if report.fixes_applied:
        console.print()
        console.print(Text("Fixes applied:", style="muted"), soft_wrap=True)
        for fix in report.fixes_applied:
            console.print(Text(f"  - {fix}", style="muted"), soft_wrap=True)


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
