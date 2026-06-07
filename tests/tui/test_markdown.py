"""Unit tests for the shared body-markdown parser factory.

Moved here from the board TUI tests when the parser was folded into
``mait_code.tui.markdown`` (the memory browser renders bodies through the same
factory, so the behaviour is a shared-layer contract now).
"""

from __future__ import annotations

from mait_code.tui.markdown import md_parser


class TestMarkdownParser:
    """The shared parser factory behind the body Markdown widgets."""

    def test_single_newlines_become_hardbreak_tokens(self) -> None:
        """Single newlines must surface as ``hardbreak`` tokens, not
        ``softbreak``. Textual's Markdown widget keys off the token *type* and
        renders a softbreak as a space, so this token rewrite — not markdown-it's
        render-only ``breaks`` option — is what keeps a plain-text body's
        line-per-item newlines as line breaks. A regression here is invisible in
        a unit that only checks HTML output, but collapses plain notes into a
        wall of text in the TUI."""
        inline = [t for t in md_parser().parse("a\nb\nc") if t.type == "inline"]
        child_types = [c.type for c in inline[0].children]
        assert child_types == ["text", "hardbreak", "text", "hardbreak", "text"]
        assert "softbreak" not in child_types

    def test_structural_markdown_still_parses(self) -> None:
        """The hard-break rewrite must not disturb real markdown structure."""
        tokens = {t.type for t in md_parser().parse("## H\n\n- a\n- b\n\n**x**")}
        assert {"heading_open", "bullet_list_open", "list_item_open"} <= tokens
