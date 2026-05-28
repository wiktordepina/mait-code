"""``mait-code uninstall`` &mdash; reverse the install footprint.

Removes the symlinks and settings entries created by ``install``,
optionally runs ``uv tool uninstall mait-code``, and (only with
``--purge-data``) deletes the user data directory. The install record
is deleted as the final step.

The CLI is best-effort: if the install record is missing or
inconsistent, the command still tries to clean up what it can find,
emitting warnings rather than failing hard. Users who reach for
``uninstall`` typically want the directory gone, not a tutorial on
broken state.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._paths import install_record_path
from mait_code.cli._paths import mait_code_config_dir
from mait_code.cli._paths import settings_path as mait_settings_path
from mait_code.cli._record import RecordError, read_record
from mait_code.cli._settings import (
    read_settings_file,
    unmerge_settings,
    write_settings_file,
)
from mait_code.cli._symlinks import (
    remove_agent_symlinks,
    remove_claude_md_symlink,
    remove_skill_symlinks,
)
from mait_code.cli._update import Runner, default_runner

__all__ = [
    "UninstallSummary",
    "uninstall",
]


class UninstallSummary:
    """Outcome of an uninstall &mdash; used by the CLI for output."""

    def __init__(
        self,
        *,
        had_record: bool,
        claude_md_removed: bool,
        skills_removed: list[Path],
        agents_removed: list[Path],
        settings_cleaned: bool,
        uv_tool_uninstalled: bool,
        data_dir_removed: bool,
        warnings: list[str],
    ) -> None:
        self.had_record = had_record
        self.claude_md_removed = claude_md_removed
        self.skills_removed = skills_removed
        self.agents_removed = agents_removed
        self.settings_cleaned = settings_cleaned
        self.uv_tool_uninstalled = uv_tool_uninstalled
        self.data_dir_removed = data_dir_removed
        self.warnings = warnings


class _SafeRunner(Protocol):
    """Optional subprocess runner used only by ``uv tool uninstall``."""

    def __call__(self, cmd: list[str]) -> bool: ...


def _safe_default_runner(cmd: list[str]) -> bool:
    """Return True if the command succeeded; False on any failure.

    Unlike the install/update runner, uninstall tolerates ``uv tool
    uninstall`` failing &mdash; the binary may already be gone.
    """
    import subprocess

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def uninstall(
    *,
    purge_data: bool = False,
    keep_uv_tool: bool = False,
    claude_dir: Path | None = None,
    data_dir: Path | None = None,
    runner: Runner | None = None,
    safe_runner: _SafeRunner | None = None,
) -> UninstallSummary:
    """Run the uninstall flow.

    Args:
        purge_data: Also delete the data directory (memories, personalised
            soul_document, user_context). Default ``False`` &mdash; data is
            preserved.
        keep_uv_tool: Skip ``uv tool uninstall`` (useful when temporarily
            downgrading or switching extras).
        claude_dir: Override the Claude Code config dir.
        data_dir: Override the mait-code data dir.
        runner: Unused today; reserved for future steps that need
            install-grade subprocess error handling.
        safe_runner: Runner used by the ``uv tool uninstall`` step.
            Returns True on success, False on failure; failures are
            warnings, not errors.

    Returns:
        An :class:`UninstallSummary`.
    """
    del runner  # Reserved for future expansion.
    safe = safe_runner if safe_runner is not None else _safe_default_runner

    warnings: list[str] = []

    cdir = (claude_dir if claude_dir is not None else default_claude_dir()).resolve()
    ddir = (data_dir if data_dir is not None else default_data_dir()).resolve()

    # Read the install record (best-effort).
    record_path = install_record_path()
    had_record = record_path.exists()
    source_dir: Path | None = None
    if had_record:
        try:
            source_dir = Path(read_record().source_dir)
        except RecordError as exc:
            warnings.append(f"install record unreadable: {exc}")

    # 1. CLAUDE.md.
    claude_md_removed = False
    if source_dir is not None:
        claude_md_removed = remove_claude_md_symlink(source_dir, cdir)

    # 2-3. Skill and agent symlinks.
    skills_removed: list[Path] = []
    agents_removed: list[Path] = []
    if source_dir is not None:
        skills_removed = remove_skill_symlinks(source_dir, cdir)
        agents_removed = remove_agent_symlinks(source_dir, cdir)

    # 4. settings.json — best-effort clean.
    settings_path = cdir / "settings.json"
    settings_cleaned = False
    if settings_path.exists():
        try:
            cleaned = unmerge_settings(read_settings_file(settings_path))
            write_settings_file(settings_path, cleaned)
            settings_cleaned = True
        except Exception as exc:  # noqa: BLE001 — uninstall tolerates settings IO failures
            warnings.append(f"could not clean {settings_path}: {exc}")

    # 5. Remove centralised settings file.
    toml_path = mait_settings_path()
    if toml_path.exists():
        toml_path.unlink()
        config_dir = mait_code_config_dir()
        if config_dir.exists() and not any(config_dir.iterdir()):
            config_dir.rmdir()

    # 6. uv tool uninstall.
    uv_tool_uninstalled = False
    if not keep_uv_tool:
        uv_tool_uninstalled = safe(["uv", "tool", "uninstall", "mait-code"])
        if not uv_tool_uninstalled:
            warnings.append(
                "uv tool uninstall mait-code did not succeed "
                "(already uninstalled? uv not on PATH?)"
            )

    # 6. data dir (only with --purge-data).
    data_dir_removed = False
    if purge_data and ddir.exists():
        shutil.rmtree(ddir)
        data_dir_removed = True

    # 7. install record itself.
    if record_path.exists():
        record_path.unlink()

    return UninstallSummary(
        had_record=had_record,
        claude_md_removed=claude_md_removed,
        skills_removed=skills_removed,
        agents_removed=agents_removed,
        settings_cleaned=settings_cleaned,
        uv_tool_uninstalled=uv_tool_uninstalled,
        data_dir_removed=data_dir_removed,
        warnings=warnings,
    )


# Re-export so a future Brick can introduce additional install-grade
# subprocess calls in the uninstall flow without churn.
_ = default_runner
