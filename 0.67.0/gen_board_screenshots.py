"""Generate the board documentation screenshots from the TUI snapshot baselines.

The board guide (``docs/board.md``) embeds screenshots of the live TUI. Those
start as the very SVG artefacts the snapshot suite renders under
``tests/cli/__snapshots__/`` — so they stay accurate automatically: whenever the
board's look changes, the snapshot baseline is regenerated and this script
renders it afresh.

The board now wears the brand banner, block-shadow wordmark and all, so the shots
are rasterised through headless Chrome rather than published as SVG (an SVG seams
across the block art — see :mod:`_screenshots` for the full why and the machine
requirements). The card-detail shots sit at a normal width with the masthead
behind the modal.

Regeneration workflow::

    uv run pytest tests/cli/test_board_tui_snapshot.py --snapshot-update
    uv run python docs/gen_board_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

from _screenshots import find_chrome, render_png, retheme_font

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _REPO_ROOT / "tests/cli/__snapshots__/test_board_tui_snapshot"
_ASSETS = _REPO_ROOT / "docs/assets/board"

#: snapshot baseline (stem) -> published asset filename.
_SCREENSHOTS = {
    "test_board_rich_snapshot": "board.png",
    "test_board_rich_expanded_snapshot": "board-expanded.png",
    "test_detail_full_snapshot": "card-detail.png",
    "test_detail_markdown_snapshot": "card-detail-markdown.png",
}


def main() -> None:
    chrome = find_chrome()
    _ASSETS.mkdir(parents=True, exist_ok=True)
    for stem, asset in _SCREENSHOTS.items():
        source = _SNAPSHOTS / f"{stem}.raw"
        if not source.exists():
            raise FileNotFoundError(
                f"missing snapshot baseline {source} — run the snapshot suite with "
                "--snapshot-update first."
            )
        render_png(chrome, retheme_font(source.read_text()), _ASSETS / asset)
        print(f"wrote docs/assets/board/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
