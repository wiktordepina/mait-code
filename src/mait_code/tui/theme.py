"""The mait-code Textual theme(s), built from the shared palette.

This module imports Textual, so keep it off the CLI hot path &mdash; CLI code that
only needs colours should import :mod:`mait_code.tui.palette` instead.
"""

from __future__ import annotations

from textual.theme import Theme

from mait_code.tui import palette as p

__all__ = ["MAIT_DARK", "MAIT_BUBBLEGUM", "MAIT_AURORA", "HOUSE_THEMES"]


def _house_variables(primary: str) -> dict[str, str]:
    """The theme-variable overrides every house theme shares.

    Border titles and footer key-hints pick up the theme's own primary, and the
    DataTable/OptionList cursor shows by colour rather than reverse-video text.
    """
    return {
        "border-title-color": primary,
        "footer-key-foreground": primary,
        "block-cursor-text-style": "none",
    }


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
    variables=_house_variables(p.PRIMARY),
)

#: The neon option: a Charm/Lipgloss-inspired palette &mdash; saturated hot pink,
#: purple and mint on a deep aubergine base. Vivid without searing; every role
#: clears WCAG AA against the three bases (see ``test_theme.py``).
MAIT_BUBBLEGUM = Theme(
    name="mait-bubblegum",
    primary="#FF6AC1",  # hot pink — frame, hints, #id
    secondary="#9D7CFF",  # purple — tags
    accent="#4DE8C2",  # mint — section heads
    foreground="#ECE6F5",  # near-white lilac
    background="#161320",  # deep aubergine-charcoal
    surface="#1F1A2E",
    panel="#2A2440",
    success="#6EE787",
    warning="#FFC857",
    error="#FF5C7A",
    dark=True,
    variables=_house_variables("#FF6AC1"),
)

#: The calmer-but-colourful option: keeps a restrained dark base, but actually
#: spreads three hues across the chrome (teal → periwinkle → violet) so it reads
#: more separated than mait-dark without going neon.
MAIT_AURORA = Theme(
    name="mait-aurora",
    primary="#5CC8E0",  # teal-cyan
    secondary="#8C9EFF",  # periwinkle — tags
    accent="#C792EA",  # violet — section heads
    foreground="#D7E0EA",
    background="#0E141B",  # cool slate
    surface="#141C26",
    panel="#1B2532",
    success="#87D96C",
    warning="#F9C560",
    error="#EF6B6B",
    dark=True,
    variables=_house_variables("#5CC8E0"),
)

#: Themes every :class:`~mait_code.tui.app.MaitApp` registers, in addition to
#: Textual's built-ins (which stay available in the Ctrl+P theme switcher).
#: ``mait-dark`` stays the default (see ``MaitApp.HOUSE_THEME``).
HOUSE_THEMES = (MAIT_DARK, MAIT_BUBBLEGUM, MAIT_AURORA)
