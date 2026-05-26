"""``mait-code`` &mdash; the install lifecycle CLI.

The ``mait-code`` binary owns the install lifecycle:

* ``mait-code install`` &mdash; first-time setup (symlinks, settings merge,
  data directories, install record).
* ``mait-code update`` &mdash; pull latest source + reinstall + refresh symlinks.
* ``mait-code uninstall`` &mdash; remove symlinks, strip settings entries,
  optionally purge data.
* ``mait-code status`` &mdash; read-only summary of the current install.
* ``mait-code doctor`` &mdash; diagnose silent breakage; ``--fix`` for safe fixes.
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

from mait_code.cli._install import (
    EMBEDDING_PROVIDERS,
    InstallSummary,
    install as _install_impl,
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
def _root() -> None:
    """mait-code install-lifecycle CLI."""


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


def main() -> None:
    """Console-script entry point declared in ``pyproject.toml``."""
    app()


if __name__ == "__main__":
    main()
