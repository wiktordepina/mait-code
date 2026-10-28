"""Render cards as portable markdown or JSON exports.

The rendering layer shared by the CLI ``export`` subcommand and the board
TUI's export binding. Three scopes - a single card, an epic with its members,
or a whole board listing - in two formats:

- **markdown**: a readable document. Stored markdown in ``description``,
  ``acceptance_criteria`` and ``completion_summary`` is embedded verbatim,
  so what was authored round-trips unchanged.
- **json**: full fidelity, matching the ``show --json`` shape - every card
  carries its ``tags``, ``references`` and ``comments``. Live session
  bindings (``sessions``) are left out: they name running processes, which
  mean nothing once the document leaves this machine.

A board listing holds cards only: epics are left out, as on the board itself,
though a member card still names its epic under ``parent``. Export the epic
with :func:`export_epic` to keep it.

Like :mod:`~mait_code.tools.board.service`, functions here take an open
``sqlite3.Connection`` and raise :class:`~mait_code.tools.board.service.CardNotFound`
rather than printing - presentation concerns stay with the caller.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BOARD_ORDER,
    DONE,
    EPIC,
    IN_PROGRESS,
    label,
)

__all__ = [
    # Formats
    "FORMATS",
    "JSON",
    "MARKDOWN",
    # Renderers
    "board_markdown",
    "card_markdown",
    # Exporters
    "epic_markdown",
    "export_board",
    "export_card",
    "export_epic",
    # Formatting
    "progress_text",
    "related_text",
    "run_lines",
]

MARKDOWN = "markdown"
JSON = "json"

#: Supported export formats.
FORMATS: tuple[str, ...] = (MARKDOWN, JSON)


def _heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def _meta_lines(card: dict) -> list[str]:
    """The bullet list of card metadata under the title heading."""
    if card["kind"] == EPIC:
        lines = [f"- **Epic:** #{card['id']}"]
    else:
        lines = [
            f"- **Card:** #{card['id']}",
            f"- **Project:** {card['project']}",
        ]
    lines += [
        f"- **Status:** {label(card['status'])}",
        f"- **Priority:** {card['priority']}",
    ]
    if card["parent"]:
        lines.append(f"- **Epic:** #{card['parent']['id']} {card['parent']['title']}")
    if card["blocked_by"]:
        lines.append(f"- **Blocked by:** {related_text(card['blocked_by'])}")
    if card["blocks"]:
        lines.append(f"- **Blocks:** {related_text(card['blocks'])}")
    if card["tags"]:
        lines.append(f"- **Tags:** {', '.join(card['tags'])}")
    if card["created_by"]:
        lines.append(f"- **Created by:** {card['created_by']}")
    lines.append(f"- **Created:** {card['created_at']}")
    lines.append(f"- **Updated:** {card['updated_at']}")
    if card["completed_at"]:
        lines.append(f"- **Completed:** {card['completed_at']}")
    return lines


def related_text(cards: list[dict]) -> str:
    """``#76 title (Refined); #80 ...`` for a list of related-card summaries.

    Each card's status rides along, so a blocker list reads as which are
    still open and which are done or archived.
    """
    return "; ".join(f"#{c['id']} {c['title']} ({label(c['status'])})" for c in cards)


def _when(stamp: str | None) -> str:
    """A stored ISO timestamp as ``YYYY-MM-DD HH:MM``."""
    return stamp[:16].replace("T", " ") if stamp else ""


def run_lines(run: dict) -> list[str]:
    """A playbook run as plain text: a header line, then one line per step.

    ``Run: work``, a U+00B7 MIDDLE DOT, then ``started 2026-10-27 21:04``; then
    ``  2. skipped      Design review``, an em dash and the reason; the current
    step is marked ``current`` behind a U+2190 LEFTWARDS ARROW.
    """
    lines = [f"Run: {run['playbook']} · started {_when(run['started_at'])}"]
    for step in run["steps"]:
        line = (
            f"  {step['position']}. {step['status'].replace('_', ' '):<12} "
            f"{step['name']}"
        )
        if step["reason"]:
            line += f" — {step['reason']}"
        if step["position"] == run["current"]:
            line += "  ← current"
        lines.append(line)
    return lines


def progress_text(progress: dict) -> str:
    """``3/7 done``, ``1 waiting``, ``2 in progress`` (U+00B7-separated) for ``progress``."""
    parts = [f"{progress[DONE]}/{progress['total']} done"]
    if progress["waiting"]:
        parts.append(f"{progress['waiting']} waiting")
    if progress[IN_PROGRESS]:
        parts.append(f"{progress[IN_PROGRESS]} in progress")
    return " · ".join(parts)


def _comment_md(comment: dict) -> str:
    """One comment: an attribution line, then the body as a blockquote."""
    quoted = "\n".join(f"> {line}".rstrip() for line in comment["body"].splitlines())
    return f"**{comment['author']}** — {comment['created_at']}\n\n{quoted}"


def _run_step_md(step: dict, current: int | None) -> str:
    """One step as a numbered list item: name, status, and any reason."""
    line = (
        f"{step['position']}. **{step['name']}** — {step['status'].replace('_', ' ')}"
    )
    if step["reason"]:
        line += f": {step['reason']}"
    if step["position"] == current:
        line += " *(current)*"
    return line


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

    run = card.get("run")
    if run:
        steps = "\n".join(_run_step_md(step, run["current"]) for step in run["steps"])
        blocks.append(
            f"{_heading(sub, 'Run')}\n\n"
            f"`{run['playbook']}`, started {_when(run['started_at'])}\n\n{steps}"
        )

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


def epic_markdown(epic: dict) -> str:
    """Render an epic and its members as one markdown document.

    Args:
        epic: An epic dict as returned by
            :func:`~mait_code.tools.board.service.get_epic` - carrying
            ``members`` and ``progress`` - optionally with ``comments`` on it
            and its members.

    Returns:
        The markdown document, without a trailing newline.
    """
    progress = epic["progress"]
    blocks = [
        card_markdown(epic),
        _heading(2, f"Members — {progress[DONE]}/{progress['total']} done"),
    ]
    by_status: dict[str, list[dict]] = {}
    for card in epic["members"]:
        by_status.setdefault(card["status"], []).append(card)
    for status in BOARD_ORDER:
        group = by_status.get(status)
        if not group:
            continue
        blocks.append(_heading(3, f"{label(status)} ({len(group)})"))
        blocks.extend(card_markdown(card, level=4) for card in group)
    if not epic["members"]:
        blocks.append("No members.")
    return "\n\n".join(blocks)


def _attach_comments(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    for card in cards:
        card["comments"] = service.get_comments(conn, card["id"])
        card.pop("sessions", None)
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


def export_epic(conn: sqlite3.Connection, epic_id: int, fmt: str = MARKDOWN) -> str:
    """Export an epic with its non-archived members, comments included.

    The JSON form is the epic in the ``epic show --json`` shape, its
    ``members`` each carrying their own comments.

    Raises:
        service.CardNotFound: If no card has *epic_id*.
        service.RelationError: If the card isn't an epic.
        ValueError: If *fmt* is not one of :data:`FORMATS`.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format: {fmt!r}")
    epic = service.get_epic(conn, epic_id)
    _attach_comments(conn, [epic, *epic["members"]])
    if fmt == JSON:
        return json.dumps(epic, indent=2)
    return epic_markdown(epic)


def export_board(
    conn: sqlite3.Connection,
    *,
    fmt: str = MARKDOWN,
    project: str | None = None,
    statuses: Iterable[str] | None = None,
    include_archived: bool = False,
    search: str | None = None,
) -> str:
    """Export a board listing as *fmt* - a JSON array or one markdown document.

    Filter arguments mirror :func:`~mait_code.tools.board.service.list_cards`.
    Epics are left out, as on the board; see :func:`export_epic`.

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
