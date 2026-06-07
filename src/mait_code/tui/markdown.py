"""Shared markdown parsing for body-rendering TUI widgets.

The TUIs render free-text body fields (card descriptions, memory content)
through Textual's :class:`~textual.widgets.Markdown` widget. Plain text is a
subset of markdown, so both share one field with no format flag &mdash; provided
single newlines survive as line breaks. :func:`md_parser` is the
``parser_factory`` that makes that true; see :func:`_hard_breaks` for why the
stock ``breaks`` option is not enough.
"""

from __future__ import annotations

from markdown_it import MarkdownIt

__all__ = ["md_parser"]


def _hard_breaks(state) -> None:
    """Core rule: rewrite every ``softbreak`` token to a ``hardbreak``.

    The ``breaks`` *option* only changes markdown-it's HTML renderer (softbreak
    → ``<br>``); the token type stays ``softbreak``, and Textual's Markdown
    widget keys off the token *type*, rendering a softbreak as a space. So the
    option alone is invisible in the TUI. Rewriting the token type is what
    actually lands the hard break in the rendered widget.
    """
    for token in state.tokens:
        if token.type == "inline" and token.children:
            for child in token.children:
                if child.type == "softbreak":
                    child.type = "hardbreak"


def md_parser() -> MarkdownIt:
    """Parser factory for body :class:`~textual.widgets.Markdown` widgets.

    Mirrors Textual's own default (``MarkdownIt("gfm-like")``) but treats every
    single newline as a hard line break (GitHub-comment style). That is what
    lets plain text and markdown share one field with no format flag: a plain
    body written with line-per-item newlines keeps those breaks instead of
    collapsing into one reflowed paragraph, while real markdown still parses
    as markdown.
    """
    md = MarkdownIt("gfm-like")
    md.core.ruler.push("hard_breaks", _hard_breaks)
    return md
