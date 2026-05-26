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

import typer

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


def main() -> None:
    """Console-script entry point declared in ``pyproject.toml``."""
    app()


if __name__ == "__main__":
    main()
