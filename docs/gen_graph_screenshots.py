"""Generate the graph-explorer documentation screenshots from the TUI snapshot baselines.

The graph guide (``docs/graph.md``) embeds screenshots of the live explorer. Those
start as the very SVG artefacts the snapshot suite renders under
``tests/cli/__snapshots__/`` — so they stay accurate automatically: whenever the
explorer's look changes, the snapshot baseline is regenerated and this script
renders it afresh. The explorer wears the block-shadow wordmark, so the shots are
rasterised through headless Chrome (see :mod:`_screenshots` for why and the
machine requirements).

Regeneration workflow::

    uv run pytest tests/cli/test_graph_tui_snapshot.py --snapshot-update
    uv run python docs/gen_graph_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

from _screenshots import find_chrome, render_png, retheme_font

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _REPO_ROOT / "tests/cli/__snapshots__/test_graph_tui_snapshot"
_ASSETS = _REPO_ROOT / "docs/assets/graph"

#: snapshot baseline (stem) -> published asset filename.
_SCREENSHOTS = {
    "test_graph_view_default": "graph.png",
    "test_table_view": "table.png",
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
        print(f"wrote docs/assets/graph/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
