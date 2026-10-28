"""Presentation-agnostic board operations shared by the CLI and the TUI.

Pure functions over an open ``sqlite3.Connection`` - queries and mutations,
including the *done-invariant* (set ``completed_at`` on entering ``done``, clear
it on leaving). The caller owns the connection lifecycle: the argparse CLI opens
one per command via :func:`~mait_code.tools.board.db.connection`; the Textual
TUI holds a single connection for the app's lifetime.

Rows are returned as the same dicts the CLI has always produced (see
:func:`_card_dict`), each carrying its ``tags``, ``references``, active
Claude Code ``sessions``, relationships (``parent``, ``blocked_by``,
``blocks``, ``waiting_on``, ``archived_blockers``) and open playbook ``run``.

The *session-invariant*: a card entering ``in_review``, ``done`` or
``archived``, or promoted to an epic, releases every session binding,
whichever verb moves it; moves between the other open columns keep them.

Mutations raise :class:`CardNotFound` for a missing id rather than printing
and exiting - that ``print``/``sys.exit`` is a CLI concern the caller layers
on top (the CLI exits; the TUI flashes a notification).
"""

from __future__ import annotations

import enum
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    BLOCKS,
    BOARD_ORDER,
    CARD,
    DONE,
    EPIC,
    EPIC_PROJECT,
    IN_PROGRESS,
    IN_REVIEW,
    KINDS,
    LINK_TYPES,
    ORIGIN_LABEL,
    REFINED,
    STEP_IN_PROGRESS,
    STEP_PAUSED,
    STEP_PENDING,
    STEP_SKIPPED,
    STEP_STATUSES,
)
from mait_code.tools.board.sessions import SessionRef, pid_alive

__all__ = [
    "CardClosed",
    "CardNotFound",
    "EpicOrigin",
    "InheritedEpicClosed",
    "LinkCycle",
    "RelationError",
    "RunRefused",
    "add_card",
    "add_comment",
    "add_link",
    "add_reference",
    "add_tag",
    "archive_card",
    "bind_session",
    "block_card",
    "card_sessions",
    "complete_card",
    "dependency_graph",
    "edit_card",
    "end_run",
    "epic_members",
    "epic_without_open_members",
    "get_card",
    "get_comments",
    "get_epic",
    "get_run",
    "list_cards",
    "list_epics",
    "list_projects",
    "list_references",
    "list_tags",
    "move_card",
    "next_refined",
    "promote_epic",
    "prune_stale_bindings",
    "rebind_pid",
    "refine_card",
    "refresh_session_pid",
    "remove_card",
    "remove_link",
    "remove_reference",
    "remove_tag",
    "review_card",
    "set_parent",
    "set_references",
    "set_step",
    "set_tags",
    "start_run",
    "summary_counts",
    "unbind_session",
    "unblock_card",
]

_PRIORITY_ORDER = "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
_CARD_COLS = (
    "id, project, title, description, acceptance_criteria, status, priority, "
    "completion_summary, created_at, updated_at, completed_at, created_by, "
    "kind, parent_id"
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
    "created_by",
    "kind",
    "parent_id",
)
#: Indices into a ``_CARD_COLS`` row.
_STATUS = 5
_KIND = 12
_PARENT = 13
#: A blocker in one of these statuses no longer holds anything up: ``done`` is
#: finished, ``archived`` was dropped (and is flagged on the waiting card).
_SETTLED = (DONE, ARCHIVED)


class CardNotFound(Exception):
    """Raised by mutations when no card has the given id."""

    def __init__(self, card_id: int) -> None:
        super().__init__(f"card #{card_id} not found")
        self.card_id = card_id


class RunRefused(ValueError):
    """A playbook run change the board refuses; the message names the card.

    Raised for starting a run on an epic, a closed card or one with an open
    run (without ``replace``), a step list it can't address, an unknown step,
    a change with no open run, a second step in progress, or a reason given
    or missing where the step rules say otherwise.
    """


class CardClosed(Exception):
    """Raised when binding a session to a card that is ``done`` or ``archived``."""

    def __init__(self, card_id: int, status: str) -> None:
        super().__init__(f"card #{card_id} is {status}; only open cards bind")
        self.card_id = card_id
        self.status = status


class RelationError(ValueError):
    """Raised when a kind, parent or link change would break a board invariant.

    The invariants: a card is an epic exactly when its project is
    :data:`EPIC_PROJECT`; a parent is always an epic and an epic has no parent;
    epics take no ``blocks`` links and bind no sessions; ``blocks`` links form
    no loops. The message says which one, ready to show a user.
    """


class LinkCycle(RelationError):
    """Raised when a ``blocks`` link would close a loop.

    Attributes:
        path: The loop as card ids, starting and ending on the link's *from*
            card - e.g. ``[41, 47, 52, 41]`` for ``41 blocks 47`` when 47
            already reaches 41 through 52.
    """

    def __init__(self, path: list[int]) -> None:
        loop = " → ".join(f"#{card_id}" for card_id in path)
        super().__init__(f"#{path[0]} blocks #{path[1]} would close a loop: {loop}")
        self.path = path


class EpicOrigin(RelationError):
    """Raised when a new card names an epic as the card it came from.

    Attributes:
        card_id: The epic named as the origin.
    """

    def __init__(self, card_id: int) -> None:
        super().__init__(f"#{card_id} is an epic; use it as the parent instead")
        self.card_id = card_id


class InheritedEpicClosed(RelationError):
    """Raised when a new card would inherit an epic that is done or archived.

    Only :func:`add_card` with ``refuse_closed_epic=True`` raises it.

    Attributes:
        origin_id: The card the epic would have been inherited from.
        epic_id: The closed epic.
        status: The epic's status, ``done`` or ``archived``.
    """

    def __init__(self, origin_id: int, epic_id: int, status: str) -> None:
        super().__init__(f"#{origin_id}'s epic #{epic_id} is {status}")
        self.origin_id = origin_id
        self.epic_id = epic_id
        self.status = status


class _Unchanged(enum.Enum):
    """Typed sentinel for "leave this field alone" where ``None`` means clear."""

    KEEP = enum.auto()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so a query is matched literally.

    Pairs with ``LIKE ? ESCAPE '\\'`` - ``\\``, ``%`` and ``_`` are escaped so a
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

    One grouped query rather than ``GROUP_CONCAT`` in the main SELECT - ordered
    ``GROUP_CONCAT`` needs SQLite >= 3.44, while a second ``card_id IN (...)`` query
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


def _attach_sessions(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Populate each card dict's ``sessions`` key with its *active* bindings.

    Each binding is a ``{"session_id", "pid", "bound_at"}`` dict, oldest first.
    A binding whose Claude Code process has gone is left out here but kept in
    the table: a resume brings the session back under a new pid (see
    :func:`refresh_session_pid`). The card moving to review or closing releases
    it, and :func:`prune_stale_bindings` drops it once it is old enough.
    """
    if not cards:
        return cards
    ids = [c["id"] for c in cards]
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT card_id, session_id, pid, bound_at FROM card_sessions "
        f"WHERE card_id IN ({placeholders}) ORDER BY bound_at, session_id",
        ids,
    ).fetchall()
    alive: dict[int, bool] = {}
    by_card: dict[int, list[dict]] = {}
    for card_id, session_id, pid, bound_at in rows:
        if pid not in alive:
            alive[pid] = pid_alive(pid)
        if alive[pid]:
            by_card.setdefault(card_id, []).append(
                {"session_id": session_id, "pid": pid, "bound_at": bound_at}
            )
    for card in cards:
        card["sessions"] = by_card.get(card["id"], [])
    return cards


def _summary(card_id: int, title: str, status: str, project: str) -> dict:
    """The compact ``{id, title, status, project}`` shape a related card takes."""
    return {"id": card_id, "title": title, "status": status, "project": project}


def _attach_links(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Populate each card dict's relationship keys.

    * ``parent`` - ``{"id", "title"}`` of the card's epic, or ``None``.
    * ``blocked_by`` / ``blocks`` - the cards on either end of its ``blocks``
      links, as :func:`_summary` dicts ordered by id.
    * ``waiting_on`` - ids of the blockers not yet settled (neither ``done``
      nor ``archived``): the card can't start while this is non-empty.
    * ``archived_blockers`` - ids of blockers that were archived. They no
      longer hold the card up, but the work they stood for was dropped rather
      than finished, so the card probably wants another look.
    """
    if not cards:
        return cards
    ids = [c["id"] for c in cards]
    placeholders = ", ".join("?" for _ in ids)
    blocked_by: dict[int, list[dict]] = {}
    for to_id, *other in conn.execute(
        f"SELECT l.to_id, c.id, c.title, c.status, c.project FROM card_links l "
        f"JOIN cards c ON c.id = l.from_id "
        f"WHERE l.type = ? AND l.to_id IN ({placeholders}) ORDER BY c.id",
        (BLOCKS, *ids),
    ):
        blocked_by.setdefault(to_id, []).append(_summary(*other))
    blocks: dict[int, list[dict]] = {}
    for from_id, *other in conn.execute(
        f"SELECT l.from_id, c.id, c.title, c.status, c.project FROM card_links l "
        f"JOIN cards c ON c.id = l.to_id "
        f"WHERE l.type = ? AND l.from_id IN ({placeholders}) ORDER BY c.id",
        (BLOCKS, *ids),
    ):
        blocks.setdefault(from_id, []).append(_summary(*other))
    parent_ids = sorted({c["parent_id"] for c in cards if c["parent_id"] is not None})
    parents: dict[int, dict] = {}
    if parent_ids:
        marks = ", ".join("?" for _ in parent_ids)
        for parent_id, title in conn.execute(
            f"SELECT id, title FROM cards WHERE id IN ({marks})", parent_ids
        ):
            parents[parent_id] = {"id": parent_id, "title": title}
    for card in cards:
        card["parent"] = parents.get(card["parent_id"])
        card["blocked_by"] = blocked_by.get(card["id"], [])
        card["blocks"] = blocks.get(card["id"], [])
        card["waiting_on"] = [
            b["id"] for b in card["blocked_by"] if b["status"] not in _SETTLED
        ]
        card["archived_blockers"] = [
            b["id"] for b in card["blocked_by"] if b["status"] == ARCHIVED
        ]
    return cards


def _ready_clause() -> tuple[str, list]:
    """The SQL condition (and its params) for a *ready* card.

    Ready: a refined card (not an epic), not tagged ``blocked``, and not
    waiting on any ``blocks`` link whose blocker is unsettled.
    """
    settled = ", ".join("?" for _ in _SETTLED)
    return (
        "status = ? AND kind = ? "
        "AND id NOT IN (SELECT card_id FROM card_tags WHERE tag = ?) "
        "AND id NOT IN (SELECT l.to_id FROM card_links l "
        "JOIN cards b ON b.id = l.from_id "
        f"WHERE l.type = ? AND b.status NOT IN ({settled}))",
        [REFINED, CARD, BLOCKED_TAG, BLOCKS, *_SETTLED],
    )


def _attach(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Attach tags, references, sessions, relationships and the open run."""
    return _attach_runs(
        conn,
        _attach_links(
            conn,
            _attach_sessions(conn, _attach_references(conn, _attach_tags(conn, cards))),
        ),
    )


def _current_step(steps: list[dict]) -> int | None:
    """The step in progress, else the lowest-numbered paused one, else none."""
    for wanted in (STEP_IN_PROGRESS, STEP_PAUSED):
        for step in steps:
            if step["status"] == wanted:
                return step["position"]
    return None


def _attach_runs(conn: sqlite3.Connection, cards: list[dict]) -> list[dict]:
    """Populate each card dict's ``run`` key with its open run, or ``None``.

    A run is ``{"id", "playbook", "started_at", "updated_at", "ended_at",
    "current", "steps"}``, its steps ``{"position", "name", "status",
    "reason", "started_at", "finished_at"}`` in order. Two queries for the
    whole list (runs, then their steps), whatever its length.
    """
    if not cards:
        return cards
    ids = [c["id"] for c in cards]
    placeholders = ", ".join("?" for _ in ids)
    runs = conn.execute(
        f"SELECT id, card_id, playbook, started_at, updated_at, ended_at "
        f"FROM card_runs WHERE ended_at IS NULL AND card_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_card: dict[int, dict] = {}
    by_run: dict[int, dict] = {}
    for run_id, card_id, playbook, started_at, updated_at, ended_at in runs:
        run = {
            "id": run_id,
            "playbook": playbook,
            "started_at": started_at,
            "updated_at": updated_at,
            "ended_at": ended_at,
            "current": None,
            "steps": [],
        }
        by_card[card_id] = by_run[run_id] = run
    if by_run:
        run_ids = list(by_run)
        rows = conn.execute(
            f"SELECT run_id, position, name, status, reason, started_at, "
            f"finished_at FROM card_run_steps WHERE run_id IN "
            f"({', '.join('?' for _ in run_ids)}) ORDER BY run_id, position",
            run_ids,
        ).fetchall()
        for run_id, position, name, status, reason, started, finished in rows:
            by_run[run_id]["steps"].append(
                {
                    "position": position,
                    "name": name,
                    "status": status,
                    "reason": reason,
                    "started_at": started,
                    "finished_at": finished,
                }
            )
        for run in by_run.values():
            run["current"] = _current_step(run["steps"])
    for card in cards:
        card["run"] = by_card.get(card["id"])
    return cards


# --- Queries ---


def list_cards(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    statuses: Iterable[str] | None = None,
    include_archived: bool = False,
    tag: str | None = None,
    search: str | None = None,
    session: str | None = None,
    kind: str | None = CARD,
    parent_id: int | None = None,
    ready: bool = False,
    claimant: str | None = None,
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
        session: Restrict to cards with an *active* binding to this Claude
            Code session id, or ``None`` for no session filter.
        kind: Restrict to this ``kind``. Defaults to :data:`CARD`, so epics
            stay off every kanban-shaped listing unless asked for; ``None``
            returns both.
        parent_id: Restrict to the members of this epic, or ``None`` for no
            parent filter.
        ready: Restrict to cards :func:`next_refined` could hand out -
            refined, not tagged ``blocked``, not waiting on a blocker, and not
            held by a live session other than *claimant*.
        claimant: With *ready*, the session id asking; its own bindings don't
            hold a card back. ``None`` treats every live binding as another's.
    """
    where: list[str] = []
    params: list = []
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    if parent_id is not None:
        where.append("parent_id = ?")
        params.append(parent_id)
    if ready:
        clause, clause_params = _ready_clause()
        where.append(f"({clause})")
        params.extend(clause_params)
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
    if session is not None:
        where.append("id IN (SELECT card_id FROM card_sessions WHERE session_id = ?)")
        params.append(session)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards{clause} "
        f"ORDER BY {_PRIORITY_ORDER}, created_at, id",
        params,
    ).fetchall()
    cards = _attach(conn, [_card_dict(r) for r in rows])
    if session is not None:
        # The SQL filter can't see liveness; drop cards whose binding is dead.
        cards = [
            c for c in cards if any(b["session_id"] == session for b in c["sessions"])
        ]
    if ready:
        cards = [c for c in cards if not _held_elsewhere(c["sessions"], claimant)]
    return cards


def _held_elsewhere(sessions: list[dict], claimant: str | None) -> bool:
    """Whether any of a card's *active* bindings belongs to another session."""
    return any(b["session_id"] != claimant for b in sessions)


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
    """Return the distinct project names on the board, sorted.

    Epics' reserved :data:`EPIC_PROJECT` isn't a project and is left out.
    """
    rows = conn.execute(
        "SELECT DISTINCT project FROM cards WHERE kind = ? ORDER BY project",
        (CARD,),
    ).fetchall()
    return [r[0] for r in rows]


def summary_counts(
    conn: sqlite3.Connection, *, project: str | None = None
) -> dict[str, int]:
    """Return per-column card counts (excluding archived and epics).

    The result always has a key for every :data:`BOARD_ORDER` status, defaulting
    to ``0``. ``project=None`` counts across every project.
    """
    if project is None:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM cards "
            "WHERE kind = ? AND status != ? GROUP BY status",
            (CARD, ARCHIVED),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM cards "
            "WHERE kind = ? AND project = ? AND status != ? GROUP BY status",
            (CARD, project, ARCHIVED),
        ).fetchall()
    counts = {status: 0 for status in BOARD_ORDER}
    for status, count in rows:
        if status in counts:
            counts[status] = count
    return counts


def next_refined(
    conn: sqlite3.Connection,
    project: str | None,
    *,
    claim: bool = False,
    session: SessionRef | None = None,
    epic_id: int | None = None,
) -> dict | None:
    """Return the top *ready* card for *project* (priority, then oldest).

    Ready means refined, not tagged ``blocked``, not waiting on any
    unsettled ``blocks`` link (see :func:`_attach_links`), and not held by a
    live session other than *session* - another session may be refining it
    under a playbook. Given *epic_id*, the
    search spans that epic's members in every project and *project* is
    ignored.

    With ``claim=True`` the card is moved to ``in_progress`` first (guarded on
    its status so a concurrent claim can't double-move it) and, given a
    *session*, bound to it. The guard re-checks the status only, not
    readiness. Returns ``None`` when nothing is ready.

    Raises :class:`CardNotFound` / :class:`RelationError` for an *epic_id*
    that is unknown or not an epic, and :class:`ValueError` when neither
    *project* nor *epic_id* is given.
    """
    if epic_id is not None:
        _require_epic(conn, epic_id)
        scope, scope_param = "parent_id = ?", epic_id
    elif project is None:
        raise ValueError("next_refined needs a project or an epic_id")
    else:
        scope, scope_param = "project = ?", project
    ready, ready_params = _ready_clause()
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM cards WHERE {scope} AND {ready} "
        f"ORDER BY {_PRIORITY_ORDER}, created_at, id",
        (scope_param, *ready_params),
    ).fetchall()
    # Liveness can't be checked in SQL, so held cards are skipped here.
    claimant = session.session_id if session is not None else None
    row = next(
        (r for r in rows if not _held_elsewhere(card_sessions(conn, r[0]), claimant)),
        None,
    )
    if row is None:
        return None
    if claim:
        claimed = conn.execute(
            "UPDATE cards SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (IN_PROGRESS, _now(), row[0], REFINED),
        ).rowcount
        if claimed and session is not None:
            _upsert_binding(conn, row[0], session)
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

    The whole set is rewritten - any tag absent from *tags* is dropped, so the
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
    """Append a label->value reference to a card (kept in insertion order).

    Labels needn't be unique - a card may carry two ``PR`` links. Raises
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
    range (so the caller can report it). Indexing the displayed order - not the
    stored ``position`` - keeps removal stable even after earlier deletions leave
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


# --- Sessions ---


def _upsert_binding(
    conn: sqlite3.Connection, card_id: int, session: SessionRef
) -> None:
    """Bind *session* to *card_id*, refreshing pid and time if already bound."""
    conn.execute(
        "INSERT INTO card_sessions (card_id, session_id, pid, bound_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(card_id, session_id) "
        "DO UPDATE SET pid = excluded.pid, bound_at = excluded.bound_at",
        (card_id, session.session_id, session.pid, _now()),
    )


def _release_sessions(conn: sqlite3.Connection, card_id: int) -> None:
    """Drop every binding on *card_id* (uncommitted; the caller commits)."""
    conn.execute("DELETE FROM card_sessions WHERE card_id = ?", (card_id,))


def _on_close(conn: sqlite3.Connection, card_id: int) -> None:
    """What every path that closes a card does (uncommitted; the caller commits).

    Closing is entering ``done`` or ``archived`` by any verb, or promotion to an
    epic. Each such path calls this, so a new consequence of closing goes here
    once rather than into every verb: the card's sessions are released and its
    open playbook run is ended.
    """
    _release_sessions(conn, card_id)
    now = _now()
    conn.execute(
        "UPDATE card_runs SET ended_at = ?, updated_at = ? "
        "WHERE card_id = ? AND ended_at IS NULL",
        (now, now, card_id),
    )


def bind_session(conn: sqlite3.Connection, card_id: int, session: SessionRef) -> None:
    """Bind a Claude Code *session* to an open card, in any column.

    A binding means the session is working on the card, whichever column it
    sits in. Idempotent: re-binding the same session refreshes its pid and
    time. A card may carry several bindings (parallel sessions on one card).
    Raises :class:`CardNotFound` if the id is unknown, :class:`RelationError`
    for an epic (epics are never worked directly; checked first) and
    :class:`CardClosed` for a ``done`` or ``archived`` card.
    """
    row = _require_row(conn, card_id)
    if row[_KIND] == EPIC:
        raise RelationError(f"#{card_id} is an epic; work its member cards instead")
    if row[_STATUS] in _SETTLED:
        raise CardClosed(card_id, row[_STATUS])
    _upsert_binding(conn, card_id, session)
    conn.commit()


def unbind_session(conn: sqlite3.Connection, card_id: int, session_id: str) -> bool:
    """Remove *session_id*'s binding from a card.

    Returns ``True`` if a binding was removed, ``False`` if there was none.
    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    removed = conn.execute(
        "DELETE FROM card_sessions WHERE card_id = ? AND session_id = ?",
        (card_id, session_id),
    ).rowcount
    conn.commit()
    return removed > 0


def card_sessions(conn: sqlite3.Connection, card_id: int) -> list[dict]:
    """Return a card's active session bindings (empty for an unknown id)."""
    return _attach_sessions(conn, [{"id": card_id}])[0]["sessions"]


def refresh_session_pid(conn: sqlite3.Connection, session_id: str, pid: int) -> int:
    """Point every binding of *session_id* at *pid*; return how many changed.

    For a resumed session: same id, new Claude Code process. Each binding's
    ``bound_at`` is renewed too, so :func:`prune_stale_bindings` counts from
    the resume rather than from the original bind.
    """
    changed = conn.execute(
        "UPDATE card_sessions SET pid = ?, bound_at = ? "
        "WHERE session_id = ? AND pid != ?",
        (pid, _now(), session_id, pid),
    ).rowcount
    conn.commit()
    return changed


def rebind_pid(conn: sqlite3.Connection, pid: int, session_id: str) -> int:
    """Move every binding held by process *pid* to *session_id*; return the count.

    For a ``/clear``: the process carries on under a new session id, and its
    cards should follow. A card already bound to *session_id* keeps that one
    binding (the old one is dropped rather than duplicated). A moved binding's
    ``bound_at`` is renewed, as on a resume.
    """
    moved = conn.execute(
        "UPDATE OR IGNORE card_sessions SET session_id = ?, bound_at = ? "
        "WHERE pid = ? AND session_id != ?",
        (session_id, _now(), pid, session_id),
    ).rowcount
    conn.execute(
        "DELETE FROM card_sessions WHERE pid = ? AND session_id != ?",
        (pid, session_id),
    )
    conn.commit()
    return moved


def prune_stale_bindings(conn: sqlite3.Connection, *, older_than: timedelta) -> int:
    """Delete dead bindings last bound or resumed more than *older_than* ago.

    A dead binding is kept so a resume can bring it back (see
    :func:`refresh_session_pid`), but on a card that stays open for weeks it
    would otherwise linger, and a recycled pid could make it read as live
    again. Age is counted from ``bound_at``, which a bind, a resume and a
    ``/clear`` all renew; nothing records when a process dies, so a session
    that ran for longer than *older_than* without either is pruned as soon as
    it ends. Live bindings are never touched, whatever their age. Returns how
    many were deleted.
    """
    cutoff = (datetime.now(timezone.utc) - older_than).isoformat()
    rows = conn.execute(
        "SELECT card_id, session_id, pid FROM card_sessions WHERE bound_at < ?",
        (cutoff,),
    ).fetchall()
    stale = [
        (card_id, session_id) for card_id, session_id, pid in rows if not pid_alive(pid)
    ]
    conn.executemany(
        "DELETE FROM card_sessions WHERE card_id = ? AND session_id = ?", stale
    )
    conn.commit()
    return len(stale)


# --- Playbook runs ---


def get_run(conn: sqlite3.Connection, card_id: int) -> dict | None:
    """Return a card's open playbook run (see :func:`_attach_runs`), or ``None``.

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    return _attach_runs(conn, [{"id": card_id}])[0]["run"]


def _check_steps(card_id: int, steps: list[str]) -> list[str]:
    """Refuse a step list that positions or names couldn't address."""
    names = [name.strip() for name in steps]
    if not names:
        raise RunRefused(f"card #{card_id}: a run needs at least one step")
    seen: set[str] = set()
    for position, name in enumerate(names, 1):
        if not name:
            raise RunRefused(f"card #{card_id}: step {position} has no name")
        if name.isdecimal():
            # A digit name would read as a position in ``run step``.
            raise RunRefused(
                f"card #{card_id}: step name {name!r} is all digits; "
                f"it would be read as a position"
            )
        if name in seen:
            raise RunRefused(f"card #{card_id}: step name {name!r} appears twice")
        seen.add(name)
    return names


def _open_run_id(conn: sqlite3.Connection, card_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM card_runs WHERE card_id = ? AND ended_at IS NULL",
        (card_id,),
    ).fetchone()
    return row[0] if row else None


def _touch_run(conn: sqlite3.Connection, card_id: int, run_id: int, now: str) -> None:
    """Bump the run's and the card's ``updated_at`` (uncommitted)."""
    conn.execute("UPDATE card_runs SET updated_at = ? WHERE id = ?", (now, run_id))
    conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (now, card_id))


def start_run(
    conn: sqlite3.Connection,
    card_id: int,
    playbook: str,
    steps: list[str],
    *,
    replace: bool = False,
) -> None:
    """Start a playbook run on a card: its ordered *steps*, all ``pending``.

    Step names come from the playbook, not the schema. With *replace*, an open
    run is ended first; without it, an open run is refused, so a second
    playbook (or a resumed session that didn't look) can't drop one that is
    half done. Ended runs are kept as history.

    Raises :class:`CardNotFound` for an unknown id, and :class:`RunRefused` for
    an epic, a ``done`` or ``archived`` card, an open run without *replace*,
    an empty *playbook*, or a step list that is empty or has an empty,
    all-digit or repeated name.
    """
    playbook = playbook.strip()
    with _write_lock(conn):
        row = _require_row(conn, card_id)
        if row[_KIND] == EPIC:
            raise RunRefused(f"card #{card_id} is an epic; run its member cards")
        if row[_STATUS] in _SETTLED:
            raise RunRefused(f"card #{card_id} is {row[_STATUS]}; only open cards run")
        if not playbook:
            raise RunRefused(f"card #{card_id}: a run needs a playbook name")
        names = _check_steps(card_id, steps)
        now = _now()
        open_run = _open_run_id(conn, card_id)
        if open_run is not None:
            if not replace:
                raise RunRefused(
                    f"card #{card_id} already has an open run; "
                    f"end it or start again with replace"
                )
            conn.execute(
                "UPDATE card_runs SET ended_at = ?, updated_at = ? WHERE id = ?",
                (now, now, open_run),
            )
        run_id = conn.execute(
            "INSERT INTO card_runs (card_id, playbook, started_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (card_id, playbook, now, now),
        ).lastrowid
        conn.executemany(
            "INSERT INTO card_run_steps (run_id, position, name) VALUES (?, ?, ?)",
            [(run_id, position, name) for position, name in enumerate(names, 1)],
        )
        conn.execute("UPDATE cards SET updated_at = ? WHERE id = ?", (now, card_id))


def _resolve_step(
    conn: sqlite3.Connection, card_id: int, run_id: int, step: str
) -> tuple:
    """The step row named by a 1-based position or an exact, case-sensitive name."""
    step = step.strip()
    cols = "position, name, status, reason, started_at, finished_at"
    if step.isdecimal():
        row = conn.execute(
            f"SELECT {cols} FROM card_run_steps WHERE run_id = ? AND position = ?",
            (run_id, int(step)),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT {cols} FROM card_run_steps WHERE run_id = ? AND name = ?",
            (run_id, step),
        ).fetchone()
    if row is None:
        raise RunRefused(f"card #{card_id}: the open run has no step {step!r}")
    return row


def set_step(
    conn: sqlite3.Connection,
    card_id: int,
    step: str,
    status: str,
    *,
    reason: str | None = None,
) -> tuple[int, str]:
    """Set one step of a card's open run to *status*; return its position and name.

    *step* is a 1-based position or the exact step name. Any status may follow
    any other, so a done step can be redone. The step's fields follow:

    - ``pending`` resets it: timestamps and reason cleared.
    - ``in_progress`` from ``paused`` resumes it, keeping ``started_at``; from
      anything else it is a new attempt with a fresh ``started_at``. Only one
      step may be in progress; setting the one already in progress again
      changes nothing.
    - ``paused`` sets ``started_at`` if it is empty; a *reason* is optional.
    - ``done`` and ``skipped`` set ``finished_at``; ``skipped`` needs a
      *reason*, and adds a card comment saying so in the same transaction.
    - Leaving ``done`` or ``skipped`` clears ``finished_at``; leaving
      ``skipped`` or ``paused`` clears the reason.

    Every change bumps the run's and the card's ``updated_at``. A run never
    ends on its own when its steps finish; see :func:`end_run`.

    Raises :class:`CardNotFound` for an unknown id, :class:`ValueError` for a
    status outside :data:`STEP_STATUSES`, and :class:`RunRefused` for a card
    with no open run, an unknown step, a second step in progress, a skip with
    no reason, or a reason on a status that takes none.
    """
    if status not in STEP_STATUSES:
        raise ValueError(f"unknown step status {status!r}")
    reason = reason.strip() if reason else None
    with _write_lock(conn):
        _require_row(conn, card_id)
        if status == STEP_SKIPPED and not reason:
            raise RunRefused(f"card #{card_id}: skipping a step needs a reason")
        if reason and status not in (STEP_SKIPPED, STEP_PAUSED):
            raise RunRefused(
                f"card #{card_id}: a reason goes with skipped or paused, not {status}"
            )
        run_id = _open_run_id(conn, card_id)
        if run_id is None:
            raise RunRefused(f"card #{card_id} has no open run")
        position, name, old, _reason, started, finished = _resolve_step(
            conn, card_id, run_id, step
        )
        which = f"step {position} ({name})"
        if status == STEP_IN_PROGRESS:
            if old == STEP_IN_PROGRESS:
                return position, name
            busy = conn.execute(
                "SELECT position, name FROM card_run_steps "
                "WHERE run_id = ? AND status = ?",
                (run_id, STEP_IN_PROGRESS),
            ).fetchone()
            if busy is not None:
                raise RunRefused(
                    f"card #{card_id}: step {busy[0]} ({busy[1]}) is already in "
                    f"progress; finish, pause or reset it before starting {which}"
                )
        now = _now()
        if status == STEP_PENDING:
            started = finished = None
        elif status == STEP_IN_PROGRESS:
            started = started if (old == STEP_PAUSED and started) else now
            finished = None
        elif status == STEP_PAUSED:
            started = started or now
            finished = None
        else:  # done or skipped
            finished = now
        conn.execute(
            "UPDATE card_run_steps SET status = ?, reason = ?, started_at = ?, "
            "finished_at = ? WHERE run_id = ? AND position = ?",
            (status, reason, started, finished, run_id, position),
        )
        if status == STEP_SKIPPED:
            # Inline, not add_comment: that commits on its own, mid-transaction.
            conn.execute(
                "INSERT INTO card_comments (card_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (card_id, "claude", f"Skipped {which}: {reason}", now),
            )
        _touch_run(conn, card_id, run_id, now)
    return position, name


def end_run(conn: sqlite3.Connection, card_id: int) -> None:
    """End a card's open run, keeping it as history.

    The playbook calls this once it has reported on the run; closing the card
    ends it too (see :func:`_on_close`). Raises :class:`CardNotFound` for an
    unknown id and :class:`RunRefused` if the card has no open run.
    """
    with _write_lock(conn):
        _require_row(conn, card_id)
        run_id = _open_run_id(conn, card_id)
        if run_id is None:
            raise RunRefused(f"card #{card_id} has no open run")
        now = _now()
        conn.execute("UPDATE card_runs SET ended_at = ? WHERE id = ?", (now, run_id))
        _touch_run(conn, card_id, run_id, now)


# --- Mutations ---


def add_card(
    conn: sqlite3.Connection,
    *,
    project: str | None,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    created_by: str | None = None,
    kind: str = CARD,
    parent_id: int | None | _Unchanged = _Unchanged.KEEP,
    origin_id: int | None = None,
    refuse_closed_epic: bool = False,
) -> int:
    """Insert a backlog card and return its new id.

    *created_by* names the client that raised the card when it arrives from
    somewhere other than a local session (see :mod:`mait_code.remote`);
    ``None`` means it was created locally.

    An epic (``kind=EPIC``) always gets :data:`EPIC_PROJECT` - pass that or
    ``None`` as *project* - and no parent. A card needs a real *project* and
    may name its epic as *parent_id*.

    *origin_id* names the card this one was split from or raised as a
    follow-up of, in any project. The new card joins the origin's epic unless
    *parent_id* is given (``None`` for no epic), and gets an
    :data:`ORIGIN_LABEL` reference to ``#<origin_id>`` in the same
    transaction, which holds the write lock from the checks on, so a
    parallel writer can't change the origin or epic in between. Epics
    neither have an origin nor serve as one (:class:`EpicOrigin`).

    *refuse_closed_epic* refuses to inherit an epic that is done or archived
    (:class:`InheritedEpicClosed`), for a caller that can't warn about one
    afterwards. An explicit *parent_id* is never refused for its status.

    Raises :class:`RelationError` when the combination breaks those rules,
    and :class:`CardNotFound` for an unknown *parent_id* or *origin_id*.
    """
    if kind not in KINDS:
        raise RelationError(f"unknown kind {kind!r}")
    with _write_lock(conn):
        if kind == EPIC:
            if project not in (None, EPIC_PROJECT):
                raise RelationError(f"an epic has no project (got {project!r})")
            if parent_id not in (None, _Unchanged.KEEP):
                raise RelationError("an epic can't have a parent")
            if origin_id is not None:
                raise RelationError("an epic can't come from a card")
            project, parent_id = EPIC_PROJECT, None
        else:
            _check_card_project(project)
            if origin_id is not None:
                origin = _require_row(conn, origin_id)
                if origin[_KIND] == EPIC:
                    raise EpicOrigin(origin_id)
                if parent_id is _Unchanged.KEEP:
                    inherited = origin[_PARENT]
                    if refuse_closed_epic and inherited is not None:
                        epic = _require_row(conn, inherited)
                        if epic[_STATUS] in _SETTLED:
                            raise InheritedEpicClosed(
                                origin_id, inherited, epic[_STATUS]
                            )
                    parent_id = inherited
            if parent_id is _Unchanged.KEEP:
                parent_id = None
            if parent_id is not None:
                _require_epic(conn, parent_id)
        now = _now()
        cursor = conn.execute(
            "INSERT INTO cards (project, title, description, status, priority, "
            "created_at, updated_at, created_by, kind, parent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project,
                title,
                description,
                BACKLOG,
                priority,
                now,
                now,
                created_by,
                kind,
                parent_id,
            ),
        )
        card_id = cursor.lastrowid
        assert card_id is not None  # a successful INSERT always sets lastrowid
        if origin_id is not None:
            conn.execute(
                "INSERT INTO card_references (card_id, position, label, value) "
                "VALUES (?, 1, ?, ?)",
                (card_id, ORIGIN_LABEL, f"#{origin_id}"),
            )
    return card_id


def move_card(
    conn: sqlite3.Connection,
    card_id: int,
    new_status: str,
    *,
    session: SessionRef | None = None,
) -> None:
    """Move a card to *new_status*, maintaining the done- and session-invariants.

    Entering ``done`` stamps ``completed_at``; leaving it clears the stamp.
    Entering ``in_review`` releases the card's session bindings (the card is
    handed off), and entering ``done`` or ``archived`` closes it (see
    :func:`_on_close`); moves between the other columns keep them. Moving to
    ``in_progress`` with a *session* binds it - unless it's an epic, which
    never binds (its status is bookkeeping, not work). Raises
    :class:`CardNotFound` if the id is unknown.
    """
    row = _require_row(conn, card_id)
    old_status = row[_STATUS]
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
    if new_status in _SETTLED:
        _on_close(conn, card_id)
    elif new_status == IN_REVIEW:
        _release_sessions(conn, card_id)
    elif new_status == IN_PROGRESS and session is not None and row[_KIND] != EPIC:
        _upsert_binding(conn, card_id, session)
    conn.commit()


def refine_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    description: str | None = None,
    acceptance: str | None = None,
) -> None:
    """Move a card to ``refined``, optionally setting description/acceptance.

    Keeps the card's session bindings: a session may refine the card it is
    working on. Raises :class:`CardNotFound` if the id is unknown.
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

    Closes the card (see :func:`_on_close`). Raises :class:`CardNotFound` if
    the id is unknown.
    """
    _require_row(conn, card_id)
    now = _now()
    conn.execute(
        "UPDATE cards SET status = ?, completion_summary = ?, completed_at = ?, "
        "updated_at = ? WHERE id = ?",
        (DONE, summary or None, now, now, card_id),
    )
    _on_close(conn, card_id)
    conn.commit()


def review_card(
    conn: sqlite3.Connection, card_id: int, *, pr: str | None = None
) -> None:
    """Move a card to ``in_review``, recording *pr* as a ``PR`` reference.

    The card is parked between ``in_progress`` and ``done`` until its pull
    request merges, and its session bindings are released. Re-reviewing with
    a PR the card already carries (e.g. after a re-push) doesn't duplicate the
    reference. Raises :class:`CardNotFound` if the id is unknown.
    """
    move_card(conn, card_id, IN_REVIEW)
    if pr and {"label": "PR", "value": pr} not in list_references(conn, card_id):
        add_reference(conn, card_id, "PR", pr)


def block_card(
    conn: sqlite3.Connection, card_id: int, *, reason: str | None = None
) -> None:
    """Tag a card ``blocked`` in place; record *reason* as a comment if given.

    Blocking no longer moves the card - it keeps its real flow position and
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

    Closes the card (see :func:`_on_close`). Raises :class:`CardNotFound` if
    the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute(
        "UPDATE cards SET status = ?, updated_at = ? WHERE id = ?",
        (ARCHIVED, _now(), card_id),
    )
    _on_close(conn, card_id)
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


def edit_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    parent_id: int | None | _Unchanged = _Unchanged.KEEP,
    **fields: str,
) -> None:
    """Update arbitrary card columns, bumping ``updated_at``.

    Pass column names as keyword arguments (e.g. ``title=..``,
    ``acceptance_criteria=..``). *parent_id* moves the card into that epic,
    or out of any with ``None``; leave it out to keep the current one. Every
    change is checked first and written in one transaction, so a refused
    field leaves the card exactly as it was - the parent included.

    ``kind`` isn't editable here - use :func:`promote_epic`. Raises
    :class:`CardNotFound` if the id (or *parent_id*) is unknown and
    :class:`RelationError` for ``kind``, a *parent_id* that breaks the rules
    of :func:`set_parent`, or a ``project`` that would move a card to
    :data:`EPIC_PROJECT` or an epic off it; a no-op (no fields) is the
    caller's concern.
    """
    with _write_lock(conn):
        row = _require_row(conn, card_id)
        if "kind" in fields:
            raise RelationError("kind can't be edited directly")
        if "project" in fields:
            if row[_KIND] == EPIC:
                if fields["project"] != EPIC_PROJECT:
                    raise RelationError(f"#{card_id} is an epic and has no project")
            else:
                _check_card_project(fields["project"])
        values: dict[str, object] = dict(fields)
        if parent_id is not _Unchanged.KEEP:
            _check_parent(conn, row, parent_id)
            values["parent_id"] = parent_id
        values["updated_at"] = _now()
        cols = ", ".join(f"{key} = ?" for key in values)
        conn.execute(
            f"UPDATE cards SET {cols} WHERE id = ?", (*values.values(), card_id)
        )


def remove_card(conn: sqlite3.Connection, card_id: int) -> None:
    """Delete a card permanently (comments cascade).

    Raises :class:`CardNotFound` if the id is unknown.
    """
    _require_row(conn, card_id)
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()


# --- Relationships ---


@contextmanager
def _write_lock(conn: sqlite3.Connection) -> Iterator[None]:
    """Run the block as one ``BEGIN IMMEDIATE`` transaction: commit or roll back.

    For a mutation whose checks must hold until its write lands - a parallel
    writer (another session, the TUI) could otherwise change what was checked
    in between. Taking the write lock up front, rather than on the first
    write, closes that window.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _check_card_project(project: str | None) -> None:
    """Refuse a missing project, or the epics' reserved one, for a card."""
    if not project:
        raise RelationError("a card needs a project")
    if project == EPIC_PROJECT:
        raise RelationError(f"{EPIC_PROJECT!r} is reserved for epics")


def _require_epic(conn: sqlite3.Connection, epic_id: int):
    """Return the row for *epic_id*, refusing a card that isn't an epic."""
    row = _require_row(conn, epic_id)
    if row[_KIND] != EPIC:
        raise RelationError(f"#{epic_id} isn't an epic")
    return row


def _blocks_path(conn: sqlite3.Connection, start: int, goal: int) -> list[int] | None:
    """Return a ``blocks`` path from *start* to *goal* as card ids, or ``None``.

    A breadth-first walk over every ``blocks`` edge loaded at once: the board
    holds a few hundred edges at most, and walking in Python yields the path
    itself for the error message, which a recursive CTE makes awkward.
    """
    successors: dict[int, list[int]] = {}
    for from_id, to_id in conn.execute(
        "SELECT from_id, to_id FROM card_links WHERE type = ?", (BLOCKS,)
    ):
        successors.setdefault(from_id, []).append(to_id)
    came_from: dict[int, int | None] = {start: None}
    frontier = [start]
    while frontier:
        following: list[int] = []
        for node in frontier:
            for nxt in successors.get(node, []):
                if nxt in came_from:
                    continue
                came_from[nxt] = node
                if nxt == goal:
                    path = [goal]
                    step = came_from[goal]
                    while step is not None:
                        path.append(step)
                        step = came_from[step]
                    return path[::-1]
                following.append(nxt)
        frontier = following
    return None


def set_parent(conn: sqlite3.Connection, card_id: int, epic_id: int | None) -> None:
    """Make *card_id* a member of epic *epic_id*, or of none with ``None``.

    Raises :class:`CardNotFound` for an unknown id and :class:`RelationError`
    when *card_id* is an epic (one level only) or *epic_id* isn't one.
    """
    with _write_lock(conn):
        row = _require_row(conn, card_id)
        _check_parent(conn, row, epic_id)
        conn.execute(
            "UPDATE cards SET parent_id = ?, updated_at = ? WHERE id = ?",
            (epic_id, _now(), card_id),
        )


def _check_parent(conn: sqlite3.Connection, row: Sequence, epic_id: int | None) -> None:
    """Refuse making the card in *row* a member of *epic_id*.

    An epic can't have a parent (one level only), and a parent must be an
    epic. ``None`` - leaving any epic - is always fine for a card.
    """
    if row[_KIND] == EPIC:
        raise RelationError(f"#{row[0]} is an epic; epics can't have a parent")
    if epic_id is not None:
        _require_epic(conn, epic_id)


def add_link(
    conn: sqlite3.Connection, from_id: int, to_id: int, link_type: str = BLOCKS
) -> None:
    """Record that *from_id* :data:`BLOCKS` *to_id*.

    The checks and the insert share one write-locked transaction, so a
    parallel writer can't slip in the edge that closes a loop between them.

    Raises:
        CardNotFound: If either id is unknown.
        LinkCycle: If *to_id* already reaches *from_id* along ``blocks``
            links, so the new link would close a loop.
        RelationError: For an unknown *link_type*, a self-link, a link that
            already exists, or an epic on either end.
    """
    if link_type not in LINK_TYPES:
        raise RelationError(f"unknown link type {link_type!r}")
    if from_id == to_id:
        raise RelationError(f"#{from_id} can't block itself")
    with _write_lock(conn):
        for card_id in (from_id, to_id):
            if _require_row(conn, card_id)[_KIND] == EPIC:
                raise RelationError(
                    f"#{card_id} is an epic; link its member cards instead"
                )
        if conn.execute(
            "SELECT 1 FROM card_links WHERE from_id = ? AND type = ? AND to_id = ?",
            (from_id, link_type, to_id),
        ).fetchone():
            raise RelationError(f"#{from_id} already blocks #{to_id}")
        path = _blocks_path(conn, to_id, from_id)
        if path is not None:
            raise LinkCycle([from_id, *path])
        conn.execute(
            "INSERT INTO card_links (from_id, type, to_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (from_id, link_type, to_id, _now()),
        )


def remove_link(
    conn: sqlite3.Connection, from_id: int, to_id: int, link_type: str = BLOCKS
) -> bool:
    """Remove a link; return ``True`` if there was one to remove."""
    removed = conn.execute(
        "DELETE FROM card_links WHERE from_id = ? AND type = ? AND to_id = ?",
        (from_id, link_type, to_id),
    ).rowcount
    conn.commit()
    return removed > 0


def promote_epic(conn: sqlite3.Connection, card_id: int) -> None:
    """Turn an existing card into an epic, keeping its history.

    Closes it as a card (see :func:`_on_close`), moves it to :data:`EPIC_PROJECT` and
    records the project it came from as a comment. Raises
    :class:`CardNotFound` for an unknown id and :class:`RelationError` if it is
    already an epic, has a parent, or has any ``blocks`` link - each of which
    an epic can't carry.
    """
    with _write_lock(conn):
        row = _require_row(conn, card_id)
        if row[_KIND] == EPIC:
            raise RelationError(f"#{card_id} is already an epic")
        if row[_PARENT] is not None:
            raise RelationError(
                f"#{card_id} belongs to epic #{row[_PARENT]}; clear its parent first"
            )
        if conn.execute(
            "SELECT 1 FROM card_links WHERE type = ? AND (from_id = ? OR to_id = ?)",
            (BLOCKS, card_id, card_id),
        ).fetchone():
            raise RelationError(f"#{card_id} has blocks links; remove them first")
        now = _now()
        conn.execute(
            "UPDATE cards SET kind = ?, project = ?, updated_at = ? WHERE id = ?",
            (EPIC, EPIC_PROJECT, now, card_id),
        )
        conn.execute(
            "INSERT INTO card_comments (card_id, author, body, created_at) "
            "VALUES (?, ?, ?, ?)",
            (card_id, "me", f"Promoted to an epic (was in project {row[1]}).", now),
        )
        _on_close(conn, card_id)


def epic_members(
    conn: sqlite3.Connection, epic_id: int, *, include_archived: bool = False
) -> list[dict]:
    """Return an epic's member cards, ordered priority-then-oldest.

    Raises :class:`CardNotFound` for an unknown id and :class:`RelationError`
    if it isn't an epic.
    """
    _require_epic(conn, epic_id)
    return list_cards(conn, parent_id=epic_id, include_archived=include_archived)


def _progress(members: list[dict]) -> dict[str, int]:
    counts = {status: 0 for status in BOARD_ORDER}
    for card in members:
        counts[card["status"]] = counts.get(card["status"], 0) + 1
    counts["total"] = len(members)
    counts["waiting"] = sum(
        1 for card in members if card["waiting_on"] and card["status"] != DONE
    )
    return counts


def get_epic(conn: sqlite3.Connection, epic_id: int) -> dict:
    """Return an epic with its non-archived ``members`` and ``progress``.

    Raises :class:`CardNotFound` for an unknown id and :class:`RelationError`
    if it isn't an epic.
    """
    _require_epic(conn, epic_id)
    epic = get_card(conn, epic_id)
    assert epic is not None  # _require_epic found the row
    epic["members"] = list_cards(conn, parent_id=epic_id)
    epic["progress"] = _progress(epic["members"])
    return epic


def epic_without_open_members(conn: sqlite3.Connection, card_id: int) -> int | None:
    """Return *card_id*'s epic if it has no open members left, else ``None``.

    Open means neither ``done`` nor ``archived``. An epic's status is set by
    hand, so a caller that just finished or dropped a member can remind the
    user the epic may be ready to close - it never moves the epic itself. An
    epic that is already done or archived needs no reminder: ``None``.
    """
    settled = ", ".join("?" for _ in _SETTLED)
    row = conn.execute(
        f"SELECT e.id FROM cards c JOIN cards e ON e.id = c.parent_id "
        f"WHERE c.id = ? AND e.status NOT IN ({settled})",
        (card_id, *_SETTLED),
    ).fetchone()
    if row is None:
        return None
    epic_id = row[0]
    still_open = conn.execute(
        f"SELECT 1 FROM cards WHERE parent_id = ? AND status NOT IN ({settled})",
        (epic_id, *_SETTLED),
    ).fetchone()
    return None if still_open else epic_id


def list_epics(conn: sqlite3.Connection, *, include_done: bool = False) -> list[dict]:
    """Return epics, priority-then-oldest, each with a ``progress`` dict.

    ``progress`` counts the epic's non-archived members per
    :data:`BOARD_ORDER` status, plus ``total`` and ``waiting`` (open members
    held up by an unsettled blocker). Done epics are left out unless
    *include_done*; archived ones always are.
    """
    statuses = [s for s in BOARD_ORDER if include_done or s != DONE]
    epics = list_cards(conn, kind=EPIC, statuses=statuses)
    for epic in epics:
        epic["progress"] = _progress(list_cards(conn, parent_id=epic["id"]))
    return epics


def dependency_graph(conn: sqlite3.Connection, *, epic_id: int | None = None) -> dict:
    """Return the ``blocks`` graph as ``{"nodes": [...], "edges": [...]}``.

    Nodes are :func:`_summary` dicts plus a ``stub`` flag; edges are
    ``{"from", "to"}`` dicts. Archived cards are left out. Given *epic_id*,
    the nodes are the epic's members plus any card one link away outside it,
    flagged ``stub`` so a view can draw them dimmed; without it, every card on
    either end of a ``blocks`` link.

    Raises :class:`CardNotFound` / :class:`RelationError` for an *epic_id*
    that is unknown or not an epic.
    """
    members: set[int] | None = None
    if epic_id is not None:
        _require_epic(conn, epic_id)
        members = {
            card_id
            for (card_id,) in conn.execute(
                "SELECT id FROM cards WHERE parent_id = ? AND status != ?",
                (epic_id, ARCHIVED),
            )
        }
    edges = [
        {"from": from_id, "to": to_id}
        for from_id, to_id in conn.execute(
            "SELECT l.from_id, l.to_id FROM card_links l "
            "JOIN cards f ON f.id = l.from_id JOIN cards t ON t.id = l.to_id "
            "WHERE l.type = ? AND f.status != ? AND t.status != ? "
            "ORDER BY l.from_id, l.to_id",
            (BLOCKS, ARCHIVED, ARCHIVED),
        )
        if members is None or from_id in members or to_id in members
    ]
    ids = set(members or ())
    for edge in edges:
        ids.update((edge["from"], edge["to"]))
    nodes: list[dict] = []
    if ids:
        marks = ", ".join("?" for _ in ids)
        for row in conn.execute(
            f"SELECT id, title, status, project FROM cards WHERE id IN ({marks}) "
            f"ORDER BY id",
            sorted(ids),
        ):
            node = _summary(*row)
            node["stub"] = members is not None and row[0] not in members
            nodes.append(node)
    return {"nodes": nodes, "edges": edges}
