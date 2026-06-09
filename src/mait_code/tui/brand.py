"""The mait-code brand moment — wordmark, signature glyph, companion voice.

Pure data and string helpers (no Textual import — safe anywhere, like
:mod:`~mait_code.tui.palette`). The wordmark is a block-shadow rendering of the
name — bold filled glyphs for a confident brand moment — with a plain-text
fallback for terminals too narrow to hold the art.

The signature glyph (:data:`GLYPH`) is the companion's marker — it leads
every empty-state line (via :func:`empty_state`) so a quiet screen still
sounds like the companion rather than a bare "no data".
"""

from __future__ import annotations

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
]

#: The companion's signature glyph — a small spark, not a logo.
GLYPH = "✦"

#: One-line self-description, rendered beside or under the wordmark.
TAGLINE = "your coding companion"

#: Block-shadow wordmark, six rows tall — filled glyphs with a drop shadow for
#: a bold brand statement. Rendered in the theme's primary colour.
WORDMARK = (
    "███╗   ███╗ █████╗ ██╗████████╗    ██████╗ ██████╗ ██████╗ ███████╗\n"
    "████╗ ████║██╔══██╗██║╚══██╔══╝   ██╔════╝██╔═══██╗██╔══██╗██╔════╝\n"
    "██╔████╔██║███████║██║   ██║█████╗██║     ██║   ██║██║  ██║█████╗  \n"
    "██║╚██╔╝██║██╔══██║██║   ██║╚════╝██║     ██║   ██║██║  ██║██╔══╝  \n"
    "██║ ╚═╝ ██║██║  ██║██║   ██║      ╚██████╗╚██████╔╝██████╔╝███████╗\n"
    "╚═╝     ╚═╝╚═╝  ╚═╝╚═╝   ╚═╝       ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝"
)

#: Half-height wordmark, three rows tall — the full :data:`WORDMARK` collapsed
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

    The block-shadow art when there's room, otherwise the plain-text name —
    a wrapped wordmark is worse than no wordmark. With *compact* set, the
    half-height :data:`WORDMARK_COMPACT` stands in for the full art, degrading
    to the same plain-text fallback below its (narrower) width threshold.
    """
    if compact:
        return WORDMARK_COMPACT if width >= WORDMARK_COMPACT_WIDTH else WORDMARK_PLAIN
    return WORDMARK if width >= WORDMARK_WIDTH else WORDMARK_PLAIN


def empty_state(message: str) -> str:
    """Prefix companion empty-state copy with the signature glyph."""
    return f"{GLYPH} {message}"
