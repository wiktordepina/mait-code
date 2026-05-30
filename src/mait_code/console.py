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
from rich.theme import Theme

from mait_code.tui import palette as p

__all__ = [
    # Console
    "THEME",
    "console",
    # Glyphs
    "GLYPH",
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

#: Severity glyphs, keyed by the doctor check levels.
GLYPH = {"ok": "✓", "warn": "●", "fail": "✗"}
