"""The mait-code brand moment - wordmark, signature glyph, companion voice.

Pure data and string/Rich helpers (no Textual import - safe anywhere, like
:mod:`~mait_code.tui.palette`). The wordmark is a block-shadow rendering of the
name - bold filled glyphs for a confident brand moment - with a plain-text
fallback for terminals too narrow to hold the art. :func:`wordmark_text`
paints it in the house treatment: a horizontal brand-palette gradient across
the fills, the drop shadow dimmed toward the background so it reads as depth.

The signature glyph (:data:`GLYPH`) is the companion's marker - it leads
every empty-state line (via :func:`empty_state`) so a quiet screen still
sounds like the companion rather than a bare "no data".
"""

from __future__ import annotations

from rich.text import Text

from mait_code.tui import palette

__all__ = [
    "GLYPH",
    "TAGLINE",
    "WORDMARK",
    "WORDMARK_COMPACT",
    "WORDMARK_COMPACT_WIDTH",
    "WORDMARK_PLAIN",
    "WORDMARK_WIDTH",
    "empty_state",
    "wordmark",
    "wordmark_text",
]

#: The companion's signature glyph - a small spark, not a logo.
GLYPH = "✦"

#: One-line self-description, rendered beside or under the wordmark.
TAGLINE = "your coding companion"

#: Block-shadow wordmark, six rows tall - filled glyphs with a drop shadow for
#: a bold brand statement. Rendered in the theme's primary colour.
WORDMARK = (
    "███╗   ███╗ █████╗ ██╗████████╗    ██████╗ ██████╗ ██████╗ ███████╗\n"
    "████╗ ████║██╔══██╗██║╚══██╔══╝   ██╔════╝██╔═══██╗██╔══██╗██╔════╝\n"
    "██╔████╔██║███████║██║   ██║█████╗██║     ██║   ██║██║  ██║█████╗  \n"
    "██║╚██╔╝██║██╔══██║██║   ██║╚════╝██║     ██║   ██║██║  ██║██╔══╝  \n"
    "██║ ╚═╝ ██║██║  ██║██║   ██║      ╚██████╗╚██████╔╝██████╔╝███████╗\n"
    "╚═╝     ╚═╝╚═╝  ╚═╝╚═╝   ╚═╝       ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝"
)

#: Half-height wordmark, three rows tall - the full :data:`WORDMARK` collapsed
#: 2:1 into half-block glyphs. A lighter brand moment for surfaces that can't
#: spare seven rows for a masthead (the board wears this so the columns keep
#: their height). Carries the same hyphen bar across its middle row.
WORDMARK_COMPACT = (
    "█▄ ▄█ ▄▀▀▀▄ ▀█▀ ▀▀█▀▀      ▄▀▀▀▀ ▄▀▀▀▄ █▀▀▀▄ █▀▀▀▀\n"
    "█ ▀ █ █▄▄▄█  █    █   ████ █     █   █ █   █ █▀▀▀ \n"
    "█   █ █   █ ▄█▄   █        ▀▄▄▄▄ ▀▄▄▄▀ █▄▄▄▀ █▄▄▄▄"
)

#: Fallback for terminals too narrow for the art.
WORDMARK_PLAIN = "mait-code"

#: Columns the block-shadow wordmark needs to render unwrapped.
WORDMARK_WIDTH = 67

#: Columns the half-height wordmark needs to render unwrapped.
WORDMARK_COMPACT_WIDTH = 50


def wordmark(width: int, *, compact: bool = False) -> str:
    """Return the wordmark that fits in *width* columns.

    The block-shadow art when there's room, otherwise the plain-text name -
    a wrapped wordmark is worse than no wordmark. With *compact* set, the
    half-height :data:`WORDMARK_COMPACT` stands in for the full art, degrading
    to the same plain-text fallback below its (narrower) width threshold.
    """
    if compact:
        return WORDMARK_COMPACT if width >= WORDMARK_COMPACT_WIDTH else WORDMARK_PLAIN
    return WORDMARK if width >= WORDMARK_WIDTH else WORDMARK_PLAIN


#: The glyphs forming the wordmark's drop shadow - everything that isn't a
#: solid ``█`` fill (or the half-blocks of the compact art, which are all fill).
_SHADOW_GLYPHS = frozenset("╔╗╚╝║═")

#: How far shadow glyphs are blended toward the background (0 = the fill
#: colour, 1 = invisible). 0.55 keeps the shadow legible but clearly behind.
_SHADOW_DIM = 0.55


def _is_hex(colour: str) -> bool:
    if len(colour) != 7 or not colour.startswith("#"):
        return False
    try:
        int(colour[1:], 16)
    except ValueError:
        return False
    return True


def _blend(start: str, end: str, t: float) -> str:
    """The colour *t* (0..1) of the way from *start* to *end* (``#rrggbb``)."""
    channels = (
        round(int(start[i : i + 2], 16) * (1 - t) + int(end[i : i + 2], 16) * t)
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _gradient(stops: tuple[str, str, str], t: float) -> str:
    """The colour *t* (0..1) along a three-stop gradient."""
    first, middle, last = stops
    if t < 0.5:
        return _blend(first, middle, t * 2)
    return _blend(middle, last, (t - 0.5) * 2)


def wordmark_text(
    width: int,
    *,
    compact: bool = False,
    primary: str = palette.PRIMARY,
    secondary: str = palette.SECONDARY,
    accent: str = palette.ACCENT,
    background: str = palette.BACKGROUND,
) -> Text:
    """The wordmark for *width*, painted in the horizon + depth treatment.

    A Rich :class:`~rich.text.Text` carrying a per-column three-stop gradient -
    *primary* -> *secondary* -> *accent* - across the glyph fills, with the
    box-drawing drop shadow additionally blended toward *background* so it
    sits behind the letters instead of competing with them. The same width
    thresholds as :func:`wordmark` apply; below them the plain-text name is
    returned wearing the same gradient.

    Colours are ``#rrggbb`` strings, typically the active theme's. A slot the
    blend maths can't work on - an ansi theme's named colour, say - falls back
    to the house palette for that slot, so the brand moment never crashes on
    an exotic theme.
    """
    stops = (
        primary if _is_hex(primary) else palette.PRIMARY,
        secondary if _is_hex(secondary) else palette.SECONDARY,
        accent if _is_hex(accent) else palette.ACCENT,
    )
    shade = background if _is_hex(background) else palette.BACKGROUND

    rows = wordmark(width, compact=compact).split("\n")
    span = max(len(row) for row in rows) - 1
    painted = Text()
    for index, row in enumerate(rows):
        if index:
            painted.append("\n")
        for column, glyph in enumerate(row):
            if glyph == " ":
                painted.append(glyph)
                continue
            colour = _gradient(stops, column / span if span else 0.0)
            if glyph in _SHADOW_GLYPHS:
                colour = _blend(colour, shade, _SHADOW_DIM)
            painted.append(glyph, style=colour)
    return painted


def empty_state(message: str) -> str:
    """Prefix companion empty-state copy with the signature glyph."""
    return f"{GLYPH} {message}"
