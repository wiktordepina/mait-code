"""Generate the board documentation screenshots from the TUI snapshot baselines.

The board guide (``docs/board.md``) embeds SVG screenshots of the live TUI. Those
SVGs are the very same artefacts the snapshot suite renders under
``tests/cli/__snapshots__/`` — so they stay accurate automatically: whenever the
board's look changes, the snapshot baseline is regenerated and this script copies
it across.

It also rewrites the font. Rich exports its terminal SVGs in *Fira Code*; this
swaps the body font-family to *GeistMono Nerd Font Mono* (kept first in the
stack) while leaving Fira Code as the fallback. On a machine with the Geist Mono
Nerd Font installed — i.e. the one these images are generated on — the text
renders in Geist; anywhere the font is absent, and for the box-drawing and symbol
glyphs Geist lacks, it falls back to the bundled Fira Code web font, so borders
stay crisp everywhere.

Regeneration workflow::

    uv run pytest tests/cli/test_board_tui_snapshot.py --snapshot-update
    uv run python docs/gen_board_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

#: Body font stack written into the exported SVGs. Geist Mono first (rendered on
#: the generating machine), Fira Code as the portable fallback for everyone else
#: and for the glyphs Geist Mono doesn't carry (box-drawing, arrows, symbols).
_FONT_STACK = "'GeistMono Nerd Font Mono', Fira Code, monospace"

#: Rich's default body font-family declaration, emitted on the ``…-matrix`` rule.
_RICH_FONT_DECL = "font-family: Fira Code, monospace;"
_DOCS_FONT_DECL = f"font-family: {_FONT_STACK};"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _REPO_ROOT / "tests/cli/__snapshots__/test_board_tui_snapshot"
_ASSETS = _REPO_ROOT / "docs/assets/board"

#: snapshot baseline (stem) -> published asset filename.
_SCREENSHOTS = {
    "test_board_rich_snapshot": "board.svg",
    "test_board_rich_expanded_snapshot": "board-expanded.svg",
    "test_detail_full_snapshot": "card-detail.svg",
    "test_detail_markdown_snapshot": "card-detail-markdown.svg",
}


def _retheme_font(svg: str) -> str:
    """Put GeistMono Nerd Font Mono at the front of the body font stack."""
    if _RICH_FONT_DECL not in svg:
        raise ValueError(
            "expected Rich font declaration not found — has the SVG export format "
            "changed? Update _RICH_FONT_DECL in docs/gen_board_screenshots.py."
        )
    return svg.replace(_RICH_FONT_DECL, _DOCS_FONT_DECL)


def main() -> None:
    _ASSETS.mkdir(parents=True, exist_ok=True)
    for stem, asset in _SCREENSHOTS.items():
        source = _SNAPSHOTS / f"{stem}.raw"
        if not source.exists():
            raise FileNotFoundError(
                f"missing snapshot baseline {source} — run the snapshot suite with "
                "--snapshot-update first."
            )
        (_ASSETS / asset).write_text(_retheme_font(source.read_text()))
        print(f"wrote docs/assets/board/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
