"""The shared mait-code masthead — the brand banner worn by every TUI.

Wraps the wordmark from :mod:`mait_code.tui.brand` in a Textual container so the
home hub, the settings editor and the memory browser all wear one identity, in
place of the stock Textual header. Callers just ``yield BrandBanner(subtitle="…")``;
the banner owns its own responsiveness, re-rendered on resize: the wordmark
degrades to its plain-text fallback on narrow terminals and to the half-height
:data:`~mait_code.tui.brand.WORDMARK_COMPACT` on short ones (at or below
:data:`~BrandBanner.COMPACT_MAX_HEIGHT` rows), so the full six-row masthead never
crowds a small screen.

The right side carries, vertically centred, the **view name** (e.g. ``"Home
Hub"``, ``"Settings"``, ``"Memory"``) over the companion tagline and the
installed version. The view name is settable at runtime (:meth:`set_subtitle`)
so a surface can fold live state into it — the memory browser shows its match
count there.

Styling is shared (``tui/app.tcss``), keyed off theme ``$``-roles, so every
banner reskins with the active theme.
"""

from __future__ import annotations

import importlib.metadata

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from mait_code.tui.brand import GLYPH, TAGLINE, wordmark

__all__ = ["BrandBanner", "installed_version"]


def installed_version() -> str:
    """The installed package version, falling back to the source tree's.

    The single source of the version string the banner renders — snapshot tests
    pin *this* function so the masthead stays stable across releases.
    """
    try:
        return importlib.metadata.version("mait-code")
    except importlib.metadata.PackageNotFoundError:
        from mait_code import __version__

        return __version__


class BrandBanner(Horizontal):
    """The mait-code masthead: the wordmark plus the view name and companion meta.

    *subtitle* is the view name shown on the right; pass it at construction and,
    if it carries live state, update it later with :meth:`set_subtitle`.

    Height-responsive, like it is width-responsive for the wordmark: on a short
    terminal (at or below :data:`COMPACT_MAX_HEIGHT` rows) it wears the
    half-height :data:`~mait_code.tui.brand.WORDMARK_COMPACT` and adds the
    ``-compact`` class (which the shared stylesheet keys the shorter height off),
    so the full six-row masthead never crowds a small screen. The choice is
    re-made on resize, so dragging a terminal taller restores the full art.
    """

    #: At or below this terminal height (rows), the masthead goes compact — the
    #: full seven-row banner would eat too much of a short screen.
    COMPACT_MAX_HEIGHT = 30

    def __init__(self, *, subtitle: str = "", id: str | None = "brand") -> None:
        super().__init__(id=id)
        self._subtitle = subtitle
        self._compact = False

    def compose(self) -> ComposeResult:
        # The wordmark text is set on mount (it's size-dependent); compose just
        # lays out the empty Static so the meta can sit beside it.
        yield Static(id="wordmark")
        with Vertical(id="brand-meta"):
            yield Static(self._subtitle, id="brand-subtitle")
            yield Static(f"{GLYPH} {TAGLINE}", id="tagline")
            yield Static(f"v{installed_version()}", id="version")

    def on_mount(self) -> None:
        self._render_wordmark()

    def on_resize(self) -> None:
        # The wordmark is size-dependent (full vs compact art by height, art vs
        # plain fallback by width); re-render on resize so the masthead tracks
        # the terminal instead of wrapping or over-spending rows.
        self._render_wordmark()

    def set_subtitle(self, text: str) -> None:
        """Update the view-name line — for surfaces folding live state into it."""
        self._subtitle = text
        self.query_one("#brand-subtitle", Static).update(text)

    def _render_wordmark(self) -> None:
        self._compact = self.app.size.height <= self.COMPACT_MAX_HEIGHT
        self.set_class(self._compact, "-compact")
        self.query_one("#wordmark", Static).update(
            wordmark(self.app.size.width, compact=self._compact)
        )
