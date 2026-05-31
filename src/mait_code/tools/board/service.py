"""Presentation-agnostic board operations shared by the CLI and the TUI.

Pure functions over an open ``sqlite3.Connection`` — queries and mutations,
including the *done-invariant* (set ``completed_at`` on entering ``done``, clear
it on leaving). The caller owns the connection lifecycle: the argparse CLI opens
one per command via :func:`~mait_code.tools.board.db.connection`; the Textual
TUI holds a single connection for the app's lifetime.

Rows are returned as the same dicts the CLI has always produced (see
:func:`_card_dict`). Mutations raise :class:`CardNotFound` for a missing id
rather than printing and exiting — that ``print``/``sys.exit`` is a CLI concern
the caller layers on top (the CLI exits; the TUI flashes a notification).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    BOARD_ORDER,
    DONE,
    IN_PROGRESS,
    REFINED,
)

__all__ = [
    "CardNotFound",
    "add_card",
    "add_comment",
    "add_reference",
    "add_tag",
    "archive_card",
    "block_card",
    "complete_card",
    "edit_card",
    "get_card",
    "get_comments",
    "list_cards",
    "list_projects",
    "list_references",
    "list_tags",
    "move_card",
    "next_refined",
    "refine_card",
    "remove_card",
    "remove_reference",
    "remove_tag",
    "set_references",
    "set_tags",
    "summary_counts",
    "unblock_card",
]

_PRIORITY_ORDER = "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
_CARD_COLS = (
    "id, project, title, description, acceptance_criteria, status, priority, "
    "completion_summary, created_at, updated_at, completed_at"
)
_CARD_KEYS = (
    "id",
    "project",
    "title",
    "description",
    "acceptance_criteria",
    "status",
    "priority",
    "completion_summary",
    "created_at",
    "updated_at",
    "completed_at",
)


class CardNotFound(Exception):
    """Raised by mutations when no card has the given id."""

    def __init__(self, card_id: int) -> None:
        super().__init__(f"card #{card_id} not found")
        self.card_id = card_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so a query is matched literally.

    Pairs with ``LIKE ? ESCAPE '\\'`` — ``\\``, ``%`` and ``_`` are escaped so a
    search for e.g. ``100%`` doesn't turn ``%`` into a match-anything wildcard.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _card_dict(row: Sequence) -> dict:
    """Map a row selected with ``_CARD_COLS`` to a JSON-friendly dict."""
    return dict(zip(_CARD_KEYS, row))


def _fetch_card_row(conn: sqlite3.Connection, card_id: int):
    return conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE id = ?", (card_id,)
    ).fetchone()


def _require_row(conn: sqlite3.Connection, card_id: int):
    row = _fetch_card_row(conn, card_id)
    if row is None:
        raise CardNotFound(card_id)
    return row


def _attach_tags(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Populate each card dict's ``tags`` key (sorted, possibly empty).

    One grouped query rather than ``GROUP_CONCAT`` in the main SELECT — ordered
    ``GROUP_CONCAT`` needs SQLite ≥ 3.44, while a second ``card_id IN (…)`` query
    is version-agnostic and keeps :func:`_card_dict` a pure row-mapper.
    """
    if not cards:
        return cards
    ids = [c["id"] for c in cards]
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT card_id, tag FROM card_tags WHERE card_id IN ({placeholders}) "
        f"ORDER BY tag",
        ids,
    ).fetchall()
    by_card: dict[int, list[str]] = {}
    for card_id, tag in rows:
        by_card.setdefault(card_id, []).append(tag)
    for card in cards:
        card["tags"] = by_card.get(card["id"], [])
    return cards


def _attach_references(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Populate each card dict's ``references`` key, ordered by position.

    Each reference is a ``{"label": str, "value": str}`` dict. Same one-grouped-
    query shape as :func:`_attach_tags`, so a card list costs a single extra
    round-trip regardless of card count.
    """
    if not cards:
        return cards
    ids = [c["id"] for c in cards]
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT card_id, label, value FROM card_references "
        f"WHERE card_id IN ({placeholders}) ORDER BY position, id",
        ids,
    ).fetchall()
    by_card: dict[int, list[dict]] = {}
    for card_id, label, value in rows:
        by_card.setdefault(card_id, []).append({"label": label, "value": value})
    for card in cards:
        card["references"] = by_card.get(card["id"], [])
    return cards


def _attach(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Attach both tags and references to each card dict."""
    return _attach_references(conn, _attach_tags(conn, cards))


# --- Queries ---


def list_cards(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    statuses: Iterable[str] | None = None,
    include_archived: bool = False,
    tag: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Return cards ordered priority-then-oldest.

    Args:
        conn: Open board connection.
        project: Restrict to one project, or ``None`` for every project.
        statuses: Restrict to these statuses; ``None`` means "all". When given,
            it takes precedence over *include_archived*.
        include_archived: When no *statuses* filter is set, whether to include
            archived cards (default excludes them).
        tag: Restrict to cards carrying this tag, or ``None`` for no tag filter.
        search: Restrict to cards whose title contains this substring,
            case-insensitively, or ``None`` for no title filter.
    """
    where: list[str] = []
    params: list = []
    if project is not None:
        where.append("project = ?")
        params.append(project)
    if statuses is not None:
        statuses = list(statuses)
        placeholders = ", ".join("?" for _ in statuses)
        where.append(f"status IN ({placeholders})")
        params.extend(statuses)
    elif not include_archived:
        where.append("status != ?")
        params.append(ARCHIVED)
    if tag is not None:
        where.append("id IN (SELECT card_id FROM card_tags WHERE tag = ?)")
        params.append(tag)
    if search:
        where.append("title LIKE ? ESCAPE '\\' COLLATE NOCASE")
        params.append(f"%{_escape_like(search)}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards{clause} "
        f"ORDER BY {_PRIORITY_ORDER}, created_at, id",
        params,
    ).fetchall()
    return _attach(conn, [_card_dict(r) for r in rows])


def get_card(conn: sqlite3.Connection, card_id: int) -> dict | None:
    """Return one card as a dict, or ``None`` if no card has that id."""
    row = _fetch_card_row(conn, card_id)
    if row is None:
        return None
    return _attach(conn, [_card_dict(row)])[0]


def get_comments(conn: sqlite3.Connection, card_id: int) -> list[dict]:
    """Return a card's comments in insertion order."""
    rows = conn.execute(
        "SELECT author, body, created_at FROM card_comments "
        "WHERE card_id = ? ORDER BY id",
        (card_id,),
    ).fetchall()
    return [{"author": a, "body": b, "created_at": c} for a, b, c in rows]


def list_projects(conn: sqlite3.Connection) -> list[str]:
    """Return the distinct project names on the board, sorted."""
    rows = conn.execute(
        "SELECT DISTINCT project FROM cards ORDER BY project"
    ).fetchall()
    return [r[0] for r in rows]


def summary_counts(
    conn: sqlite3.Connection, *, project: str | None = None
) -> dict[str, int]:
    """Return per-column card counts (excluding archived).

    The result always has a key for every :data:`BOARD_ORDER` status, defaulting
    to ``0``. ``project=None`` counts across every project.
    """
    if project is None:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM cards WHERE status != ? GROUP BY status",
            (ARCHIVED,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM cards "
            "WHERE project = ? AND status != ? GROUP BY status",
            (project, ARCHIVED),
        ).fetchall()
    counts = {status: 0 for status in BOARD_ORDER}
    for status, count in rows:
        if status in counts:
            counts[status] = count
    return counts


def next_refined(
    conn: sqlite3.Connection, project: str, *, claim: bool = False
) -> dict | None:
    """Return the top refined card for *project* (priority, then oldest).

    With ``claim=True`` the card is moved to ``in_progress`` first (guarded on
    its status so a concurrent claim can't double-move it). Returns ``None``
    when the project has no refined cards.
    """
    row = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards "
        f"WHERE project = ? AND status = ? "
        f"ORDER BY {_PRIORITY_ORDER}, created_at, id LIMIT 1",
        (project, REFINED),
    ).fetchone()
    if row is None:
        return None
    if claim:
        conn.execute(
            "UPDATE cards SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (IN_PROGRESS, _now(), row[0], REFINED),
        )
        conn.commit()
        row = _fetch_card_row(conn, row[0])
    return _attach(conn, [_card_dict(row)])[0]


# --- Tags ---


def add_tag(conn: sqlite3.Connection, card_id: int, tag: str) -> None:
    """Add a tag to a card (idempotent).

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute(
        "INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)",
        (card_id, tag),
    )
    conn.commit()


def remove_tag(conn: sqlite3.Connection, card_id: int, tag: str) -> None:
    """Remove a tag from a card (no-op if the tag is absent).

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute("DELETE FROM card_tags WHERE card_id = ? AND tag = ?", (card_id, tag))
    conn.commit()


def list_tags(conn: sqlite3.Connection, card_id: int) -> list[str]:
    """Return a card's tags, sorted."""
    rows = conn.execute(
        "SELECT tag FROM card_tags WHERE card_id = ? ORDER BY tag", (card_id,)
    ).fetchall()
    return [r[0] for r in rows]


def set_tags(conn: sqlite3.Connection, card_id: int, tags: list[str]) -> None:
    """Replace a card's entire tag set with *tags* (set-replace, one txn).

    The whole set is rewritten — any tag absent from *tags* is dropped, so the
    caller owns the full membership (including service-managed tags like
    ``blocked``, which must be carried through if it should survive). Duplicates
    in *tags* collapse via the table's uniqueness. Raises :class:`CardNotFound`
    if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute("DELETE FROM card_tags WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO card_tags (card_id, tag) VALUES (?, ?)",
        [(card_id, tag) for tag in tags],
    )
    conn.commit()


# --- References ---


def add_reference(
    conn: sqlite3.Connection, card_id: int, label: str, value: str
) -> None:
    """Append a label→value reference to a card (kept in insertion order).

    Labels needn't be unique — a card may carry two ``PR`` links. Raises
    :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    next_position = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM card_references WHERE card_id = ?",
        (card_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO card_references (card_id, position, label, value) "
        "VALUES (?, ?, ?, ?)",
        (card_id, next_position, label, value),
    )
    conn.commit()


def remove_reference(conn: sqlite3.Connection, card_id: int, index: int) -> bool:
    """Remove the reference at 1-based *index* in display order.

    Returns ``True`` if a reference was removed, ``False`` if *index* is out of
    range (so the caller can report it). Indexing the displayed order — not the
    stored ``position`` — keeps removal stable even after earlier deletions leave
    gaps. Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    rows = conn.execute(
        "SELECT id FROM card_references WHERE card_id = ? ORDER BY position, id",
        (card_id,),
    ).fetchall()
    if index < 1 or index > len(rows):
        return False
    conn.execute("DELETE FROM card_references WHERE id = ?", (rows[index - 1][0],))
    conn.commit()
    return True


def list_references(conn: sqlite3.Connection, card_id: int) -> list[dict]:
    """Return a card's references as ``{"label", "value"}`` dicts, in order."""
    rows = conn.execute(
        "SELECT label, value FROM card_references WHERE card_id = ? "
        "ORDER BY position, id",
        (card_id,),
    ).fetchall()
    return [{"label": label, "value": value} for label, value in rows]


def set_references(
    conn: sqlite3.Connection, card_id: int, references: list[dict]
) -> None:
    """Replace a card's references with *references* (set-replace, one txn).

    Each entry is a ``{"label", "value"}`` dict; the list order becomes the new
    display order (positions renumbered from 1). The whole set is rewritten, so
    any reference absent from *references* is dropped. Raises
    :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute("DELETE FROM card_references WHERE card_id = ?", (card_id,))
    conn.executemany(
        "INSERT INTO card_references (card_id, position, label, value) "
        "VALUES (?, ?, ?, ?)",
        [
            (card_id, position, ref["label"], ref["value"])
            for position, ref in enumerate(references, 1)
        ],
    )
    conn.commit()


# --- Mutations ---


def add_card(
    conn: sqlite3.Connection,
    *,
    project: str,
    title: str,
    description: str | None = None,
    priority: str = "medium",
) -> int:
    """Insert a backlog card and return its new id."""
    now = _now()
    cursor = conn.execute(
        "INSERT INTO cards (project, title, description, status, priority, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project, title, description, BACKLOG, priority, now, now),
    )
    conn.commit()
    card_id = cursor.lastrowid
    assert card_id is not None  # a successful INSERT always sets lastrowid
    return card_id


def move_card(conn: sqlite3.Connection, card_id: int, new_status: str) -> None:
    """Move a card to *new_status*, maintaining the done-invariant.

    Entering ``done`` stamps ``completed_at``; leaving it clears the stamp.
    Raises :class:`CardNotFound` if the id is unknown.
    """
    row = _require_row(conn, card_id)
    old_status = row[5]
    now = _now()
    if new_status == DONE and old_status != DONE:
        conn.execute(
            "UPDATE cards SET status = ?, completed_at = ?, updated_at = ? "
            "WHERE id = ?",
            (new_status, now, now, card_id),
        )
    elif new_status != DONE and old_status == DONE:
        conn.execute(
            "UPDATE cards SET status = ?, completed_at = NULL, updated_at = ? "
            "WHERE id = ?",
            (new_status, now, card_id),
        )
    else:
        conn.execute(
            "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, card_id),
        )
    conn.commit()


def refine_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    description: str | None = None,
    acceptance: str | None = None,
) -> None:
    """Move a card to ``refined``, optionally setting description/acceptance.

    Raises :class:`CardNotFound` if the id is unknown.
    """
    fields: dict[str, str] = {"status": REFINED, "updated_at": _now()}
    if description is not None:
        fields["description"] = description
    if acceptance is not None:
        fields["acceptance_criteria"] = acceptance
    _require_row(conn, card_id)
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE cards SET {cols} WHERE id = ?", (*fields.values(), card_id))
    conn.commit()


def complete_card(
    conn: sqlite3.Connection, card_id: int, *, summary: str | None = None
) -> None:
    """Move a card to ``done`` with an optional completion summary.

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    now = _now()
    conn.execute(
        "UPDATE cards SET status = ?, completion_summary = ?, completed_at = ?, "
        "updated_at = ? WHERE id = ?",
        (DONE, summary or None, now, now, card_id),
    )
    conn.commit()


def block_card(
    conn: sqlite3.Connection, card_id: int, *, reason: str | None = None
) -> None:
    """Tag a card ``blocked`` in place; record *reason* as a comment if given.

    Blocking no longer moves the card — it keeps its real flow position and
    gains a :data:`BLOCKED_TAG` tag. Raises :class:`CardNotFound` if the id is
    unknown.
    """
    _require_row(conn, card_id)
    add_tag(conn, card_id, BLOCKED_TAG)
    if reason:
        conn.execute(
            "INSERT INTO card_comments (card_id, author, body, created_at) "
            "VALUES (?, ?, ?, ?)",
            (card_id, "me", f"Blocked: {reason}", _now()),
        )
        conn.commit()


def unblock_card(conn: sqlite3.Connection, card_id: int) -> None:
    """Remove the ``blocked`` tag from a card (keeps its flow position).

    Raises :class:`CardNotFound` if the id is unknown.
    """
    remove_tag(conn, card_id, BLOCKED_TAG)


def archive_card(conn: sqlite3.Connection, card_id: int) -> None:
    """Archive a card (hide it from default views).

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute(
        "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
        (ARCHIVED, _now(), card_id),
    )
    conn.commit()


def add_comment(
    conn: sqlite3.Connection, card_id: int, body: str, *, author: str = "me"
) -> None:
    """Append a comment to a card and bump its ``updated_at``.

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    now = _now()
    conn.execute(
        "INSERT INTO card_comments (card_id, author, body, created_at) "
        "VALUES (?, ?, ?, ?)",
        (card_id, author, body, now),
    )
    conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (now, card_id))
    conn.commit()


def edit_card(conn: sqlite3.Connection, card_id: int, **fields: str) -> None:
    """Update arbitrary card columns, bumping ``updated_at``.

    Pass column names as keyword arguments (e.g. ``title=..``,
    ``acceptance_criteria=..``). Raises :class:`CardNotFound` if the id is
    unknown; a no-op (no fields) is the caller's concern.
    """
    _require_row(conn, card_id)
    fields["updated_at"] = _now()
    cols = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE cards SET {cols} WHERE id = ?", (*fields.values(), card_id))
    conn.commit()


def remove_card(conn: sqlite3.Connection, card_id: int) -> None:
    """Delete a card permanently (comments cascade).

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
