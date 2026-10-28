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
behind the modal. The Initiatives view is its own snapshot suite but documents
inside the board guide, so its shots publish here too.

Regeneration workflow::

    uv run pytest tests/cli/test_board_tui_snapshot.py \
        tests/cli/test_initiatives_tui_snapshot.py --snapshot-update
    uv run python docs/gen_board_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

from _screenshots import find_chrome, render_png, retheme_font

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOT_ROOT = _REPO_ROOT / "tests/cli/__snapshots__"
_ASSETS = _REPO_ROOT / "docs/assets/board"

#: (snapshot suite dir, baseline stem) -> published asset filename.
_SCREENSHOTS = {
    ("test_board_tui_snapshot", "test_board_rich_snapshot"): "board.png",
    (
        "test_board_tui_snapshot",
        "test_board_rich_expanded_snapshot",
    ): "board-expanded.png",
    ("test_board_tui_snapshot", "test_detail_full_snapshot"): "card-detail.png",
    (
        "test_board_tui_snapshot",
        "test_detail_markdown_snapshot",
    ): "card-detail-markdown.png",
    ("test_initiatives_tui_snapshot", "test_initiatives_snapshot"): "initiatives.png",
    (
        "test_initiatives_tui_snapshot",
        "test_diagram_snapshot",
    ): "initiatives-diagram.png",
}


def main() -> None:
    chrome = find_chrome()
    _ASSETS.mkdir(parents=True, exist_ok=True)
    for (suite, stem), asset in _SCREENSHOTS.items():
        source = _SNAPSHOT_ROOT / suite / f"{stem}.raw"
        if not source.exists():
            raise FileNotFoundError(
                f"missing snapshot baseline {source} — run the snapshot suite with "
                "--snapshot-update first."
            )
        render_png(chrome, retheme_font(source.read_text()), _ASSETS / asset)
        print(f"wrote docs/assets/board/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
