"""Tests for binding board cards to Claude Code sessions.

Covers the environment reader and liveness check in
:mod:`~mait_code.tools.board.sessions`, the service's bind/release/rebind
rules, and the ``bind``/``unbind``/``list --session|--mine`` CLI surface.

Liveness is real, not faked: the test process's own pid is a live session, and
the pid of a child that has already exited is a dead one.
"""

import json
import os
import subprocess
import sys

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    DONE,
    IN_PROGRESS,
    IN_REVIEW,
    REFINED,
)
from mait_code.tools.board.db import connection
from mait_code.tools.board.sessions import (
    PID_ENV,
    SESSION_ENV,
    SessionRef,
    current_session,
    pid_alive,
)

from tests.tools.board.conftest import TEST_PROJECT

LIVE = SessionRef("live-session", os.getpid())


@pytest.fixture
def dead_pid() -> int:
    """The pid of a process that has already exited."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _card(conn, title: str = "card", status: str = IN_PROGRESS) -> int:
    cid = service.add_card(conn, project=TEST_PROJECT, title=title)
    service.move_card(conn, cid, status)
    return cid


def _rows(conn) -> list[tuple]:
    return conn.execute(
        "SELECT card_id, session_id, pid FROM card_sessions ORDER BY card_id, session_id"
    ).fetchall()


# --- environment & liveness ---


@pytest.mark.parametrize(
    ("session", "pid", "expected"),
    [
        ("abc", "42", SessionRef("abc", 42)),
        ("  abc ", " 42 ", SessionRef("abc", 42)),
        (None, "42", None),
        ("abc", None, None),
        ("abc", "nope", None),
        ("abc", "0", None),
        ("abc", "-3", None),
        ("", "", None),
    ],
)
def test_current_session_reads_both_variables(monkeypatch, session, pid, expected):
    for name, value in ((SESSION_ENV, session), (PID_ENV, pid)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert current_session() == expected


def test_pid_alive(dead_pid):
    assert pid_alive(os.getpid())
    assert not pid_alive(dead_pid)
    assert not pid_alive(0)
    assert not pid_alive(-1)


# --- schema ---


def test_binding_is_unique_per_card_and_session(board_db):
    cid = _card(board_db)
    service.bind_session(board_db, cid, LIVE)
    service.bind_session(board_db, cid, LIVE)
    assert len(_rows(board_db)) == 1


def test_removing_a_card_cascades_its_bindings(board_db):
    cid = _card(board_db)
    service.bind_session(board_db, cid, LIVE)
    service.remove_card(board_db, cid)
    assert _rows(board_db) == []


# --- service: bind / unbind / read ---


def test_bind_requires_in_progress(board_db):
    cid = _card(board_db, status=REFINED)
    with pytest.raises(service.NotInProgress) as exc:
        service.bind_session(board_db, cid, LIVE)
    assert exc.value.status == REFINED
    assert _rows(board_db) == []


def test_bind_unknown_card(board_db):
    with pytest.raises(service.CardNotFound):
        service.bind_session(board_db, 999, LIVE)


def test_a_card_takes_several_sessions(board_db):
    cid = _card(board_db)
    other = SessionRef("other-session", os.getpid())
    service.bind_session(board_db, cid, LIVE)
    service.bind_session(board_db, cid, other)
    ids = {b["session_id"] for b in service.card_sessions(board_db, cid)}
    assert ids == {"live-session", "other-session"}


def test_rebinding_refreshes_the_pid(board_db, dead_pid):
    cid = _card(board_db)
    service.bind_session(board_db, cid, SessionRef("s", dead_pid))
    service.bind_session(board_db, cid, SessionRef("s", os.getpid()))
    assert _rows(board_db) == [(cid, "s", os.getpid())]


def test_card_dicts_carry_active_sessions_only(board_db, dead_pid):
    cid = _card(board_db)
    service.bind_session(board_db, cid, LIVE)
    board_db.execute(
        "INSERT INTO card_sessions (card_id, session_id, pid, bound_at) "
        "VALUES (?, 'gone', ?, '2026-01-01')",
        (cid, dead_pid),
    )
    board_db.commit()

    card = service.get_card(board_db, cid)
    assert card is not None
    assert [b["session_id"] for b in card["sessions"]] == ["live-session"]
    assert set(card["sessions"][0]) == {"session_id", "pid", "bound_at"}
    # Reads never write: the dead row is still there until the next write.
    assert len(_rows(board_db)) == 2


def test_a_closed_session_survives_other_writes_until_resumed(board_db, dead_pid):
    """A dead binding is hidden, not deleted, so a later resume can reclaim it."""
    mine = _card(board_db, "mine")
    service.bind_session(board_db, mine, SessionRef("closed", dead_pid))
    # A parallel session carries on writing while "closed" is shut.
    theirs = _card(board_db, "theirs", status=REFINED)
    service.move_card(
        board_db, theirs, IN_PROGRESS, session=SessionRef("parallel", os.getpid())
    )
    service.bind_session(board_db, theirs, SessionRef("another", os.getpid()))
    assert service.list_cards(board_db, session="closed") == []

    assert service.refresh_session_pid(board_db, "closed", os.getpid()) == 1
    assert [c["id"] for c in service.list_cards(board_db, session="closed")] == [mine]


def test_unbind(board_db):
    cid = _card(board_db)
    service.bind_session(board_db, cid, LIVE)
    assert service.unbind_session(board_db, cid, "live-session") is True
    assert service.unbind_session(board_db, cid, "live-session") is False
    with pytest.raises(service.CardNotFound):
        service.unbind_session(board_db, 999, "live-session")


def test_list_cards_filters_by_live_session(board_db, dead_pid):
    mine = _card(board_db, "mine")
    theirs = _card(board_db, "theirs")
    stale = _card(board_db, "stale")
    unbound = _card(board_db, "unbound")
    service.bind_session(board_db, mine, LIVE)
    service.bind_session(board_db, theirs, SessionRef("someone-else", os.getpid()))
    board_db.execute(
        "INSERT INTO card_sessions (card_id, session_id, pid, bound_at) "
        "VALUES (?, 'live-session', ?, '2026-01-01')",
        (stale, dead_pid),
    )
    board_db.commit()

    titles = [c["title"] for c in service.list_cards(board_db, session="live-session")]
    assert titles == ["mine"]
    assert unbound not in [c["id"] for c in service.list_cards(board_db, session="x")]


# --- service: the session invariant on moves ---


def test_moving_into_in_progress_with_a_session_binds(board_db):
    cid = _card(board_db, status=REFINED)
    service.move_card(board_db, cid, IN_PROGRESS, session=LIVE)
    assert _rows(board_db) == [(cid, "live-session", os.getpid())]


def test_moving_into_in_progress_without_a_session_does_not_bind(board_db):
    cid = _card(board_db, status=REFINED)
    service.move_card(board_db, cid, IN_PROGRESS)
    assert _rows(board_db) == []


@pytest.mark.parametrize("target", [BACKLOG, REFINED, IN_REVIEW, DONE, ARCHIVED])
def test_leaving_in_progress_releases_every_binding(board_db, target):
    cid = _card(board_db)
    service.bind_session(board_db, cid, LIVE)
    service.bind_session(board_db, cid, SessionRef("second", os.getpid()))
    service.move_card(board_db, cid, target, session=LIVE)
    assert _rows(board_db) == []


@pytest.mark.parametrize(
    "leave",
    [
        lambda conn, cid: service.complete_card(conn, cid, summary="done"),
        lambda conn, cid: service.review_card(conn, cid, pr="https://x/pr/1"),
        lambda conn, cid: service.archive_card(conn, cid),
        lambda conn, cid: service.refine_card(conn, cid, acceptance="AC"),
    ],
    ids=["complete", "review", "archive", "refine"],
)
def test_workflow_verbs_release_bindings(board_db, leave):
    cid = _card(board_db)
    service.bind_session(board_db, cid, LIVE)
    leave(board_db, cid)
    assert _rows(board_db) == []


def test_moving_back_to_in_progress_binds_the_current_session(board_db):
    cid = _card(board_db)
    service.bind_session(board_db, cid, SessionRef("original", os.getpid()))
    service.review_card(board_db, cid)
    service.move_card(board_db, cid, IN_PROGRESS, session=LIVE)
    assert _rows(board_db) == [(cid, "live-session", os.getpid())]


def test_other_cards_keep_their_bindings(board_db):
    leaving = _card(board_db, "leaving")
    staying = _card(board_db, "staying")
    service.bind_session(board_db, leaving, LIVE)
    service.bind_session(board_db, staying, LIVE)
    service.complete_card(board_db, leaving)
    assert _rows(board_db) == [(staying, "live-session", os.getpid())]


def test_next_claim_binds(board_db):
    cid = _card(board_db, status=REFINED)
    card = service.next_refined(board_db, TEST_PROJECT, claim=True, session=LIVE)
    assert card is not None and card["id"] == cid
    assert [b["session_id"] for b in card["sessions"]] == ["live-session"]


def test_next_without_claim_never_binds(board_db):
    _card(board_db, status=REFINED)
    service.next_refined(board_db, TEST_PROJECT, session=LIVE)
    assert _rows(board_db) == []


# --- service: following a resume or a /clear ---


def test_refresh_session_pid_follows_a_resume(board_db, dead_pid):
    cid = _card(board_db)
    service.bind_session(board_db, cid, SessionRef("resumed", dead_pid))
    assert service.refresh_session_pid(board_db, "resumed", os.getpid()) == 1
    assert _rows(board_db) == [(cid, "resumed", os.getpid())]
    assert service.refresh_session_pid(board_db, "resumed", os.getpid()) == 0


def test_rebind_pid_follows_a_clear(board_db):
    first = _card(board_db, "first")
    second = _card(board_db, "second")
    elsewhere = _card(board_db, "elsewhere")
    service.bind_session(board_db, first, SessionRef("before-clear", os.getpid()))
    service.bind_session(board_db, second, SessionRef("before-clear", os.getpid()))
    service.bind_session(board_db, elsewhere, SessionRef("other-process", 1))

    assert service.rebind_pid(board_db, os.getpid(), "after-clear") == 2
    assert _rows(board_db) == [
        (first, "after-clear", os.getpid()),
        (second, "after-clear", os.getpid()),
        (elsewhere, "other-process", 1),
    ]


def test_rebind_pid_never_duplicates_a_binding(board_db):
    cid = _card(board_db)
    service.bind_session(board_db, cid, SessionRef("old", os.getpid()))
    service.bind_session(board_db, cid, SessionRef("new", os.getpid()))
    service.rebind_pid(board_db, os.getpid(), "new")
    assert _rows(board_db) == [(cid, "new", os.getpid())]


# --- CLI ---


def _main(monkeypatch, *argv: str) -> None:
    from mait_code.tools.board.cli import main

    monkeypatch.setattr("mait_code.tools.board.cli.get_project", lambda: TEST_PROJECT)
    monkeypatch.setattr("sys.argv", ["mc-tool-board", *argv])
    main()


def _in_session(monkeypatch, session_id: str = "cli-session") -> SessionRef:
    monkeypatch.setenv(SESSION_ENV, session_id)
    monkeypatch.setenv(PID_ENV, str(os.getpid()))
    return SessionRef(session_id, os.getpid())


def _cli_card(status: str = IN_PROGRESS) -> int:
    with connection() as conn:
        return _card(conn, status=status)


def _cli_rows() -> list[tuple]:
    with connection() as conn:
        return _rows(conn)


def test_cli_move_binds_inside_a_session(monkeypatch):
    _in_session(monkeypatch)
    cid = _cli_card(status=REFINED)
    _main(monkeypatch, "move", str(cid), "in_progress")
    assert _cli_rows() == [(cid, "cli-session", os.getpid())]


def test_cli_move_outside_a_session_does_not_bind(monkeypatch):
    cid = _cli_card(status=REFINED)
    _main(monkeypatch, "move", str(cid), "in_progress")
    assert _cli_rows() == []


def test_cli_next_claim_binds(monkeypatch, capsys):
    _in_session(monkeypatch)
    cid = _cli_card(status=REFINED)
    _main(monkeypatch, "next", "--claim", "--json")
    card = json.loads(capsys.readouterr().out)
    assert card["id"] == cid
    assert card["sessions"][0]["session_id"] == "cli-session"


def test_cli_bind_defaults_to_the_current_session(monkeypatch, capsys):
    _in_session(monkeypatch)
    cid = _cli_card()
    _main(monkeypatch, "bind", str(cid), "--json")
    card = json.loads(capsys.readouterr().out)
    assert [b["session_id"] for b in card["sessions"]] == ["cli-session"]


def test_cli_bind_explicit_session_and_pid(monkeypatch, capsys):
    cid = _cli_card()
    _main(
        monkeypatch, "bind", str(cid), "--session", "given", "--pid", str(os.getpid())
    )
    assert "bound to session given" in capsys.readouterr().out
    assert _cli_rows() == [(cid, "given", os.getpid())]


@pytest.mark.parametrize(
    "argv",
    [["--pid", "123"], []],
    ids=["no-session", "nothing"],
)
def test_cli_bind_refuses_without_session_and_pid(monkeypatch, capsys, argv):
    cid = _cli_card()
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "bind", str(cid), *argv)
    assert exc.value.code == 1
    assert "session id and a pid" in capsys.readouterr().err
    assert _cli_rows() == []


def test_cli_bind_session_needs_its_own_pid(monkeypatch, capsys):
    """Inside a session, --session alone must not borrow this process's pid."""
    _in_session(monkeypatch)
    cid = _cli_card()
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "bind", str(cid), "--session", "someone-else")
    assert exc.value.code == 1
    assert "--session needs --pid" in capsys.readouterr().err
    assert _cli_rows() == []


def test_cli_bind_refuses_a_bad_pid(monkeypatch, capsys):
    cid = _cli_card()
    with pytest.raises(SystemExit):
        _main(monkeypatch, "bind", str(cid), "--session", "s", "--pid", "0")
    assert "positive integer" in capsys.readouterr().err


def test_cli_bind_refuses_a_card_not_in_progress(monkeypatch, capsys):
    _in_session(monkeypatch)
    cid = _cli_card(status=REFINED)
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "bind", str(cid))
    assert exc.value.code == 1
    assert "only In Progress cards bind" in capsys.readouterr().err


def test_cli_bind_unknown_card(monkeypatch, capsys):
    _in_session(monkeypatch)
    with pytest.raises(SystemExit):
        _main(monkeypatch, "bind", "999")
    assert "not found" in capsys.readouterr().err


def test_cli_unbind(monkeypatch, capsys):
    session = _in_session(monkeypatch)
    cid = _cli_card()
    with connection() as conn:
        service.bind_session(conn, cid, session)
    _main(monkeypatch, "unbind", str(cid))
    assert "unbound from session" in capsys.readouterr().out
    _main(monkeypatch, "unbind", str(cid))
    assert "was not bound" in capsys.readouterr().out
    assert _cli_rows() == []


def test_cli_unbind_needs_a_session(monkeypatch, capsys):
    cid = _cli_card()
    with pytest.raises(SystemExit):
        _main(monkeypatch, "unbind", str(cid))
    assert "needs a session id" in capsys.readouterr().err


def test_cli_list_mine_and_session(monkeypatch, capsys):
    session = _in_session(monkeypatch)
    mine = _cli_card()
    _cli_card()
    with connection() as conn:
        service.bind_session(conn, mine, session)

    _main(monkeypatch, "list", "--mine", "--json")
    assert [c["id"] for c in json.loads(capsys.readouterr().out)] == [mine]
    _main(monkeypatch, "list", "--session", "cli-session", "--json")
    assert [c["id"] for c in json.loads(capsys.readouterr().out)] == [mine]
    _main(monkeypatch, "list", "--session", "nobody", "--json")
    assert json.loads(capsys.readouterr().out) == []


def test_cli_list_mine_spans_projects(monkeypatch, capsys):
    session = _in_session(monkeypatch)
    with connection() as conn:
        here = _card(conn, "here")
        cid = service.add_card(conn, project="elsewhere", title="there")
        service.move_card(conn, cid, IN_PROGRESS)
        service.bind_session(conn, here, session)
        service.bind_session(conn, cid, session)

    _main(monkeypatch, "list", "--mine", "--json")
    assert sorted(c["id"] for c in json.loads(capsys.readouterr().out)) == [here, cid]
    _main(monkeypatch, "list", "--mine")
    assert "there [elsewhere]" in capsys.readouterr().out


def test_cli_list_mine_needs_a_session(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _main(monkeypatch, "list", "--mine")
    assert "--mine needs" in capsys.readouterr().err


def test_cli_show_lists_sessions(monkeypatch, capsys):
    session = _in_session(monkeypatch, "0123456789abcdef")
    cid = _cli_card()
    with connection() as conn:
        service.bind_session(conn, cid, session)
    _main(monkeypatch, "show", str(cid))
    assert f"sessions: 01234567 (pid {os.getpid()})" in capsys.readouterr().out
