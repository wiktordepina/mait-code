"""Guard the ASCII-only rule for comments, docstrings and shipped prose.

The ``code-comments`` skill's Rule 7 keeps every comment and docstring plain
ASCII, because source is read through diffs, pagers and terminals that render
anything else wrongly. The shipped skill and agent markdown is held to the same
standard, as prose that ``outward-comms`` asks to be ASCII.

String literals are deliberately out of scope: TUI glyphs and test fixtures
need their characters. A docstring that has to mention a glyph names it by
escape or Unicode name instead.
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

#: ``(file, character)`` pairs a markdown file may contain, mapped to why.
MARKDOWN_ALLOWED = {
    (
        "skills/outward-comms/SKILL.md",
        "\u00e9",
    ): "the description spells cliches as a loanword",
    (
        "skills/outward-comms/SKILL.md",
        "\u2014",
    ): "the pre-send pass searches for the literal em dash",
    (
        "skills/outward-comms/SKILL.md",
        "\u2013",
    ): "the pre-send pass searches for the literal en dash",
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


def python_offences(source: str) -> list[Offence]:
    """``(line, character)`` for every non-ASCII character in a comment or docstring."""
    found: list[Offence] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            found += [(tok.start[0], ch) for ch in tok.string if not ch.isascii()]
    lines = source.splitlines()
    for node in _docstring_nodes(ast.parse(source)):
        end = node.end_lineno or node.lineno
        for lineno in range(node.lineno, end + 1):
            found += [(lineno, ch) for ch in lines[lineno - 1] if not ch.isascii()]
    return sorted(set(found))


def markdown_offences(text: str, allowed: set[str]) -> list[Offence]:
    """``(line, character)`` for every non-ASCII character not in ``allowed``."""
    return [
        (lineno, ch)
        for lineno, line in enumerate(text.splitlines(), 1)
        for ch in line
        if not ch.isascii() and ch not in allowed
    ]


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
        for line in _report(path, python_offences(path.read_text()))
    ]
    assert problems == []


def test_shipped_markdown_is_ascii() -> None:
    problems: list[str] = []
    for path in MARKDOWN_FILES:
        rel = path.relative_to(ROOT).as_posix()
        allowed = {ch for (file, ch) in MARKDOWN_ALLOWED if file == rel}
        problems += _report(path, markdown_offences(path.read_text(), allowed))
    assert problems == []


def test_markdown_allowlist_entries_are_still_needed() -> None:
    """An allowance whose character has gone from its file is stale."""
    stale = [
        (file, ch)
        for (file, ch) in MARKDOWN_ALLOWED
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


def test_markdown_offences_honours_the_allowance() -> None:
    text = "Search for \u2014.\nAnd \u2192 too.\n"
    assert markdown_offences(text, {"\u2014"}) == [(2, "\u2192")]
