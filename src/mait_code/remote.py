"""The remote API — what another machine or agent may do to a mait-code instance.

A deliberately small, executive-free surface over one instance's board,
memories and reminders, for a host service to expose to remote clients — over
MCP, say. mait-code itself never listens on anything: transport,
authentication, scopes and process lifecycle all belong to the host.

What is here is the whole contract:

* **Read** the board, a card with its comments, the project list, memories
  (ranked like ``mc-tool-memory search``), whether memory search can use its
  vectors, and active reminders.
* **Create** a card. It always lands in ``backlog`` — there is no status
  parameter to override.
* **Refine** a card: edit its description and acceptance criteria, and move
  it between ``backlog`` and ``refined``. Any other column is refused.

What is absent is just as deliberate: deleting or archiving, tags, moves into
``in_progress`` / ``in_review`` / ``done``, memory writes, reflections and
reminder changes. Those are decisions for whoever hosts the instance, so the
functions do not exist here rather than refusing at runtime. A test pins
``__all__`` to an allowlist.

Every mutating call takes a required *client* name, recorded as the card's
``created_by`` on create and as the author of a comment on refine, so a card
raised remotely is identifiable before anyone acts on it.

The host runs as a different user from the instance it serves and pins its
own mait-code release, so this module is careful about what it trusts:

* Every function takes the instance's *data_dir* explicitly and reads only the
  databases in it — never ``dashboard.toml``, the settings ``[env]`` table or
  any other agent-writable file that would execute.
* The board and reminder functions read nothing else at all: no
  ``os.environ``, no settings file, no data-dir lookup.
* It never runs migrations. A database whose schema version differs from the
  one this release expects raises :class:`SchemaMismatch`.
* Memories, reminders and board reads open read-only; the two board writes
  open read-write with a busy timeout, since the instance writes it
  concurrently.

:func:`search_memories` is the exception: it embeds and ranks with the
*host's* own configuration, resolved like any mait-code setting (environment
variable, then the settings file, then the default).
:func:`memory_search_status` reads the same embedding settings, without
loading the provider. A host should pin all of it:

* **Environment** — ``MAIT_CODE_EMBEDDING_PROVIDER`` and
  ``MAIT_CODE_EMBEDDING_MODEL`` (or ``MAIT_CODE_BEDROCK_MODEL_ID`` and
  ``MAIT_CODE_BEDROCK_REGION``); the ranking knobs
  ``MAIT_CODE_SCORE_WEIGHT_{RECENCY,IMPORTANCE,RELEVANCE}``,
  ``MAIT_CODE_HALF_LIFE_{EPISODIC,SEMANTIC,PROCEDURAL}`` and
  ``MAIT_CODE_SCOPE_BOOST_{GLOBAL,CROSS_PROJECT}``; and ``MAIT_CODE_DATA_DIR``,
  ``XDG_CONFIG_HOME`` and ``HOME``, which locate the files below.
* **Files** — the flat keys of ``$XDG_CONFIG_HOME/mait-code/settings.toml``
  (its ``[env]`` table is not applied), and the local provider's model cache
  in ``models/`` under the host's data dir, downloaded on first use. The
  Bedrock provider also reads boto3's usual AWS credential chain.
* **Side effects** — the host's data dir is created if missing, and the
  Bedrock provider injects the OS trust store into :mod:`ssl` for the whole
  process.
* **Lifetime** — the ranking knobs and the embedding dimension are fixed when
  the memory modules are first imported, the settings file is cached on first
  read, and the provider is kept once loaded, so changes need a restart. So
  does a failed model load: it degrades every later search to keyword-only
  results.

The host must embed with the same provider and model the instance used. The
instance's ``memory.db`` records which provider and model built its vectors;
when the host's configuration differs (a different model, even one of the same
dimension, or a different width), vector search is skipped and results are
keyword-only, with a warning logged once per process. An instance with no
record yet is trusted as before. :func:`memory_search_status` reports the same
check up front, for a host's health endpoint. The ranking knobs are a second divergence:
the host's, not the instance's, decide the order of results.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from mait_code.tools.board import migrate as _board_migrate
from mait_code.tools.board import service as _board
from mait_code.tools.board.columns import (
    BACKLOG,
    REFINED,
    is_valid_status,
)
from mait_code.tools.board.service import CardNotFound
from mait_code.tools.reminders import migrate as _reminders_migrate
from mait_code.tools.reminders import service as _reminders

__all__ = [
    # Errors
    "CardNotFound",
    "RemoteError",
    "SchemaMismatch",
    "TransitionRefused",
    # Board
    "create_card",
    "get_card",
    "list_cards",
    "list_projects",
    "refine_card",
    # Memory
    "memory_search_status",
    "search_memories",
    # Reminders
    "list_reminders",
]

#: How long a board write waits for the instance's own writer, in seconds.
BUSY_TIMEOUT = 10.0

#: Longest accepted *client* name; it is stored on cards and comments.
MAX_CLIENT_LENGTH = 64

_PRIORITIES = ("low", "medium", "high")
_REFINABLE = (BACKLOG, REFINED)


class RemoteError(Exception):
    """Base class for errors raised by the remote API."""


class SchemaMismatch(RemoteError):
    """A database's schema version is not the one this release expects.

    Raised instead of migrating: the host pins its own mait-code release, so
    a newer or older instance needs the host upgrading (or the instance), not
    a schema change made by the host.

    Attributes:
        database: The database file name, e.g. ``"board.db"``.
        expected: The schema version this release of mait-code expects.
        found: The version recorded in the database (``0`` if it has none).
    """

    def __init__(self, database: str, expected: int, found: int) -> None:
        super().__init__(
            f"{database}: schema version {found}, this mait-code expects "
            f"{expected} — upgrade whichever side is older"
        )
        self.database = database
        self.expected = expected
        self.found = found


class TransitionRefused(RemoteError):
    """A refine asked for a card or column outside ``backlog``/``refined``.

    Attributes:
        card_id: The card the refine targeted.
        status: The column involved — the card's current one, or the
            requested target.
    """

    def __init__(self, card_id: int, status: str) -> None:
        super().__init__(
            f"card #{card_id}: refine only works between backlog and refined "
            f"(got {status!r})"
        )
        self.card_id = card_id
        self.status = status


# --- Connections ---


def _open(
    data_dir: Path,
    name: str,
    migrations: Sequence[tuple],
    *,
    readonly: bool,
) -> sqlite3.Connection:
    """Open *name* under *data_dir* without creating or migrating it."""
    path = Path(data_dir) / name
    if not path.is_file():
        raise FileNotFoundError(f"{path}: no such database")
    mode = "ro" if readonly else "rw"
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode={mode}", uri=True, timeout=BUSY_TIMEOUT
    )
    try:
        _check_schema(conn, name, migrations)
    except BaseException:
        conn.close()
        raise
    return conn


def _check_schema(
    conn: sqlite3.Connection, name: str, migrations: Sequence[tuple]
) -> None:
    expected = migrations[-1][0]
    try:
        found = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        found = 0
    if found != expected:
        raise SchemaMismatch(name, expected, found)


def _board_conn(data_dir: Path, *, readonly: bool) -> sqlite3.Connection:
    conn = _open(data_dir, "board.db", _board_migrate.MIGRATIONS, readonly=readonly)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _memory_conn(data_dir: Path) -> sqlite3.Connection:
    import sqlite_vec

    from mait_code.tools.memory import migrate as _memory_migrate

    conn = _open(data_dir, "memory.db", _memory_migrate.MIGRATIONS, readonly=True)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _reminders_conn(data_dir: Path) -> sqlite3.Connection:
    return _open(data_dir, "reminders.db", _reminders_migrate.MIGRATIONS, readonly=True)


def _require_client(client: str) -> str:
    client = client.strip()
    if not client:
        raise ValueError("client must name the caller")
    if len(client) > MAX_CLIENT_LENGTH:
        raise ValueError(f"client name is longer than {MAX_CLIENT_LENGTH} characters")
    return client


# --- Board ---


def list_cards(
    data_dir: Path,
    *,
    project: str | None = None,
    statuses: Iterable[str] | None = None,
    tag: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Return cards ordered priority-then-oldest.

    Args:
        data_dir: The instance's data directory.
        project: Restrict to one project, or ``None`` for every project.
        statuses: Restrict to these columns; ``None`` means every column
            except ``archived``.
        tag: Restrict to cards carrying this tag.
        search: Case-insensitive substring of the title.

    Returns:
        Card dicts in the ``mc-tool-board show --json`` shape, without
        comments.

    Raises:
        ValueError: If *statuses* names an unknown column.
    """
    if statuses is not None:
        statuses = list(statuses)
        unknown = [s for s in statuses if not is_valid_status(s)]
        if unknown:
            raise ValueError(f"unknown status: {', '.join(unknown)}")
    conn = _board_conn(data_dir, readonly=True)
    try:
        return _board.list_cards(
            conn, project=project, statuses=statuses, tag=tag, search=search
        )
    finally:
        conn.close()


def get_card(data_dir: Path, card_id: int) -> dict:
    """Return one card with its comments.

    Args:
        data_dir: The instance's data directory.
        card_id: The card's id.

    Returns:
        The card dict with a ``comments`` list, as ``show --json`` emits it.

    Raises:
        CardNotFound: If no card has that id.
    """
    conn = _board_conn(data_dir, readonly=True)
    try:
        return _card_with_comments(conn, card_id)
    finally:
        conn.close()


def list_projects(data_dir: Path) -> list[str]:
    """Return the distinct projects that have cards, sorted.

    Args:
        data_dir: The instance's data directory.
    """
    conn = _board_conn(data_dir, readonly=True)
    try:
        return _board.list_projects(conn)
    finally:
        conn.close()


def create_card(
    data_dir: Path,
    *,
    client: str,
    project: str,
    title: str,
    description: str | None = None,
    priority: str = "medium",
) -> dict:
    """Create a card in ``backlog``, recording *client* as its creator.

    There is no way to create a card anywhere but ``backlog``.

    Args:
        data_dir: The instance's data directory.
        client: Name of the calling client, stored as ``created_by``.
        project: Project the card belongs to.
        title: Card title.
        description: Optional markdown description.
        priority: ``"low"``, ``"medium"`` or ``"high"``.

    Returns:
        The new card, with its (empty) comments.

    Raises:
        ValueError: If *client*, *project* or *title* is blank, *client* is
            too long, or *priority* is unknown.
    """
    client = _require_client(client)
    if not project.strip():
        raise ValueError("project is required")
    if not title.strip():
        raise ValueError("title is required")
    if priority not in _PRIORITIES:
        raise ValueError(f"priority must be one of {', '.join(_PRIORITIES)}")
    conn = _board_conn(data_dir, readonly=False)
    try:
        card_id = _board.add_card(
            conn,
            project=project.strip(),
            title=title.strip(),
            description=description,
            priority=priority,
            created_by=client,
        )
        return _card_with_comments(conn, card_id)
    finally:
        conn.close()


def refine_card(
    data_dir: Path,
    card_id: int,
    *,
    client: str,
    description: str | None = None,
    acceptance: str | None = None,
    to: str = REFINED,
) -> dict:
    """Edit a card's description/acceptance and place it in backlog or refined.

    The card must currently sit in ``backlog`` or ``refined``, and *to* must
    be one of those two. The change and a comment authored by *client*
    recording it are written in one transaction, after re-checking the
    card's column under the write lock.

    Args:
        data_dir: The instance's data directory.
        card_id: The card to refine.
        client: Name of the calling client, recorded as the comment author.
        description: New description, or ``None`` to leave it.
        acceptance: New acceptance criteria, or ``None`` to leave them.
        to: Target column, ``"refined"`` (default) or ``"backlog"``.

    Returns:
        The card after the change, with its comments.

    Raises:
        CardNotFound: If no card has that id.
        TransitionRefused: If the card is outside backlog/refined, or *to*
            is any other column.
        ValueError: If *client* is blank or too long, or the call would change
            nothing.
    """
    client = _require_client(client)
    if to not in _REFINABLE:
        raise TransitionRefused(card_id, to)
    conn = _board_conn(data_dir, readonly=False)
    try:
        # Plain SQL rather than the service helpers: each of those commits on
        # its own, and the column re-check must share one transaction with the
        # write. That skips move_card's done-invariant, which is safe only
        # because backlog and refined never carry completed_at — revisit if
        # the service layer grows other bookkeeping for these columns.
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT status FROM cards WHERE id = ?", (card_id,)
            ).fetchone()
            if row is None:
                raise CardNotFound(card_id)
            current = row[0]
            if current not in _REFINABLE:
                raise TransitionRefused(card_id, current)
            changed = [
                name
                for name, value in (
                    ("description", description),
                    ("acceptance", acceptance),
                )
                if value is not None
            ]
            if not changed and current == to:
                raise ValueError("nothing to change")

            now = datetime.now(timezone.utc).isoformat()
            fields: dict[str, str] = {"status": to, "updated_at": now}
            if description is not None:
                fields["description"] = description
            if acceptance is not None:
                fields["acceptance_criteria"] = acceptance
            cols = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(
                f"UPDATE cards SET {cols} WHERE id = ?", (*fields.values(), card_id)
            )
            note = "Refined remotely"
            if changed:
                note += f": {' and '.join(changed)} updated"
            if current != to:
                note += f"{';' if changed else ':'} {current} → {to}"
            conn.execute(
                "INSERT INTO card_comments (card_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (card_id, client, note, now),
            )
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
        return _card_with_comments(conn, card_id)
    finally:
        conn.close()


def _card_with_comments(conn: sqlite3.Connection, card_id: int) -> dict:
    card = _board.get_card(conn, card_id)
    if card is None:
        raise CardNotFound(card_id)
    card["comments"] = _board.get_comments(conn, card_id)
    return card


# --- Memory ---


def search_memories(
    data_dir: Path,
    query: str,
    *,
    limit: int = 10,
    entry_type: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Search memories (keyword plus vector) and rank them.

    The same hybrid search and composite ranking as ``mc-tool-memory
    search``. Superseded and retired entries are excluded.

    Note:
        Unlike the rest of this module, the embedding provider and the
        ranking weights come from the host's environment and settings file —
        see the module docstring for exactly what to pin.

    Args:
        data_dir: The instance's data directory.
        query: Search text.
        limit: Maximum number of results.
        entry_type: Restrict to one entry type (e.g. ``"preference"``).
        project: Project context: global entries plus that project's are
            searched, and the project's own rank higher. ``None`` searches
            every scope.

    Returns:
        Memory entry dicts, best first, each with a ``score`` key.

    Raises:
        ValueError: If *query* is blank or *limit* is not positive.
    """
    if not query.strip():
        raise ValueError("query is required")
    if limit < 1:
        raise ValueError("limit must be positive")

    from mait_code.tools.memory.scoring import rank_results
    from mait_code.tools.memory.search import hybrid_search

    conn = _memory_conn(data_dir)
    try:
        results = hybrid_search(
            conn, query, limit=limit * 2, entry_type=entry_type, project=project
        )
    finally:
        conn.close()
    return [
        {**entry, "score": round(score, 4)}
        for score, entry in rank_results(results, limit=limit, query_project=project)
    ]


def memory_search_status(data_dir: Path) -> dict:
    """Report whether memory search can use the instance's vectors.

    The check :func:`search_memories` makes on every query, asked up front:
    the provider, model and width the host is configured to embed with,
    against the record of what built the instance's vectors. When they
    disagree, search runs keyword-only. Nothing is embedded and the
    embedding provider is never loaded, so this is cheap enough for a
    health check.

    Note:
        Like :func:`search_memories`, the configured side comes from the
        host's environment and settings file — see the module docstring.

    Args:
        data_dir: The instance's data directory.

    Returns:
        A dict with ``usable`` (bool), ``state`` (``"match"``,
        ``"unknown"``, ``"empty"``, ``"absent"``, ``"dimension"`` or
        ``"model"``), ``reason`` (one line), ``configured`` (``provider``,
        ``model``, ``dim``) and ``recorded`` (the same keys, or ``None``
        when the instance has no record). ``"unknown"`` and ``"empty"`` are
        usable; ``"absent"``, ``"dimension"`` and ``"model"`` are not.
        ``usable`` says only that the vectors fit the configured model, not
        that the provider will load: a missing model download, ``boto3`` or
        AWS credentials still leaves search keyword-only.

    Raises:
        FileNotFoundError: If the instance has no ``memory.db``.
        SchemaMismatch: If its schema version is not this release's.
    """
    from dataclasses import asdict

    from mait_code.tools.memory.embeddings import vectors_usable

    conn = _memory_conn(data_dir)
    try:
        status = vectors_usable(conn)
    finally:
        conn.close()
    return {
        "usable": status.usable,
        "state": status.state,
        "reason": status.reason,
        "configured": asdict(status.configured),
        "recorded": asdict(status.recorded) if status.recorded else None,
    }


# --- Reminders ---


def list_reminders(data_dir: Path) -> list[dict]:
    """Return active (undismissed) reminders, ordered by due time.

    Args:
        data_dir: The instance's data directory.

    Returns:
        Dicts with ``id``, ``what``, ``due`` (ISO 8601 string) and
        ``overdue`` (bool).
    """
    conn = _reminders_conn(data_dir)
    try:
        overdue, upcoming = _reminders.active_reminders(conn)
    finally:
        conn.close()
    return [
        {**r, "due": r["due"].isoformat(), "overdue": is_overdue}
        for is_overdue, group in ((True, overdue), (False, upcoming))
        for r in group
    ]
