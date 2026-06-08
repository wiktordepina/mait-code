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
import subprocess
import sys
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
    mait_code_config_dir,
    mait_code_log_dir,
    mait_code_state_dir,
    settings_path,
    xdg_config_home,
    xdg_data_home,
    xdg_state_home,
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
from mait_code.cli._settings_edit import (
    ApplyOutcome,
    SettingError as _SettingError,
    apply_setting,
)
from mait_code.config import (
    SETTINGS as _SETTINGS,
    collect_settings as _collect_settings,
    render as _settings_render,
    render_json as _settings_render_json,
    resolve as _resolve_setting,
)
from mait_code.console import console

__all__ = [
    # State paths
    "claude_dir",
    "data_dir",
    "install_record_path",
    "mait_code_config_dir",
    "mait_code_log_dir",
    "mait_code_state_dir",
    "settings_path",
    "xdg_config_home",
    "xdg_data_home",
    "xdg_state_home",
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
    # Editable settings
    "ApplyOutcome",
    "apply_setting",
    # Entry point
    "app",
    "main",
]


app = typer.Typer(
    name="mait-code",
    help="mait-code install-lifecycle CLI.",
    pretty_exceptions_enable=False,
    add_completion=False,
)


# The callback forces Typer into multi-command mode even when only one
# subcommand is registered. Without this, `mait-code version` would be
# parsed as `mait-code` with `version` as an unexpected positional argument.
@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
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
    if ctx.invoked_subcommand is not None:
        return
    # Bare `mait-code` on a terminal opens the companion's home hub — the front
    # door. Piped or redirected it keeps printing help, so scripts and muscle
    # memory like `mait-code | grep` see what they always did.
    if sys.stdin.isatty() and sys.stdout.isatty():
        _run_home_loop()
    else:
        typer.echo(ctx.get_help())


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
    import mait_code

    record = summary.record
    typer.echo(f"Installed mait-code {mait_code.__version__} from {record.source_dir}.")
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
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Reinstall even when the source is unchanged "
            "(e.g. to rebuild uncommitted dev edits).",
        ),
    ] = False,
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
            force=force,
            claude_dir=claude_dir_override,
        )
    except RecordError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except subprocess.CalledProcessError as exc:
        # A git/uv subprocess failed (its own stderr has already printed).
        # Surface a clean error line instead of dumping a Python traceback.
        typer.echo(f"error: command failed: {exc}", err=True)
        raise typer.Exit(code=1) from None

    _render_update_summary(summary)


def _render_update_summary(summary: UpdateSummary) -> None:
    import mait_code

    record = summary.record
    pieces = []
    if summary.fetched:
        pieces.append("fetched")
    pieces.append(f"now on {summary.landed_on}")
    if summary.reinstalled:
        pieces.append(f"reinstalled {mait_code.__version__}")
    else:
        pieces.append(f"already current ({mait_code.__version__}), reinstall skipped")
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


def _require_settings_file() -> None:
    """Abort with exit code 1 if the centralised settings file is absent.

    From 0.19.0 ``mait-code install`` always writes ``settings.toml``, so its
    absence means a broken or pre-0.19.0 install. The read-only reporting
    commands refuse to run rather than present defaults as configured values.
    """
    sp = settings_path()
    if not sp.exists():
        sp_display = str(sp).replace(str(Path.home()), "~")
        typer.echo(f"error: settings file not found at {sp_display}", err=True)
        typer.echo("run `mait-code install` to create it", err=True)
        raise typer.Exit(code=1)


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
    _require_settings_file()
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


settings_app = typer.Typer(
    help="View and edit mait-code configuration.",
    no_args_is_help=False,
)
app.add_typer(settings_app, name="settings")


@settings_app.callback(invoke_without_command=True)
def settings_root(ctx: typer.Context) -> None:
    """View and edit mait-code configuration.

    On a terminal this opens the interactive editor; when piped or
    redirected it falls back to the read-only configuration view (the same
    output as ``settings list``), so scripts are unaffected.
    """
    if ctx.invoked_subcommand is not None:
        return
    _require_settings_file()
    if sys.stdin.isatty() and sys.stdout.isatty():
        from mait_code.cli._settings_tui import run_interactive_editor

        run_interactive_editor()
    else:
        _settings_render(_collect_settings())


@settings_app.command("list")
def settings_list(
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a machine-readable JSON document instead of text.",
        ),
    ] = False,
) -> None:
    """Show the active mait-code configuration (read-only)."""
    _require_settings_file()
    snapshot = _collect_settings()
    if as_json:
        typer.echo(_settings_render_json(snapshot))
    else:
        _settings_render(snapshot)


@settings_app.command("get")
def settings_get(
    key: str,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit the value and source as a JSON document.",
        ),
    ] = False,
) -> None:
    """Print one resolved setting value and its source (for scripting)."""
    _require_settings_file()
    by_key = {s.key: s for s in _SETTINGS}
    setting = by_key.get(key)
    if setting is None:
        typer.echo(f"error: unknown setting {key!r}", err=True)
        raise typer.Exit(code=1)
    value, source = _resolve_setting(setting)
    if as_json:
        import json

        typer.echo(json.dumps({"key": key, "value": value, "source": source}))
    else:
        typer.echo(f"{value}\t({source})")


@settings_app.command("set")
def settings_set(
    key: str,
    value: str,
    reindex: Annotated[
        bool | None,
        typer.Option(
            "--reindex/--no-reindex",
            help="For a migration key: re-embed memories now, or defer.",
        ),
    ] = None,
    move_data: Annotated[
        bool | None,
        typer.Option(
            "--move-data/--no-move-data",
            help="For data-dir: relocate existing data, or leave it in place.",
        ),
    ] = None,
) -> None:
    """Validate and persist a setting, then run any required follow-up."""
    _require_settings_file()
    try:
        outcome = apply_setting(key, value, reindex=reindex, move_data=move_data)
    except _SettingError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"{outcome.key}: {outcome.old_value!r} → {outcome.new_value!r}")
    for warning in outcome.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if outcome.followup == "reindex":
        typer.echo(
            "  re-embedded stored memories."
            if outcome.followup_done
            else "  deferred re-embed — run `mc-tool-memory reindex` when ready."
        )
    elif outcome.followup == "move-data":
        typer.echo(
            "  moved existing data to the new location."
            if outcome.followup_done
            else "  left existing data at the old location."
        )


@app.command("board")
def board() -> None:
    """Open the interactive kanban board (read-only render when not on a TTY)."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        from mait_code.cli._board_tui import run_board_tui

        run_board_tui()
    else:
        _board_render()


def _board_render() -> None:
    """Print every project's board as grouped text (the non-TTY fallback)."""
    from mait_code.tools.board import service
    from mait_code.tools.board.columns import BOARD_ORDER, label as col_label
    from mait_code.tools.board.db import connection

    with connection() as conn:
        cards = service.list_cards(conn)

    if not cards:
        typer.echo("No cards on the board.")
        return

    by_status: dict[str, list[dict]] = {}
    for card in cards:
        by_status.setdefault(card["status"], []).append(card)

    for status in BOARD_ORDER:
        group = by_status.get(status)
        if not group:
            continue
        typer.echo(f"{col_label(status)} ({len(group)}):")
        for card in group:
            typer.echo(
                f"  [#{card['id']}] ({card['priority']}) {card['title']} "
                f"[{card['project']}]"
            )
        typer.echo("")


@app.command("home")
def home() -> None:
    """Open the companion's home hub (text summary when not on a TTY)."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        _run_home_loop()
    else:
        _home_render()


def _run_home_loop() -> None:
    """Run the home hub, relaunching it after each sibling TUI it hands off to.

    Home exits with a :class:`~mait_code.cli._home_tui.HomeTarget` when the user
    opens the board, memory browser or settings editor; we launch that app
    (which blocks until it quits) and then re-enter a fresh home — so its tree
    badges reflect anything just changed. ``None`` means the user quit home.

    Each TUI runs in turn in this one process: home exits its event loop before
    the next app starts its own, so the loops never nest.
    """
    from mait_code.cli._home_tui import HomeTarget, run_home_tui

    def launch(target: HomeTarget) -> None:
        # Imported lazily, per target — keep the heavy Textual imports off the
        # path of every other `mait-code` subcommand.
        if target is HomeTarget.BOARD:
            from mait_code.cli._board_tui import run_board_tui

            run_board_tui()
        elif target is HomeTarget.MEMORY:
            from mait_code.cli._memory_tui import run_memory_tui

            run_memory_tui()
        elif target is HomeTarget.SETTINGS:
            from mait_code.cli._settings_tui import run_interactive_editor

            run_interactive_editor()

    target = run_home_tui()
    while target is not None:
        launch(target)
        target = run_home_tui()


def _home_render() -> None:
    """Print the home summary as compact text (the non-TTY fallback)."""
    from mait_code.tools.board import service as board_service
    from mait_code.tools.board.db import connection as board_connection
    from mait_code.tools.inbox import service as inbox_service
    from mait_code.tools.inbox.db import connection as inbox_connection
    from mait_code.tools.memory.db import connection as memory_connection
    from mait_code.tools.memory.stats import collect_stats
    from mait_code.tools.reminders.db import connection as reminders_connection
    from mait_code.tools.reminders.service import active_reminders

    with board_connection() as conn:
        cards = board_service.list_cards(conn)
    by_project: dict[str, dict[str, int]] = {}
    for card in cards:
        counts = by_project.setdefault(card["project"], {})
        counts[card["status"]] = counts.get(card["status"], 0) + 1
    typer.echo("Board:")
    if not by_project:
        typer.echo("  no cards")
    for project in sorted(by_project):
        counts = by_project[project]
        live = " · ".join(
            f"{n} {status.replace('_', ' ')}"
            for status, n in counts.items()
            if status != "done" and n
        )
        typer.echo(f"  {project}: {live or 'all done'}")

    with reminders_connection() as conn:
        overdue, upcoming = active_reminders(conn)
    typer.echo(f"Reminders: {len(overdue)} overdue · {len(upcoming)} upcoming")

    with inbox_connection() as conn:
        inbox_count = inbox_service.count_items(conn)
    typer.echo(f"Inbox: {inbox_count}")

    with memory_connection() as conn:
        stats = collect_stats(conn)
    typer.echo(
        f"Memory: {stats.total} entries · {stats.unembedded} unembedded · "
        f"{stats.unreflected} unreflected"
    )


@app.command("memory")
def memory() -> None:
    """Browse stored memories read-only (grouped summary when not on a TTY)."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        from mait_code.cli._memory_tui import run_memory_tui

        run_memory_tui()
    else:
        _memory_render()


def _memory_render() -> None:
    """Print the store as a grouped summary (the non-TTY fallback)."""
    from mait_code.tools.memory.db import connection
    from mait_code.tools.memory.search import list_entries

    with connection() as conn:
        entries = list_entries(conn, limit=100_000)

    if not entries:
        typer.echo("No memories stored yet.")
        return

    by_type: dict[str, list[dict]] = {}
    for entry in entries:
        by_type.setdefault(entry["entry_type"], []).append(entry)

    for entry_type in sorted(by_type, key=lambda t: -len(by_type[t])):
        group = by_type[entry_type]
        typer.echo(f"{entry_type} ({len(group)}):")
        for entry in group[:5]:
            first_line = entry["content"].strip().splitlines()[0]
            typer.echo(f"  [#{entry['id']}] {entry['created_at'][:10]} {first_line}")
        if len(group) > 5:
            typer.echo(f"  … and {len(group) - 5} more")
        typer.echo("")


def main() -> None:
    """Console-script entry point declared in ``pyproject.toml``."""
    app()


if __name__ == "__main__":
    main()
