"""Generate the home-hub documentation screenshots from the TUI snapshot baselines.

The home guide (``docs/home.md``) embeds screenshots of the live hub. Those start
as the very SVG artefacts the snapshot suite renders under
``tests/cli/__snapshots__/`` — so they stay accurate automatically: whenever the
hub's look changes, the snapshot baseline is regenerated and this script renders
it afresh. The hub's hero is the block-shadow wordmark, so the shots are
rasterised through headless Chrome (see :mod:`_screenshots` for why and the
machine requirements).

Regeneration workflow::

    uv run pytest tests/cli/test_home_tui_snapshot.py --snapshot-update
    uv run python docs/gen_home_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

from _screenshots import find_chrome, render_png, retheme_font

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _REPO_ROOT / "tests/cli/__snapshots__/test_home_tui_snapshot"
_ASSETS = _REPO_ROOT / "docs/assets/home"

#: snapshot baseline (stem) -> published asset filename.
_SCREENSHOTS = {
    "test_home_populated_snapshot": "home.png",
    "test_home_board_detail_snapshot": "home-detail.png",
    "test_home_sysprompt_snapshot": "home-sysprompt.png",
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
        print(f"wrote docs/assets/home/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
