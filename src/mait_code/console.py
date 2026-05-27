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

__all__ = [
    # Console
    "THEME",
    "console",
    # Glyphs
    "GLYPH",
]


#: Semantic styles shared across status, doctor and settings output. The
#: ``ok``/``warn``/``fail`` keys deliberately match the doctor check levels,
#: so ``[ok]…[/ok]`` markup and ``style="warn"`` both resolve here.
THEME = Theme(
    {
        "ok": "green",
        "warn": "yellow",
        "fail": "red bold",
        "muted": "dim",
        "accent": "cyan",
    }
)

#: The process-wide console. ``highlight=False`` keeps rich from
#: auto-colouring numbers and quoted strings in our controlled output.
console = Console(theme=THEME, highlight=False)

#: Severity glyphs, keyed by the doctor check levels.
GLYPH = {"ok": "✓", "warn": "●", "fail": "✗"}
