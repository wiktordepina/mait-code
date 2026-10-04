"""Tests for :mod:`mait_code.remote` — the executive-free remote API.

The contract under test is as much about what is *absent* as what works:
the public surface is pinned to an allowlist, creates can only land in
backlog, refines can only move between backlog and refined, the facade never
migrates or writes memories/reminders, and it never reads agent-writable
config or touches the environment.
"""

from __future__ import annotations

import inspect
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from mait_code import remote
from mait_code.tools.board import migrate as board_migrate
from mait_code.tools.board import service as board_service
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    ARCHIVED,
    BACKLOG,
    DONE,
    IN_PROGRESS,
    IN_REVIEW,
    REFINED,
)
from mait_code.tools.board.db import get_connection as board_connection
from mait_code.tools.memory.db import get_connection as memory_connection
from mait_code.tools.reminders.db import get_connection as reminders_connection

#: The whole public surface. Adding a name here is a decision about what a
#: remote client may do to an instance — keep executive actions out.
ALLOWED = {
    "CardNotFound",
    "RemoteError",
    "SchemaMismatch",
    "TransitionRefused",
    "create_card",
    "get_card",
    "list_cards",
    "list_projects",
    "refine_card",
    "search_memories",
    "list_reminders",
}


@pytest.fixture
def instance(tmp_path: Path) -> Path:
    """An instance data dir with all three databases created and migrated."""
    data = tmp_path / "instance"
    data.mkdir()
    for connect, name in (
        (board_connection, "board.db"),
        (memory_connection, "memory.db"),
        (reminders_connection, "reminders.db"),
    ):
        connect(data / name).close()
    return data


def _add(data: Path, title: str, status: str = BACKLOG) -> int:
    conn = board_connection(data / "board.db")
    try:
        card_id = board_service.add_card(conn, project="proj", title=title)
        if status != BACKLOG:
            board_service.move_card(conn, card_id, status)
        return card_id
    finally:
        conn.close()


def _schema_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    finally:
        conn.close()


# --- The surface ---


def test_public_surface_is_the_allowlist():
    assert set(remote.__all__) == ALLOWED


def test_no_public_function_hides_outside_all():
    """A public function defined in the module but left out of ``__all__``
    would still be importable — catch that too."""
    defined = {
        name
        for name, obj in inspect.getmembers(remote)
        if (inspect.isfunction(obj) or inspect.isclass(obj))
        and getattr(obj, "__module__", None) == remote.__name__
        and not name.startswith("_")
    }
    assert defined <= ALLOWED


@pytest.mark.parametrize(
    "name",
    [
        "move_card",
        "complete_card",
        "review_card",
        "archive_card",
        "remove_card",
        "delete_card",
        "add_tag",
        "store_memory",
        "dismiss_reminder",
    ],
)
def test_executive_functions_are_absent(name):
    assert not hasattr(remote, name)


# --- Reads ---


def test_list_cards_excludes_archived_by_default(instance):
    keep = _add(instance, "keep")
    _add(instance, "gone", ARCHIVED)
    assert [c["id"] for c in remote.list_cards(instance)] == [keep]


def test_list_cards_filters_by_status(instance):
    _add(instance, "a")
    refined = _add(instance, "b", REFINED)
    cards = remote.list_cards(instance, statuses=[REFINED])
    assert [c["id"] for c in cards] == [refined]


def test_list_cards_rejects_unknown_status(instance):
    with pytest.raises(ValueError, match="bogus"):
        remote.list_cards(instance, statuses=["bogus"])


def test_get_card_includes_comments(instance):
    card_id = _add(instance, "x")
    conn = board_connection(instance / "board.db")
    board_service.add_comment(conn, card_id, "hello")
    conn.close()
    card = remote.get_card(instance, card_id)
    assert card["title"] == "x"
    assert [c["body"] for c in card["comments"]] == ["hello"]


def test_get_card_missing_raises(instance):
    with pytest.raises(remote.CardNotFound):
        remote.get_card(instance, 999)


def test_list_projects(instance):
    _add(instance, "x")
    assert remote.list_projects(instance) == ["proj"]


# --- Create ---


def test_create_card_lands_in_backlog_with_provenance(instance):
    card = remote.create_card(
        instance, client="hermes", project="proj", title="  Do a thing  "
    )
    assert card["status"] == BACKLOG
    assert card["created_by"] == "hermes"
    assert card["title"] == "Do a thing"
    assert card["comments"] == []


def test_create_card_has_no_status_parameter():
    params = inspect.signature(remote.create_card).parameters
    assert "status" not in params
    with pytest.raises(TypeError):
        remote.create_card(  # type: ignore[call-arg]
            Path("."), client="x", project="p", title="t", status=DONE
        )


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"client": "  "}, "client"),
        ({"project": ""}, "project"),
        ({"title": " "}, "title"),
        ({"priority": "urgent"}, "priority"),
    ],
)
def test_create_card_validates(instance, kwargs, match):
    args = {"client": "hermes", "project": "proj", "title": "t", **kwargs}
    with pytest.raises(ValueError, match=match):
        remote.create_card(instance, **args)


def test_local_cards_have_no_creator(instance):
    card_id = _add(instance, "local")
    assert remote.get_card(instance, card_id)["created_by"] is None


# --- Refine ---


def test_refine_moves_backlog_to_refined_and_records_client(instance):
    card_id = _add(instance, "x")
    card = remote.refine_card(
        instance, card_id, client="laptop", description="d", acceptance="a"
    )
    assert card["status"] == REFINED
    assert card["description"] == "d"
    assert card["acceptance_criteria"] == "a"
    (comment,) = card["comments"]
    assert comment["author"] == "laptop"
    assert "description and acceptance updated" in comment["body"]
    assert "backlog → refined" in comment["body"]


def test_refine_can_move_back_to_backlog(instance):
    card_id = _add(instance, "x", REFINED)
    card = remote.refine_card(instance, card_id, client="laptop", to=BACKLOG)
    assert card["status"] == BACKLOG


def test_refine_edits_in_place(instance):
    card_id = _add(instance, "x", REFINED)
    card = remote.refine_card(instance, card_id, client="laptop", acceptance="new")
    assert card["status"] == REFINED
    assert card["acceptance_criteria"] == "new"


@pytest.mark.parametrize("status", [IN_PROGRESS, IN_REVIEW, DONE, ARCHIVED])
def test_refine_refuses_cards_outside_backlog_and_refined(instance, status):
    card_id = _add(instance, "x", status)
    with pytest.raises(remote.TransitionRefused):
        remote.refine_card(instance, card_id, client="laptop", description="d")
    card = remote.get_card(instance, card_id)
    assert card["status"] == status
    assert card["description"] is None
    assert card["comments"] == []


@pytest.mark.parametrize(
    "target", [s for s in ALL_STATUSES if s not in (BACKLOG, REFINED)]
)
def test_refine_refuses_every_other_target(instance, target):
    card_id = _add(instance, "x")
    with pytest.raises(remote.TransitionRefused):
        remote.refine_card(instance, card_id, client="laptop", to=target)
    assert remote.get_card(instance, card_id)["status"] == BACKLOG


def test_refine_checks_the_column_under_the_write_lock(instance, monkeypatch):
    """The transaction is opened IMMEDIATE, before the column is read, so the
    check and the write see the same state."""
    card_id = _add(instance, "x")
    statements: list[str] = []
    real_open = remote._open

    def traced(*args, **kwargs):
        conn = real_open(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(remote, "_open", traced)
    remote.refine_card(instance, card_id, client="laptop", description="d")
    begin = statements.index("BEGIN IMMEDIATE")
    check = next(i for i, s in enumerate(statements) if s.startswith("SELECT status"))
    assert begin < check


def test_refine_missing_card(instance):
    with pytest.raises(remote.CardNotFound):
        remote.refine_card(instance, 999, client="laptop", description="d")


def test_refine_noop_is_refused(instance):
    card_id = _add(instance, "x", REFINED)
    with pytest.raises(ValueError, match="nothing to change"):
        remote.refine_card(instance, card_id, client="laptop")


def test_refine_requires_client(instance):
    card_id = _add(instance, "x")
    with pytest.raises(ValueError, match="client"):
        remote.refine_card(instance, card_id, client="", description="d")


def test_client_name_is_bounded(instance):
    card_id = _add(instance, "x")
    long_name = "x" * (remote.MAX_CLIENT_LENGTH + 1)
    with pytest.raises(ValueError, match="longer than"):
        remote.create_card(instance, client=long_name, project="p", title="t")
    with pytest.raises(ValueError, match="longer than"):
        remote.refine_card(instance, card_id, client=long_name, description="d")
    ok = "x" * remote.MAX_CLIENT_LENGTH
    assert (
        remote.create_card(instance, client=ok, project="p", title="t")["created_by"]
        == ok
    )


def test_refine_cannot_overwrite_a_concurrent_move(instance, monkeypatch):
    """While another connection holds the write lock, a refine waits and gives
    up rather than writing over a concurrent move; once the move lands, the
    refine sees it and refuses."""
    card_id = _add(instance, "x")
    monkeypatch.setattr(remote, "BUSY_TIMEOUT", 0.1)
    holder = sqlite3.connect(instance / "board.db", isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(
            "UPDATE cards SET status = ? WHERE id = ?", (IN_PROGRESS, card_id)
        )
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            remote.refine_card(instance, card_id, client="laptop", description="d")
        holder.execute("COMMIT")
    finally:
        holder.close()
    # Once the concurrent move lands, the refine sees it and refuses.
    with pytest.raises(remote.TransitionRefused):
        remote.refine_card(instance, card_id, client="laptop", description="d")


# --- Schema version ---


def test_missing_database_is_not_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        remote.list_cards(tmp_path)
    assert not (tmp_path / "board.db").exists()


def test_older_schema_raises_and_is_not_migrated(instance):
    path = instance / "board.db"
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM schema_version WHERE version = 4")
    conn.commit()
    conn.close()
    expected = board_migrate.MIGRATIONS[-1][0]
    with pytest.raises(remote.SchemaMismatch) as exc:
        remote.list_cards(instance)
    assert (exc.value.expected, exc.value.found) == (expected, expected - 1)
    assert _schema_version(path) == expected - 1


def test_newer_schema_raises(instance):
    path = instance / "board.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO schema_version (version, description) VALUES (999, 'future')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(remote.SchemaMismatch) as exc:
        remote.create_card(instance, client="x", project="p", title="t")
    assert exc.value.found == 999
    assert "board.db" in str(exc.value)


def test_unversioned_database_raises(tmp_path):
    sqlite3.connect(tmp_path / "reminders.db").close()
    with pytest.raises(remote.SchemaMismatch) as exc:
        remote.list_reminders(tmp_path)
    assert exc.value.found == 0


# --- Read-only stores ---


@pytest.mark.parametrize(
    "call, readonly",
    [
        (lambda d, c: remote.list_cards(d), True),
        (lambda d, c: remote.get_card(d, c), True),
        (lambda d, c: remote.list_projects(d), True),
        (lambda d, c: remote.create_card(d, client="x", project="p", title="t"), False),
        (lambda d, c: remote.refine_card(d, c, client="x", description="d"), False),
    ],
)
def test_board_opens_read_write_only_to_write(instance, monkeypatch, call, readonly):
    card_id = _add(instance, "x")
    modes: list[bool] = []
    real_open = remote._open

    def spy(data_dir, name, migrations, *, readonly):
        modes.append(readonly)
        return real_open(data_dir, name, migrations, readonly=readonly)

    monkeypatch.setattr(remote, "_open", spy)
    call(instance, card_id)
    assert modes == [readonly]


@pytest.mark.parametrize(
    "opener, sql",
    [
        (remote._memory_conn, "DELETE FROM memory_entries"),
        (remote._reminders_conn, "DELETE FROM reminders"),
        (
            lambda d: remote._board_conn(d, readonly=True),
            "DELETE FROM cards",
        ),
    ],
)
def test_read_only_connections_refuse_writes(instance, opener, sql):
    conn = opener(instance)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(sql)
    finally:
        conn.close()


# --- Memory ---


def _seed_memories(data: Path) -> None:
    conn = memory_connection(data / "memory.db")
    for content, importance, scope, project in (
        ("Wiktor prefers British English", 8, "global", None),
        ("homelab uses Forgejo for CI", 6, "project", "homelab"),
        ("mait-code uses uv for packaging", 6, "project", "mait-code"),
    ):
        conn.execute(
            "INSERT INTO memory_entries "
            "(content, entry_type, importance, memory_class, scope, project) "
            "VALUES (?, 'fact', ?, 'semantic', ?, ?)",
            (content, importance, scope, project),
        )
    conn.commit()
    conn.close()


def test_search_memories_ranks_and_scores(instance):
    _seed_memories(instance)
    with patch("mait_code.tools.memory.search.embed_text", return_value=None):
        results = remote.search_memories(instance, "uses")
    assert {r["content"] for r in results} == {
        "homelab uses Forgejo for CI",
        "mait-code uses uv for packaging",
    }
    assert all("score" in r for r in results)
    assert [r["score"] for r in results] == sorted(
        (r["score"] for r in results), reverse=True
    )


def test_search_memories_project_scope(instance):
    _seed_memories(instance)
    with patch("mait_code.tools.memory.search.embed_text", return_value=None):
        results = remote.search_memories(instance, "uses", project="homelab")
    assert [r["content"] for r in results] == ["homelab uses Forgejo for CI"]


def test_search_memories_limit(instance):
    _seed_memories(instance)
    with patch("mait_code.tools.memory.search.embed_text", return_value=None):
        assert len(remote.search_memories(instance, "uses", limit=1)) == 1


@pytest.mark.parametrize("kwargs", [{"query": " "}, {"query": "x", "limit": 0}])
def test_search_memories_validates(instance, kwargs):
    with pytest.raises(ValueError):
        remote.search_memories(instance, **kwargs)


# --- Reminders ---


def test_list_reminders(instance):
    now = datetime.now(timezone.utc)
    conn = reminders_connection(instance / "reminders.db")
    for what, due, dismissed in (
        ("past", now - timedelta(hours=1), 0),
        ("future", now + timedelta(hours=1), 0),
        ("done", now - timedelta(hours=2), 1),
    ):
        conn.execute(
            "INSERT INTO reminders (what, due, created_at, dismissed) "
            "VALUES (?, ?, ?, ?)",
            (what, due.isoformat(), now.isoformat(), dismissed),
        )
    conn.commit()
    conn.close()
    reminders = remote.list_reminders(instance)
    assert [(r["what"], r["overdue"]) for r in reminders] == [
        ("past", True),
        ("future", False),
    ]
    assert isinstance(reminders[0]["due"], str)


# --- Hostile configuration ---


class _FakeTextEmbedding:
    """Stands in for fastembed's model so the real provider path runs offline."""

    def __init__(self, model_name, cache_dir):
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    def embed(self, texts):
        import numpy as np

        return iter([np.zeros(768, dtype="float32") for _ in texts])


def test_never_reads_agent_config_or_touches_environment(
    instance, tmp_path, monkeypatch
):
    """Hostile config planted by the instance's owner neither runs in, nor
    changes the environment of, the host process.

    Nothing in the remote API reads ``dashboard.toml`` or calls ``apply_env``
    today; this pins that against a future change. The embedding provider is
    stubbed only at the model itself, so the real provider path — the one
    part that reads the host's settings — runs, and must cache under the
    host's data dir, not the instance's.
    """
    import mait_code.tools.memory.embeddings as embeddings

    marker = tmp_path / "pwned"
    (instance / "dashboard.toml").write_text(
        f'[[tile]]\ncommand = "touch {marker}"\ntitle = "x"\n'
    )
    hostile_settings = '[env]\nHOSTILE = "1"\nLD_PRELOAD = "/tmp/evil.so"\n'
    (instance / "settings.toml").write_text(hostile_settings)
    xdg = tmp_path / "xdg-config" / "mait-code"
    xdg.mkdir(parents=True, exist_ok=True)
    (xdg / "settings.toml").write_text(hostile_settings)
    _seed_memories(instance)
    card_id = _add(instance, "x")
    before = dict(os.environ)

    def forbidden(*args, **kwargs):
        raise AssertionError("the remote API must not run anything")

    monkeypatch.setattr("mait_code.config.apply_env", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr("fastembed.TextEmbedding", _FakeTextEmbedding)
    monkeypatch.setattr(embeddings, "_provider", None)
    monkeypatch.setattr(embeddings, "_provider_failed", False)

    remote.list_cards(instance)
    remote.get_card(instance, card_id)
    remote.list_projects(instance)
    remote.create_card(instance, client="hermes", project="proj", title="t")
    remote.refine_card(instance, card_id, client="laptop", description="d")
    remote.search_memories(instance, "uses")
    remote.list_reminders(instance)

    assert embeddings._provider is not None, "the provider path did not run"
    assert dict(os.environ) == before
    assert not marker.exists()
    assert not (instance / "models").exists()
    assert (Path(os.environ["MAIT_CODE_DATA_DIR"]) / "models").is_dir()
