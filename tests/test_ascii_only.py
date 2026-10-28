"""Guard the ASCII-only rule for comments, docstrings and shipped prose.

The ``code-comments`` skill's Rule 7 keeps every comment and docstring plain
ASCII, because source is read through diffs, pagers and terminals that render
anything else wrongly. The shipped skill and agent markdown is held to the same
standard, as prose that ``outward-comms`` asks to be ASCII.

String literals are deliberately out of scope: TUI glyphs and test fixtures
need their characters. So is ``templates/``, whose seeded files belong to the
user and use some characters on purpose, and so are comments in shell scripts,
workflows and the mod's TypeScript, which are too few to be worth a scanner.

A comment or docstring that refers to a specific glyph the code renders or
handles quotes it, and :data:`ALLOWED` records the pair with its reason.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PYTHON_ROOTS = ("src", "tests", "docs", "scripts")

#: Shipped prose checked as whole files.
MARKDOWN_GLOBS = ("skills/**/*.md", "agents/*.md", "config/CLAUDE.md")

#: Per file, the characters it may contain, each mapped to why.
ALLOWED: dict[str, dict[str, str]] = {
    # Python: comments and docstrings quoting a glyph the code renders.
    "src/mait_code/cli/_board_tui.py": {
        "✕": "the tag, reference and link remove buttons",
        "·": "the card meta line's separator",
    },
    "src/mait_code/cli/_home_tui.py": {
        "↗": "the launch leaves' glyph",
    },
    "src/mait_code/cli/_initiatives_tui.py": {
        "…": "the diagram title's truncation mark",
    },
    "src/mait_code/cli/_settings_tui.py": {
        "⚠": "the migration marker",
    },
    "src/mait_code/console.py": {
        "✗": "the error line's glyph",
        "●": "the warning line's glyph",
        "✓": "the success line's glyph",
    },
    "src/mait_code/tools/board/export.py": {
        "·": "the run header and progress separator",
        "—": "the run step's reason separator",
        "←": "the current-step marker",
    },
    "src/mait_code/tools/memory/reflect.py": {
        "→": "the preview's rewrite marker",
    },
    "src/mait_code/tui/app.py": {
        "←": "the footer's key display",
    },
    "src/mait_code/tui/brand.py": {
        "█": "the wordmark's fill",
    },
    "tests/cli/test_board_tui.py": {
        "✕": "the tag remove button",
    },
    "tests/cli/test_dispatch.py": {
        "…": "the truncation line",
    },
    "tests/cli/test_graph_tui.py": {
        "─": "the graph table's relationship arrow",
        "▶": "the graph table's relationship arrow",
    },
    "tests/cli/test_home_tui.py": {
        "↗": "the launch leaves' labels",
    },
    "tests/tools/memory/test_cli.py": {
        "→": "the outgoing relationship marker",
        "←": "the incoming relationship marker",
    },
    "tests/tui/test_brand.py": {
        "█": "the wordmark's fill",
        "╗": "the wordmark's shadow",
    },
    # Markdown.
    "skills/outward-comms/SKILL.md": {
        "é": "the description spells cliches as a loanword",
        "—": "the pre-send pass searches for the literal em dash",
        "–": "the pre-send pass searches for the literal en dash",
    },
    "skills/memory-store/SKILL.md": {
        "⚠": "quotes the store command's contradiction warning",
        "…": "quotes the store command's contradiction warning",
    },
    "skills/reflect/SKILL.md": {
        "→": "the preview's rewrite marker",
    },
}

Offence = tuple[int, str]


def _docstring_nodes(tree: ast.Module) -> list[ast.Expr]:
    """String-expression statements directly in a module, class or function body.

    This covers the leading docstring and the attribute docstrings that follow
    an assignment, both of which mkdocstrings renders.
    """
    bodies = [tree.body] + [
        node.body
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return [
        stmt
        for body in bodies
        for stmt in body
        if isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    ]


def _docstring_lines(source: str, node: ast.Expr) -> list[tuple[int, str]]:
    """The node's own text, line by line, without code sharing its first or last line.

    ``ast`` column offsets count UTF-8 bytes, so each line is sliced as bytes.
    """
    lines = source.splitlines()
    end = node.end_lineno or node.lineno
    spans = []
    for lineno in range(node.lineno, end + 1):
        raw = lines[lineno - 1].encode()
        stop = node.end_col_offset if lineno == end else None
        start = node.col_offset if lineno == node.lineno else 0
        spans.append((lineno, raw[start:stop].decode()))
    return spans


def python_offences(
    source: str, allowed: frozenset[str] = frozenset()
) -> list[Offence]:
    """``(line, character)`` for each non-ASCII character in a comment or docstring."""
    found: list[Offence] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            found += [(tok.start[0], ch) for ch in tok.string if not ch.isascii()]
    for node in _docstring_nodes(ast.parse(source)):
        for lineno, text in _docstring_lines(source, node):
            found += [(lineno, ch) for ch in text if not ch.isascii()]
    return sorted({(lineno, ch) for lineno, ch in found if ch not in allowed})


def markdown_offences(
    text: str, allowed: frozenset[str] = frozenset()
) -> list[Offence]:
    """``(line, character)`` for every non-ASCII character not in ``allowed``."""
    return [
        (lineno, ch)
        for lineno, line in enumerate(text.splitlines(), 1)
        for ch in line
        if not ch.isascii() and ch not in allowed
    ]


def _allowed(path: Path) -> frozenset[str]:
    rel = path.relative_to(ROOT).as_posix()
    return frozenset(ALLOWED.get(rel, {}))


def _report(path: Path, offences: list[Offence]) -> list[str]:
    rel = path.relative_to(ROOT)
    return [f"{rel}:{lineno}: U+{ord(ch):04X} {ch!r}" for lineno, ch in offences]


PYTHON_FILES = sorted(
    path for root in PYTHON_ROOTS for path in (ROOT / root).rglob("*.py")
)
MARKDOWN_FILES = sorted(path for glob in MARKDOWN_GLOBS for path in ROOT.glob(glob))


def test_files_were_discovered() -> None:
    """A glob that silently matches nothing would make the guards below vacuous."""
    assert len(PYTHON_FILES) > 100, f"only {len(PYTHON_FILES)} Python files found"
    assert len(MARKDOWN_FILES) > 10, f"only {len(MARKDOWN_FILES)} markdown files found"


def test_python_comments_and_docstrings_are_ascii() -> None:
    problems = [
        line
        for path in PYTHON_FILES
        for line in _report(path, python_offences(path.read_text(), _allowed(path)))
    ]
    assert problems == []


def test_shipped_markdown_is_ascii() -> None:
    problems = [
        line
        for path in MARKDOWN_FILES
        for line in _report(path, markdown_offences(path.read_text(), _allowed(path)))
    ]
    assert problems == []


def test_allowlist_entries_are_still_needed() -> None:
    """An allowance whose character has gone from its file is stale."""
    stale = [
        (file, ch)
        for file, chars in ALLOWED.items()
        for ch in chars
        if ch not in (ROOT / file).read_text()
    ]
    assert stale == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = 1  # a \u2014 b\n", [(1, "\u2014")]),
        ('"""Module \u2192 doc."""\n', [(1, "\u2192")]),
        ('def f():\n    """Line one.\n\n    Two \u2026\n    """\n', [(4, "\u2026")]),
        ('X = 1\n"""Attribute \u00b7 doc."""\n', [(2, "\u00b7")]),
        ('class C:\n    y = 2\n    """Class attribute \u2264."""\n', [(3, "\u2264")]),
    ],
    ids=[
        "comment",
        "module-docstring",
        "function-docstring",
        "attribute",
        "class-attribute",
    ],
)
def test_python_offences_finds(source: str, expected: list[Offence]) -> None:
    assert python_offences(source) == expected


def test_python_offences_ignores_string_literals() -> None:
    source = 'GLYPH = "\u2713"\nprint(f"{GLYPH} done \u2014 ok")\nx = ["\u25b6"]\n'
    assert python_offences(source) == []


def test_python_offences_ignores_a_literal_sharing_the_docstring_line() -> None:
    source = 'def f(x="\u2192"): """Doc \u00b7 here."""  # ok\n'
    assert python_offences(source) == [(1, "\u00b7")]


def test_python_offences_honours_the_allowance() -> None:
    source = "# a \u2715 b \u2192 c\n"
    assert python_offences(source, frozenset("\u2715")) == [(1, "\u2192")]


def test_markdown_offences_honours_the_allowance() -> None:
    text = "Search for \u2014.\nAnd \u2192 too.\n"
    assert markdown_offences(text, frozenset("\u2014")) == [(2, "\u2192")]
