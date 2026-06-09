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

#: Fallback for terminals too narrow for the art.
WORDMARK_PLAIN = "mait-code"

#: Columns the block-shadow wordmark needs to render unwrapped.
WORDMARK_WIDTH = 67


def wordmark(width: int) -> str:
    """Return the wordmark that fits in *width* columns.

    The block-shadow art when there's room, otherwise the plain-text name —
    a wrapped wordmark is worse than no wordmark.
    """
    return WORDMARK if width >= WORDMARK_WIDTH else WORDMARK_PLAIN


def empty_state(message: str) -> str:
    """Prefix companion empty-state copy with the signature glyph."""
    return f"{GLYPH} {message}"
