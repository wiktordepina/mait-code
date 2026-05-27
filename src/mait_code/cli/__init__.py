"""``mait-code`` &mdash; the install lifecycle CLI.

The ``mait-code`` binary owns the install lifecycle:

* ``mait-code install`` &mdash; first-time setup (symlinks, settings merge,
  data directories, install record).
* ``mait-code update`` &mdash; pull latest source + reinstall + refresh symlinks.
* ``mait-code uninstall`` &mdash; remove symlinks, strip settings entries,
  optionally purge data.
* ``mait-code status`` &mdash; read-only summary of the current install.
* ``mait-code doctor`` &mdash; diagnose silent breakage; ``--fix`` for safe fixes.
* ``mait-code settings`` &mdash; read-only view of the active configuration.
* ``mait-code version`` &mdash; print the installed version.

The bash shims under ``scripts/`` handle the chicken-and-egg of
installing the CLI itself (``uv tool install``) before delegating
to ``mait-code install``.

The public surface of this package is the helpers used by those
subcommands &mdash; :class:`~mait_code.cli._record.InstallRecord`,
the path helpers, the symlink and settings-merge functions. The
Typer command callables themselves are private (their docs live in
``mait-code <cmd> --help``).
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Annotated

import typer

from mait_code.cli._doctor import (
    Check,
    DoctorReport,
    render as _doctor_render,
    render_json as _doctor_render_json,
    run_doctor as _doctor_impl,
)
from mait_code.cli._install import (
    EMBEDDING_PROVIDERS,
    InstallSummary,
    install as _install_impl,
)
from mait_code.cli._status import (
    Status,
    collect_status as _status_impl,
    render as _status_render,
    render_json as _status_render_json,
)
from mait_code.cli._uninstall import (
    UninstallSummary,
    uninstall as _uninstall_impl,
)
from mait_code.cli._update import (
    UpdateSummary,
    update as _update_impl,
)
from mait_code.cli._paths import (
    claude_dir,
    data_dir,
    install_record_path,
    mait_code_state_dir,
    xdg_data_home,
)
from mait_code.cli._record import (
    SCHEMA_VERSION,
    InstallRecord,
    RecordError,
    read_record,
    write_record,
)
from mait_code.cli._settings import (
    merge_settings,
    read_settings_file,
    unmerge_settings,
    write_settings_file,
)
from mait_code.cli._symlinks import (
    SymlinkResult,
    remove_agent_symlinks,
    remove_claude_md_symlink,
    remove_skill_symlinks,
    symlink_agents,
    symlink_claude_md,
    symlink_skills,
)
from mait_code.config import (
    collect_settings as _collect_settings,
    render as _settings_render,
    render_json as _settings_render_json,
)
from mait_code.console import console

__all__ = [
    # State paths
    "claude_dir",
    "data_dir",
    "install_record_path",
    "mait_code_state_dir",
    "xdg_data_home",
    # Install record
    "SCHEMA_VERSION",
    "InstallRecord",
    "RecordError",
    "read_record",
    "write_record",
    # Install flow
    "EMBEDDING_PROVIDERS",
    "InstallSummary",
    # Update flow
    "UpdateSummary",
    # Uninstall flow
    "UninstallSummary",
    # Status & doctor
    "Check",
    "DoctorReport",
    "Status",
    # Symlinks
    "SymlinkResult",
    "remove_agent_symlinks",
    "remove_claude_md_symlink",
    "remove_skill_symlinks",
    "symlink_agents",
    "symlink_claude_md",
    "symlink_skills",
    # Settings
    "merge_settings",
    "read_settings_file",
    "unmerge_settings",
    "write_settings_file",
    # Entry point
    "app",
    "main",
]


app = typer.Typer(
    name="mait-code",
    help="mait-code install-lifecycle CLI.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    add_completion=False,
)


# Empty callback forces Typer into multi-command mode even when only one
# subcommand is registered (subsequent commits will add several more).
# Without this, `mait-code version` would be parsed as `mait-code` with
# `version` as an unexpected positional argument.
@app.callback()
def _root(
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable coloured output."),
    ] = False,
) -> None:
    """mait-code install-lifecycle CLI."""
    # rich already honours NO_COLOR / non-TTY / TERM=dumb; this is the
    # explicit manual override. Assigning the bool each invocation keeps
    # the process-wide console's state predictable.
    console.no_color = no_color


@app.command()
def version() -> None:
    """Print the installed mait-code version."""
    try:
        typer.echo(importlib.metadata.version("mait-code"))
    except importlib.metadata.PackageNotFoundError:
        # Running from a checkout without `uv tool install`: fall back
        # to the in-tree __version__ if importable.
        try:
            from mait_code import __version__

            typer.echo(__version__)
        except ImportError:
            typer.echo("unknown")
            raise typer.Exit(code=1) from None


@app.command(name="install")
def install_cmd(
    from_: Annotated[
        Path,
        typer.Option(
            "--from",
            help="Absolute path to the cloned mait-code source tree.",
        ),
    ],
    embedding_provider: Annotated[
        str,
        typer.Option(
            "--embedding-provider",
            help="Which embedding backend to configure ('local' or 'bedrock').",
        ),
    ] = "local",
    data_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Override the mait-code data directory.",
        ),
    ] = None,
    claude_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--claude-dir",
            help="Override the Claude Code config directory.",
        ),
    ] = None,
) -> None:
    """Set up data directories, symlinks, and settings for a mait-code clone."""
    try:
        summary = _install_impl(
            source_dir=from_,
            embedding_provider=embedding_provider,
            data_dir=data_dir_override,
            claude_dir=claude_dir_override,
        )
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    _render_install_summary(summary)


def _render_install_summary(summary: InstallSummary) -> None:
    """Print a short human-readable summary of an install."""
    record = summary.record
    typer.echo(f"Installed mait-code {record.version} from {record.source_dir}.")
    typer.echo(f"  Embedding provider: {record.embedding_provider}")
    if summary.templates_copied:
        typer.echo(f"  Templates copied: {', '.join(summary.templates_copied)}")
    if summary.memory_md_created:
        typer.echo("  Created MEMORY.md stub")
    if summary.claude_md.backed_up:
        typer.echo(
            f"  Backed up existing CLAUDE.md to {summary.claude_md.backed_up[0]}"
        )
    typer.echo(
        f"  Symlinks: {len(summary.skills.created) + len(summary.skills.already_linked)} skills, "
        f"{len(summary.agents.created) + len(summary.agents.already_linked)} agents"
    )
    typer.echo(f"  Settings merged into {summary.settings_path}")
    typer.echo("")
    typer.echo("Next: personalise the soul_document and user_context.")


@app.command(name="update")
def update_cmd(
    no_pull: Annotated[
        bool,
        typer.Option(
            "--no-pull",
            help="Skip `git pull` (useful if you pull manually).",
        ),
    ] = False,
    ref: Annotated[
        str | None,
        typer.Option(
            "--ref",
            help="Checkout this ref (tag/branch/sha) before reinstalling.",
        ),
    ] = None,
    claude_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--claude-dir",
            help="Override the Claude Code config directory.",
        ),
    ] = None,
) -> None:
    """Pull latest source, reinstall via uv tool, refresh symlinks and settings."""
    try:
        summary = _update_impl(
            no_pull=no_pull,
            ref=ref,
            claude_dir=claude_dir_override,
        )
    except RecordError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    _render_update_summary(summary)


def _render_update_summary(summary: UpdateSummary) -> None:
    record = summary.record
    pieces = []
    if summary.fetched:
        pieces.append("fetched")
    pieces.append(f"now on {summary.landed_on}")
    pieces.append(f"reinstalled {record.version}")
    typer.echo(f"Updated mait-code: {', '.join(pieces)}.")
    typer.echo(f"  Source: {record.source_dir}")
    typer.echo(
        f"  Symlinks refreshed: {len(summary.skills.created) + len(summary.skills.updated)} new, "
        f"{len(summary.skills.already_linked)} unchanged"
    )
    typer.echo(f"  Settings: {summary.settings_path}")


@app.command(name="uninstall")
def uninstall_cmd(
    purge_data: Annotated[
        bool,
        typer.Option(
            "--purge-data",
            help="Also delete the data directory (memories + personalised files).",
        ),
    ] = False,
    keep_uv_tool: Annotated[
        bool,
        typer.Option(
            "--keep-uv-tool",
            help="Skip `uv tool uninstall mait-code` (useful when downgrading).",
        ),
    ] = False,
    claude_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--claude-dir",
            help="Override the Claude Code config directory.",
        ),
    ] = None,
    data_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Override the mait-code data directory.",
        ),
    ] = None,
) -> None:
    """Remove symlinks, strip settings entries, optionally purge data."""
    summary = _uninstall_impl(
        purge_data=purge_data,
        keep_uv_tool=keep_uv_tool,
        claude_dir=claude_dir_override,
        data_dir=data_dir_override,
    )
    _render_uninstall_summary(summary)


def _render_uninstall_summary(summary: UninstallSummary) -> None:
    typer.echo("Uninstalled mait-code.")
    if not summary.had_record:
        typer.echo("  (No install record was present.)")
    if summary.claude_md_removed:
        typer.echo("  Removed CLAUDE.md symlink (restored backup if any)")
    if summary.skills_removed:
        typer.echo(f"  Removed {len(summary.skills_removed)} skill symlinks")
    if summary.agents_removed:
        typer.echo(f"  Removed {len(summary.agents_removed)} agent symlinks")
    if summary.settings_cleaned:
        typer.echo("  Cleaned mait-code entries from settings.json")
    if summary.uv_tool_uninstalled:
        typer.echo("  Uninstalled `mait-code` from uv tool")
    if summary.data_dir_removed:
        typer.echo("  Removed data directory")
    elif not summary.warnings:
        typer.echo("  Data directory preserved (use --purge-data to remove)")
    for warning in summary.warnings:
        typer.echo(f"  warning: {warning}", err=True)


@app.command(name="status")
def status_cmd(
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a machine-readable JSON document instead of text.",
        ),
    ] = False,
    claude_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--claude-dir",
            help="Override the Claude Code config directory.",
        ),
    ] = None,
    data_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Override the mait-code data directory.",
        ),
    ] = None,
) -> None:
    """Print a read-only summary of the current install."""
    status = _status_impl(
        claude_dir=claude_dir_override,
        data_dir=data_dir_override,
    )
    if as_json:
        typer.echo(_status_render_json(status))
    else:
        _status_render(status)


@app.command(name="doctor")
def doctor_cmd(
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Apply safe fixes for findings that support it."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a machine-readable JSON document instead of text.",
        ),
    ] = False,
    claude_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--claude-dir",
            help="Override the Claude Code config directory.",
        ),
    ] = None,
    data_dir_override: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Override the mait-code data directory.",
        ),
    ] = None,
) -> None:
    """Diagnose silent breakage in the install; exits 1 on any failure."""
    report = _doctor_impl(
        fix=fix,
        claude_dir=claude_dir_override,
        data_dir=data_dir_override,
    )
    if as_json:
        typer.echo(_doctor_render_json(report))
    else:
        _doctor_render(report)
    if report.has_fail:
        raise typer.Exit(code=1)


@app.command(name="settings")
def settings_cmd(
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a machine-readable JSON document instead of text.",
        ),
    ] = False,
) -> None:
    """Show the active mait-code configuration (read-only)."""
    try:
        recorded_provider = read_record().embedding_provider
    except RecordError:
        recorded_provider = None
    snapshot = _collect_settings(recorded_provider=recorded_provider)
    if as_json:
        typer.echo(_settings_render_json(snapshot))
    else:
        _settings_render(snapshot)


def main() -> None:
    """Console-script entry point declared in ``pyproject.toml``."""
    app()


if __name__ == "__main__":
    main()
