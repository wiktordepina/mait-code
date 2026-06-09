"""Render cards as portable markdown or JSON exports.

The rendering layer shared by the CLI ``export`` subcommand and the board
TUI's export binding. Two scopes — a single card or a whole board listing —
in two formats:

- **markdown**: a readable document. Stored markdown in ``description``,
  ``acceptance_criteria`` and ``completion_summary`` is embedded verbatim,
  so what was authored round-trips unchanged.
- **json**: full fidelity, matching the ``show --json`` shape — every card
  carries its ``tags``, ``references`` and ``comments``.

Like :mod:`~mait_code.tools.board.service`, functions here take an open
``sqlite3.Connection`` and raise :class:`~mait_code.tools.board.service.CardNotFound`
rather than printing — presentation concerns stay with the caller.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from mait_code.tools.board import service
from mait_code.tools.board.columns import ARCHIVED, BOARD_ORDER, label

__all__ = [
    # Formats
    "FORMATS",
    "JSON",
    "MARKDOWN",
    # Renderers
    "board_markdown",
    "card_markdown",
    # Exporters
    "export_board",
    "export_card",
]

MARKDOWN = "markdown"
JSON = "json"

#: Supported export formats.
FORMATS: tuple[str, ...] = (MARKDOWN, JSON)


def _heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def _meta_lines(card: dict) -> list[str]:
    """The bullet list of card metadata under the title heading."""
    lines = [
        f"- **Card:** #{card['id']}",
        f"- **Project:** {card['project']}",
        f"- **Status:** {label(card['status'])}",
        f"- **Priority:** {card['priority']}",
    ]
    if card["tags"]:
        lines.append(f"- **Tags:** {', '.join(card['tags'])}")
    lines.append(f"- **Created:** {card['created_at']}")
    lines.append(f"- **Updated:** {card['updated_at']}")
    if card["completed_at"]:
        lines.append(f"- **Completed:** {card['completed_at']}")
    return lines


def _comment_md(comment: dict) -> str:
    """One comment: an attribution line, then the body as a blockquote."""
    quoted = "\n".join(f"> {line}".rstrip() for line in comment["body"].splitlines())
    return f"**{comment['author']}** — {comment['created_at']}\n\n{quoted}"


def card_markdown(card: dict, *, level: int = 1) -> str:
    """Render one card as a markdown document.

    Args:
        card: A card dict as returned by :func:`~mait_code.tools.board.service.get_card`,
            optionally carrying a ``comments`` list.
        level: Heading level for the card title; sections render at
            ``level + 1``. Defaults to a standalone document (``# title``).

    Returns:
        The markdown document, without a trailing newline.
    """
    sub = level + 1
    blocks = [_heading(level, card["title"]), "\n".join(_meta_lines(card))]

    for field, title in (
        ("description", "Description"),
        ("acceptance_criteria", "Acceptance criteria"),
        ("completion_summary", "Completion summary"),
    ):
        if card[field]:
            blocks.append(f"{_heading(sub, title)}\n\n{card[field]}")

    if card["references"]:
        refs = "\n".join(
            f"- **{r['label']}:** {r['value']}" for r in card["references"]
        )
        blocks.append(f"{_heading(sub, 'References')}\n\n{refs}")

    comments = card.get("comments") or []
    if comments:
        rendered = "\n\n".join(_comment_md(c) for c in comments)
        blocks.append(f"{_heading(sub, 'Comments')}\n\n{rendered}")

    return "\n\n".join(blocks)


def board_markdown(cards: Iterable[dict], *, project: str | None = None) -> str:
    """Render a board listing as one markdown document grouped by column.

    Args:
        cards: Card dicts (each optionally carrying ``comments``).
        project: Project name for the document title, or ``None`` for an
            all-projects export.

    Returns:
        The markdown document, without a trailing newline.
    """
    scope = project if project is not None else "all projects"
    blocks = [_heading(1, f"Board export — {scope}")]

    by_status: dict[str, list[dict]] = {}
    for card in cards:
        by_status.setdefault(card["status"], []).append(card)

    for status in (*BOARD_ORDER, ARCHIVED):
        group = by_status.get(status)
        if not group:
            continue
        blocks.append(_heading(2, f"{label(status)} ({len(group)})"))
        blocks.extend(card_markdown(card, level=3) for card in group)

    if len(blocks) == 1:
        blocks.append("No cards.")
    return "\n\n".join(blocks)


def _attach_comments(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    for card in cards:
        card["comments"] = service.get_comments(conn, card["id"])
    return cards


def export_card(conn: sqlite3.Connection, card_id: int, fmt: str = MARKDOWN) -> str:
    """Export one card, comments included, as *fmt*.

    Raises:
        service.CardNotFound: If no card has *card_id*.
        ValueError: If *fmt* is not one of :data:`FORMATS`.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format: {fmt!r}")
    card = service.get_card(conn, card_id)
    if card is None:
        raise service.CardNotFound(card_id)
    _attach_comments(conn, [card])
    if fmt == JSON:
        return json.dumps(card, indent=2)
    return card_markdown(card)


def export_board(
    conn: sqlite3.Connection,
    *,
    fmt: str = MARKDOWN,
    project: str | None = None,
    statuses: Iterable[str] | None = None,
    include_archived: bool = False,
    search: str | None = None,
) -> str:
    """Export a board listing as *fmt* — a JSON array or one markdown document.

    Filter arguments mirror :func:`~mait_code.tools.board.service.list_cards`.

    Raises:
        ValueError: If *fmt* is not one of :data:`FORMATS`.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format: {fmt!r}")
    cards = _attach_comments(
        conn,
        service.list_cards(
            conn,
            project=project,
            statuses=statuses,
            include_archived=include_archived,
            search=search,
        ),
    )
    if fmt == JSON:
        return json.dumps(cards, indent=2)
    return board_markdown(cards, project=project)
