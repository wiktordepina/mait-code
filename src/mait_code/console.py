"""Shared rich console for mait-code CLI output.

A single themed :class:`~rich.console.Console` so colour handling is
consistent and correct across commands. Rich auto-disables colour when
stdout is not a TTY, when ``NO_COLOR`` is set (non-empty, any value),
when ``TERM=dumb``, and it honours ``FORCE_COLOR`` — so commands print
*through* this console rather than hand-rolling ANSI escapes. A global
``--no-color`` flag flips :attr:`console.no_color <rich.console.Console.no_color>`.

JSON output paths must bypass the console entirely and print plain
``json.dumps``; colour never belongs in machine-readable output.
"""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.theme import Theme

from mait_code.tui import palette as p

__all__ = [
    # Console
    "THEME",
    "console",
    "err_console",
    # Glyphs
    "GLYPH",
    # Helpers
    "print_error",
    "print_success",
    "print_warning",
]


#: Semantic styles shared across status, doctor and settings output. The
#: ``ok``/``warn``/``fail`` keys deliberately match the doctor check levels,
#: so ``[ok]…[/ok]`` markup and ``style="warn"`` both resolve here. Colours come
#: from :mod:`mait_code.tui.palette` &mdash; the single source of truth shared with
#: the TUI theme &mdash; so plain CLI output and the TUIs read as one product.
#: ``muted`` stays the terminal-relative ``dim`` attribute rather than a fixed
#: grey, to keep low-emphasis output legible on any background.
THEME = Theme(
    {
        "ok": p.SUCCESS,
        "warn": p.WARNING,
        "fail": f"{p.ERROR} bold",
        "muted": "dim",
        "accent": p.PRIMARY,
    }
)

#: The process-wide console. ``highlight=False`` keeps rich from
#: auto-colouring numbers and quoted strings in our controlled output.
console = Console(theme=THEME, highlight=False)

#: The stderr twin of :data:`console`, for errors and warnings. Same theme,
#: so ``[fail]`` markup resolves identically, but writes to stderr — keeping
#: diagnostics off stdout so piped/JSON consumers stay clean. Colour is still
#: auto-disabled when stderr is not a TTY (or ``NO_COLOR`` is set).
err_console = Console(theme=THEME, highlight=False, stderr=True)

#: Severity glyphs, keyed by the doctor check levels.
GLYPH = {"ok": "✓", "warn": "●", "fail": "✗"}


def print_error(message: str) -> None:
    """Print a themed error line to stderr: a red-bold ``✗`` and the message.

    The single funnel for user-facing error output so every command surfaces
    failures the same way the ``doctor`` checks do. ``message`` is treated as
    plain text — it is escaped before rendering, since it usually carries an
    exception string or a filesystem path that may contain ``[`` and would
    otherwise be misread as rich markup.
    """
    err_console.print(
        f"{GLYPH['fail']} {escape(message)}", style="fail", soft_wrap=True
    )


def print_warning(message: str) -> None:
    """Print a themed warning line to stderr: an amber ``●`` and the message.

    Like :func:`print_error` but for non-fatal advisories — a skipped step, a
    preserved file, a degraded mode. ``message`` is escaped, not interpreted.
    """
    err_console.print(
        f"{GLYPH['warn']} {escape(message)}", style="warn", soft_wrap=True
    )


def print_success(message: str) -> None:
    """Print a themed success headline to stdout: a green ``✓`` and the message.

    The positive counterpart to :func:`print_error`, for the one-line "it
    worked" headline a command leads with (install/update/uninstall). Detail
    lines below it are printed plainly. ``message`` is escaped, not interpreted.
    """
    console.print(f"{GLYPH['ok']} {escape(message)}", style="ok", soft_wrap=True)
