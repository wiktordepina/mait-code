"""Generate the home-hub documentation screenshots from the TUI snapshot baselines.

The home guide (``docs/home.md``) embeds screenshots of the live hub. Those start
as the very SVG artefacts the snapshot suite renders under
``tests/cli/__snapshots__/`` — so they stay accurate automatically: whenever the
hub's look changes, the snapshot baseline is regenerated and this script renders
it afresh.

**Why PNG (and not SVG like the board).** The hub's hero is the block-shadow
wordmark. A terminal fills each character cell edge to edge, so the block art
tiles seamlessly; an SVG export instead places glyphs on a grid whose row pitch
is a few pixels taller than the glyph, leaving horizontal seams across the
wordmark — and it only renders in *GeistMono Nerd Font Mono* (the house terminal
font) on machines that have it installed, falling back to Fira Code everywhere
else. Rendering the rethemed SVG through headless Chrome — which uses the locally
installed GeistMono and fills the cells like a terminal — and publishing the
*raster* result gives every reader the same crisp, GeistMono rendering, no font
required at their end. The board has no wordmark, so its generator stays on the
lighter SVG path.

Requirements (the doc author's machine, not CI — CI just builds the committed
PNGs): a Chromium/Chrome binary on ``PATH`` and the GeistMono Nerd Font installed.

Regeneration workflow::

    uv run pytest tests/cli/test_home_tui_snapshot.py --snapshot-update
    uv run python docs/gen_home_screenshots.py
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
#: the fallback for any glyph it lacks. Matches gen_board_screenshots.py.
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _REPO_ROOT / "tests/cli/__snapshots__/test_home_tui_snapshot"
_ASSETS = _REPO_ROOT / "docs/assets/home"

#: snapshot baseline (stem) -> published asset filename.
_SCREENSHOTS = {
    "test_home_populated_snapshot": "home.png",
    "test_home_board_detail_snapshot": "home-detail.png",
    "test_home_sysprompt_snapshot": "home-sysprompt.png",
}

_VIEWBOX = re.compile(r'viewBox="0 0 ([\d.]+) ([\d.]+)"')


def _find_chrome() -> str:
    for name in _CHROME_BINARIES:
        if path := shutil.which(name):
            return path
    raise RuntimeError(
        "no Chrome/Chromium binary found on PATH (tried "
        f"{', '.join(_CHROME_BINARIES)}); the home screenshots are rendered "
        "through a headless browser so the GeistMono wordmark tiles cleanly."
    )


def _retheme_font(svg: str) -> str:
    if _RICH_FONT_DECL not in svg:
        raise ValueError(
            "expected Rich font declaration not found — has the SVG export format "
            "changed? Update _RICH_FONT_DECL in docs/gen_home_screenshots.py."
        )
    return svg.replace(_RICH_FONT_DECL, _DOCS_FONT_DECL)


def _viewbox_size(svg: str) -> tuple[int, int]:
    match = _VIEWBOX.search(svg)
    if not match:
        raise ValueError("no viewBox on the SVG — cannot size the render window.")
    return math.ceil(float(match.group(1))), math.ceil(float(match.group(2)))


def _render_png(chrome: str, svg: str, out: Path) -> None:
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


def main() -> None:
    chrome = _find_chrome()
    _ASSETS.mkdir(parents=True, exist_ok=True)
    for stem, asset in _SCREENSHOTS.items():
        source = _SNAPSHOTS / f"{stem}.raw"
        if not source.exists():
            raise FileNotFoundError(
                f"missing snapshot baseline {source} — run the snapshot suite with "
                "--snapshot-update first."
            )
        _render_png(chrome, _retheme_font(source.read_text()), _ASSETS / asset)
        print(f"wrote docs/assets/home/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
