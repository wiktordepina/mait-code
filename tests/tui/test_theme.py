"""Contrast guards for the house themes.

Every house theme promises its foreground clears WCAG AA (>=4.5:1) on each of
the three base surfaces, and that the role colours used as chip/heading *text*
stay at least AA-large (>=3:1) on the background. These tests hold new or tuned
themes to that contract so a pretty-but-illegible palette can't slip in.
"""

from __future__ import annotations

import pytest

from mait_code.tui.theme import HOUSE_THEMES


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = (int(h[i : i + 2], 16) for i in (0, 2, 4))

    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", HOUSE_THEMES, ids=lambda t: t.name)
def test_foreground_clears_aa_on_every_base(theme) -> None:
    for base in (theme.background, theme.surface, theme.panel):
        assert _contrast(theme.foreground, base) >= 4.5, (
            f"{theme.name}: foreground on {base} is below AA"
        )


@pytest.mark.parametrize("theme", HOUSE_THEMES, ids=lambda t: t.name)
def test_role_colours_legible_as_text(theme) -> None:
    roles = {
        "primary": theme.primary,
        "secondary": theme.secondary,
        "accent": theme.accent,
        "success": theme.success,
        "warning": theme.warning,
        "error": theme.error,
    }
    for name, colour in roles.items():
        if colour is None:
            continue
        ratio = _contrast(colour, theme.background)
        assert ratio >= 3.0, (
            f"{theme.name}: {name} ({colour}) on background is {ratio:.2f}, below AA-large"
        )


# -- theme_palette: the colours handed to consumers outside Python -------------


@pytest.mark.parametrize("theme", HOUSE_THEMES, ids=lambda t: t.name)
def test_palette_keeps_house_colours_exact(theme) -> None:
    from mait_code.tui.theme import theme_palette

    name, colours = theme_palette(theme.name)
    assert name == theme.name
    assert colours["primary"] == theme.primary.upper()
    assert colours["panel"] == theme.panel.upper()


def test_palette_fills_unset_roles_for_builtins() -> None:
    from mait_code.tui.theme import PALETTE_ROLES, theme_palette

    name, colours = theme_palette("nord")
    assert name == "nord"
    assert set(colours) == set(PALETTE_ROLES)
    assert all(v.startswith("#") and len(v) == 7 for v in colours.values())


@pytest.mark.parametrize("requested", ["no-such-theme", "ansi-dark", ""])
def test_palette_falls_back_to_mait_dark(requested) -> None:
    from mait_code.tui.theme import theme_palette

    assert theme_palette(requested)[0] == "mait-dark"
