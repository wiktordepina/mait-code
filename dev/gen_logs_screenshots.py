"""Generate the log-viewer documentation screenshots from the snapshot baselines.

The logs guide (``docs/logs.md``) embeds screenshots of the live viewer. Those
start as the very SVG artefacts the snapshot suite renders under
``tests/cli/__snapshots__/`` — so they stay accurate automatically: whenever
the viewer's look changes, the snapshot baseline is regenerated and this script
renders it afresh. The viewer wears the brand banner, block-shadow wordmark and
all, so the shots are rasterised through headless Chrome rather than published
as SVG (an SVG seams across the block art — see :mod:`_screenshots` for the
full why and the machine requirements).

Regeneration workflow::

    uv run pytest tests/cli/test_logs_tui_snapshot.py --snapshot-update
    uv run python docs/gen_logs_screenshots.py
"""

from __future__ import annotations

from pathlib import Path

from _screenshots import find_chrome, render_png, retheme_font

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOTS = _REPO_ROOT / "tests/cli/__snapshots__/test_logs_tui_snapshot"
_ASSETS = _REPO_ROOT / "docs/assets/logs"

#: snapshot baseline (stem) -> published asset filename.
_SCREENSHOTS = {
    "test_logs_snapshot": "logs.png",
    "test_logs_filter_snapshot": "logs-filter.png",
    "test_logs_level_filter_snapshot": "logs-level.png",
    "test_logs_day_detail_snapshot": "logs-day.png",
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
        print(f"wrote docs/assets/logs/{asset}  (from {stem})")


if __name__ == "__main__":
    main()
