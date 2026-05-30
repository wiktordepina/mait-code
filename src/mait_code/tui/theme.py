"""The mait-code Textual theme(s), built from the shared palette.

This module imports Textual, so keep it off the CLI hot path &mdash; CLI code that
only needs colours should import :mod:`mait_code.tui.palette` instead.
"""

from __future__ import annotations

from textual.theme import Theme

from mait_code.tui import palette as p

__all__ = ["MAIT_DARK", "HOUSE_THEMES"]

#: The house theme: the default identity for every mait-code TUI. Its colours
#: come straight from :mod:`mait_code.tui.palette`, so they match the CLI output.
MAIT_DARK = Theme(
    name="mait-dark",
    primary=p.PRIMARY,
    secondary=p.SECONDARY,
    accent=p.ACCENT,
    foreground=p.FOREGROUND,
    background=p.BACKGROUND,
    surface=p.SURFACE,
    panel=p.PANEL,
    success=p.SUCCESS,
    warning=p.WARNING,
    error=p.ERROR,
    dark=True,
    variables={
        # Border titles and footer key-hints pick up the house cyan.
        "border-title-color": p.PRIMARY,
        "footer-key-foreground": p.PRIMARY,
        # Show the DataTable/OptionList cursor by colour, not reverse-video text.
        "block-cursor-text-style": "none",
    },
)

#: Themes every :class:`~mait_code.tui.app.MaitApp` registers, in addition to
#: Textual's built-ins (which stay available in the Ctrl+P theme switcher).
HOUSE_THEMES = (MAIT_DARK,)
