"""The shared mait-code masthead — the brand banner worn by every TUI.

Wraps the wordmark from :mod:`mait_code.tui.brand` in a Textual container so the
home hub, the settings editor and the memory browser all wear one identity, in
place of the stock Textual header. Width-aware: the wordmark degrades to its
plain-text fallback on narrow terminals, re-rendered on resize — the banner owns
that, so callers just ``yield BrandBanner(subtitle="…")``.

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
    """

    def __init__(self, *, subtitle: str = "", id: str | None = "brand") -> None:
        super().__init__(id=id)
        self._subtitle = subtitle

    def compose(self) -> ComposeResult:
        # The wordmark text is set on mount (it's width-dependent); compose just
        # lays out the empty Static so the meta can sit beside it.
        yield Static(id="wordmark")
        with Vertical(id="brand-meta"):
            yield Static(self._subtitle, id="brand-subtitle")
            yield Static(f"{GLYPH} {TAGLINE}", id="tagline")
            yield Static(f"v{installed_version()}", id="version")

    def on_mount(self) -> None:
        self._render_wordmark()

    def on_resize(self) -> None:
        # The wordmark is width-dependent (art vs plain fallback); re-render on
        # resize so a shrinking terminal degrades instead of wrapping.
        self._render_wordmark()

    def set_subtitle(self, text: str) -> None:
        """Update the view-name line — for surfaces folding live state into it."""
        self._subtitle = text
        self.query_one("#brand-subtitle", Static).update(text)

    def _render_wordmark(self) -> None:
        self.query_one("#wordmark", Static).update(wordmark(self.app.size.width))
