"""Shared rendering for the documentation TUI screenshots.

Both :mod:`gen_board_screenshots` and :mod:`gen_home_screenshots` turn the TUI
snapshot baselines under ``tests/cli/__snapshots__/`` into the images the guides
embed. Any surface that carries the block-shadow wordmark must be rasterised
through headless Chrome rather than published as SVG: a terminal fills each
character cell edge to edge, so the block art tiles seamlessly, but an SVG export
places glyphs on a grid whose row pitch is a few pixels taller than the glyph,
leaving horizontal seams across the wordmark — and the SVG only renders in
*GeistMono Nerd Font Mono* on machines that have it installed. Rendering the
rethemed SVG through Chrome (which uses the locally installed GeistMono and fills
the cells like a terminal) and publishing the *raster* result gives every reader
the same crisp rendering, no font required at their end.

Every TUI now wears the brand banner — wordmark and all — so both generators use
this PNG path; this module is the single home for the font retheme and the Chrome
pipeline they share.

Requirements (the doc author's machine, not CI — CI just builds the committed
PNGs): a Chromium/Chrome binary on ``PATH`` and the GeistMono Nerd Font installed.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

#: Body font stack written into the SVG before rendering. GeistMono first (the
#: house terminal font, which fills the cell so the wordmark tiles), Fira Code as
#: the fallback for any glyph it lacks (box-drawing, arrows, symbols).
_FONT_STACK = "'GeistMono Nerd Font Mono', Fira Code, monospace"
_RICH_FONT_DECL = "font-family: Fira Code, monospace;"
_DOCS_FONT_DECL = f"font-family: {_FONT_STACK};"

#: Render at 2× for crisp text on high-DPI displays.
_SCALE = 2

#: Chrome binaries to try, in order.
_CHROME_BINARIES = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

_VIEWBOX = re.compile(r'viewBox="0 0 ([\d.]+) ([\d.]+)"')


def find_chrome() -> str:
    """Return the first Chrome/Chromium binary on ``PATH``, or raise."""
    for name in _CHROME_BINARIES:
        if path := shutil.which(name):
            return path
    raise RuntimeError(
        "no Chrome/Chromium binary found on PATH (tried "
        f"{', '.join(_CHROME_BINARIES)}); the doc screenshots are rendered "
        "through a headless browser so the GeistMono wordmark tiles cleanly."
    )


def retheme_font(svg: str) -> str:
    """Put GeistMono Nerd Font Mono at the front of the SVG's body font stack."""
    if _RICH_FONT_DECL not in svg:
        raise ValueError(
            "expected Rich font declaration not found — has the SVG export format "
            "changed? Update _RICH_FONT_DECL in docs/_screenshots.py."
        )
    return svg.replace(_RICH_FONT_DECL, _DOCS_FONT_DECL)


def _viewbox_size(svg: str) -> tuple[int, int]:
    match = _VIEWBOX.search(svg)
    if not match:
        raise ValueError("no viewBox on the SVG — cannot size the render window.")
    return math.ceil(float(match.group(1))), math.ceil(float(match.group(2)))


def render_png(chrome: str, svg: str, out: Path) -> None:
    """Rasterise *svg* to *out* through headless Chrome at the house font."""
    width, height = _viewbox_size(svg)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "shot.svg"
        src.write_text(svg)
        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--hide-scrollbars",
                f"--force-device-scale-factor={_SCALE}",
                f"--window-size={width},{height}",
                "--default-background-color=00000000",  # transparent outside the panel
                "--virtual-time-budget=2000",  # let fonts settle before the shot
                f"--screenshot={out}",
                src.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
