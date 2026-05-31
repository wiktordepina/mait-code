"""The mait-code Textual theme(s), built from the shared palette.

This module imports Textual, so keep it off the CLI hot path &mdash; CLI code that
only needs colours should import :mod:`mait_code.tui.palette` instead.
"""

from __future__ import annotations

from textual.theme import Theme

from mait_code.tui import palette as p

__all__ = [
    "MAIT_DARK",
    "MAIT_BUBBLEGUM",
    "MAIT_AURORA",
    "MAIT_EMBER",
    "MAIT_SYNTAX",
    "HOUSE_THEMES",
]


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

#: A warm dark theme: amber and gold over a roasted-brown base, with a teal
#: secondary and mauve accent for cool relief. The counterpoint to the cool
#: mait-dark/aurora and the neon bubblegum.
MAIT_EMBER = Theme(
    name="mait-ember",
    primary="#F2A65A",  # amber — frame, hints, #id
    secondary="#6FB3B8",  # teal — comment bar
    accent="#C98BB9",  # mauve — section heads
    foreground="#ECE3D8",  # warm off-white
    background="#1A1512",  # roasted brown-charcoal
    surface="#241D18",
    panel="#2F2620",
    success="#9DBF6E",
    warning="#E8C547",
    error="#E5604D",
    dark=True,
    variables=_house_variables("#F2A65A"),
)

#: A theme drawn from a syntax-highlighted code screenshot: teal, gold, orange,
#: violet, green and pink on a near-black base &mdash; the vivid multi-hue look of
#: a code editor.
MAIT_SYNTAX = Theme(
    name="mait-syntax",
    primary="#45BFA8",  # teal — frame, hints, #id (the `def` colour)
    secondary="#E8975C",  # orange — comment bar (params)
    accent="#C08CE0",  # violet — section heads (types)
    foreground="#D7DAD2",
    background="#181C1B",  # near-black with a faint teal cast
    surface="#20251F",
    panel="#2A302A",
    success="#8FBF6F",  # green (strings)
    warning="#E6C07B",  # gold (function names)
    error="#F06595",  # pink (keywords)
    dark=True,
    variables=_house_variables("#45BFA8"),
)

#: Themes every :class:`~mait_code.tui.app.MaitApp` registers, in addition to
#: Textual's built-ins (which stay available in the Ctrl+P theme switcher).
#: ``mait-dark`` stays the default (see ``MaitApp.HOUSE_THEME``).
HOUSE_THEMES = (MAIT_DARK, MAIT_BUBBLEGUM, MAIT_AURORA, MAIT_EMBER, MAIT_SYNTAX)
