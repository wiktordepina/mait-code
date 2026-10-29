"""Tests for playbook runs on board cards: a per-step run log.

Covers migration 7's constraints, the service's start / step / end rules and
the run-ending close paths, run history, how a run rides along on every card
read, and the ``run`` CLI verbs with the ``show``, export and ``summary --session`` surfaces.
"""

import json
import os
import sqlite3
import threading

import pytest

from mait_code.tools.board import export, service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    DONE,
    IN_PROGRESS,
    IN_REVIEW,
    REFINED,
    STEP_DONE,
    STEP_IN_PROGRESS,
    STEP_PAUSED,
    STEP_PENDING,
    STEP_SKIPPED,
)
from mait_code.tools.board.db import connection, get_connection
from mait_code.tools.board.sessions import PID_ENV, SESSION_ENV, SessionRef

from tests.tools.board.conftest import TEST_PROJECT

STEPS = ["Refine", "Design review", "Implement"]


def _card(conn, title: str = "card", status: str = IN_PROGRESS) -> int:
    cid = service.add_card(conn, project=TEST_PROJECT, title=title)
    service.move_card(conn, cid, status)
    return cid


def _run(conn, cid: int) -> dict:
    run = service.get_run(conn, cid)
    assert run is not None
    return run


def _step(conn, cid: int, position: int) -> dict:
    return _run(conn, cid)["steps"][position - 1]


def _runs(conn, cid: int) -> list[tuple]:
    return conn.execute(
        "SELECT playbook, ended_at IS NULL FROM card_runs WHERE card_id = ? ORDER BY id",
        (cid,),
    ).fetchall()


@pytest.fixture
def running(board_db) -> int:
    """A card with an open three-step ``work`` run."""
    cid = _card(board_db)
    service.start_run(board_db, cid, "work", STEPS)
    return cid


# --- schema ---


def test_a_step_status_outside_the_set_is_refused_by_the_schema(board_db, running):
    with pytest.raises(sqlite3.IntegrityError):
        board_db.execute("UPDATE card_run_steps SET status = 'nope'")


def test_removing_a_card_cascades_its_runs_and_steps(board_db, running):
    service.remove_card(board_db, running)
    assert board_db.execute("SELECT COUNT(*) FROM card_runs").fetchone()[0] == 0
    assert board_db.execute("SELECT COUNT(*) FROM card_run_steps").fetchone()[0] == 0


def test_the_schema_allows_one_open_run_per_card(board_db, running):
    with pytest.raises(sqlite3.IntegrityError):
        board_db.execute(
            "INSERT INTO card_runs (card_id, playbook, started_at, updated_at) "
            "VALUES (?, 'x', 'now', 'now')",
            (running,),
        )


def test_the_schema_allows_one_step_in_progress_per_run(board_db, running):
    with pytest.raises(sqlite3.IntegrityError):
        board_db.execute("UPDATE card_run_steps SET status = 'in_progress'")


# --- starting a run ---


def test_start_writes_every_step_pending_in_order(board_db, running):
    run = _run(board_db, running)
    assert run["playbook"] == "work"
    assert run["ended_at"] is None
    assert run["current"] is None
    assert [(s["position"], s["name"], s["status"]) for s in run["steps"]] == [
        (1, "Refine", STEP_PENDING),
        (2, "Design review", STEP_PENDING),
        (3, "Implement", STEP_PENDING),
    ]


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([], "at least one step"),
        (["A", "  "], "step 2 has no name"),
        (["A", "2"], "all digits"),
        (["A", "B", "A"], "appears twice"),
    ],
)
def test_start_refuses_a_step_list_it_cannot_address(board_db, steps, message):
    cid = _card(board_db)
    with pytest.raises(service.RunRefused, match=message):
        service.start_run(board_db, cid, "work", steps)
    assert _runs(board_db, cid) == []


def test_start_refuses_an_empty_playbook(board_db):
    cid = _card(board_db)
    with pytest.raises(service.RunRefused, match="playbook name"):
        service.start_run(board_db, cid, "  ", STEPS)


@pytest.mark.parametrize("status", [DONE, ARCHIVED])
def test_start_refuses_a_closed_card(board_db, status):
    cid = _card(board_db, status=status)
    with pytest.raises(service.RunRefused, match="only open cards run"):
        service.start_run(board_db, cid, "work", STEPS)


def test_start_refuses_an_epic(board_db):
    eid = service.add_card(board_db, project=None, title="epic", kind="epic")
    with pytest.raises(service.RunRefused, match="is an epic"):
        service.start_run(board_db, eid, "work", STEPS)


@pytest.mark.parametrize("status", [BACKLOG, REFINED, IN_PROGRESS, IN_REVIEW])
def test_start_works_in_any_open_column(board_db, status):
    cid = _card(board_db, status=status)
    service.start_run(board_db, cid, "work", STEPS)
    assert _run(board_db, cid)["playbook"] == "work"


def test_start_refuses_an_open_run_unless_replacing(board_db, running):
    with pytest.raises(service.RunRefused, match="already has an open run"):
        service.start_run(board_db, running, "other", ["X"])
    service.start_run(board_db, running, "other", ["X"], replace=True)
    assert _run(board_db, running)["playbook"] == "other"
    assert _runs(board_db, running) == [("work", 0), ("other", 1)]


def test_start_unknown_card(board_db):
    with pytest.raises(service.CardNotFound):
        service.start_run(board_db, 999, "work", STEPS)


# --- step rules ---


def test_in_progress_sets_started_and_names_the_current_step(board_db, running):
    service.set_step(board_db, running, "2", STEP_IN_PROGRESS)
    step = _step(board_db, running, 2)
    assert step["started_at"] is not None and step["finished_at"] is None
    assert _run(board_db, running)["current"] == 2


def test_a_step_is_addressed_by_exact_name(board_db, running):
    service.set_step(board_db, running, "Design review", STEP_DONE)
    assert _step(board_db, running, 2)["status"] == STEP_DONE
    with pytest.raises(service.RunRefused, match="no step 'design review'"):
        service.set_step(board_db, running, "design review", STEP_DONE)


@pytest.mark.parametrize("step", ["4", "0", "Nope", "²"])
def test_an_unknown_step_is_refused(board_db, running, step):
    with pytest.raises(service.RunRefused, match="has no step"):
        service.set_step(board_db, running, step, STEP_DONE)


def test_a_second_step_in_progress_is_refused_naming_the_first(board_db, running):
    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    with pytest.raises(service.RunRefused, match=r"step 1 \(Refine\) is already"):
        service.set_step(board_db, running, "2", STEP_IN_PROGRESS)
    assert _step(board_db, running, 2)["status"] == STEP_PENDING


def test_setting_the_step_in_progress_again_changes_nothing(board_db, running):
    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    before = _run(board_db, running)
    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    assert _run(board_db, running) == before


def test_done_sets_finished_and_a_redo_starts_afresh(board_db, running):
    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    first_start = _step(board_db, running, 1)["started_at"]
    service.set_step(board_db, running, "1", STEP_DONE)
    assert _step(board_db, running, 1)["finished_at"] is not None

    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    redo = _step(board_db, running, 1)
    assert redo["finished_at"] is None
    assert redo["started_at"] > first_start


def test_resuming_a_paused_step_keeps_its_start(board_db, running):
    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    started = _step(board_db, running, 1)["started_at"]
    service.set_step(board_db, running, "1", STEP_PAUSED, reason="waiting on CI")
    paused = _step(board_db, running, 1)
    assert (paused["started_at"], paused["reason"]) == (started, "waiting on CI")
    assert _run(board_db, running)["current"] == 1

    service.set_step(board_db, running, "1", STEP_IN_PROGRESS)
    resumed = _step(board_db, running, 1)
    assert (resumed["started_at"], resumed["reason"]) == (started, None)


def test_pausing_a_pending_step_starts_its_clock(board_db, running):
    service.set_step(board_db, running, "2", STEP_PAUSED)
    assert _step(board_db, running, 2)["started_at"] is not None


def test_pending_resets_a_step(board_db, running):
    service.set_step(board_db, running, "1", STEP_SKIPPED, reason="not needed")
    service.set_step(board_db, running, "1", STEP_PENDING)
    step = _step(board_db, running, 1)
    assert (step["started_at"], step["finished_at"], step["reason"]) == (
        None,
        None,
        None,
    )


def test_the_current_step_falls_back_to_the_lowest_paused(board_db, running):
    service.set_step(board_db, running, "3", STEP_PAUSED)
    service.set_step(board_db, running, "2", STEP_PAUSED)
    assert _run(board_db, running)["current"] == 2
    service.set_step(board_db, running, "3", STEP_IN_PROGRESS)
    assert _run(board_db, running)["current"] == 3


def test_a_skip_needs_a_reason(board_db, running):
    with pytest.raises(service.RunRefused, match="needs a reason"):
        service.set_step(board_db, running, "2", STEP_SKIPPED)
    with pytest.raises(service.RunRefused, match="needs a reason"):
        service.set_step(board_db, running, "2", STEP_SKIPPED, reason="   ")


@pytest.mark.parametrize("status", [STEP_PENDING, STEP_IN_PROGRESS, STEP_DONE])
def test_a_reason_is_refused_where_none_belongs(board_db, running, status):
    with pytest.raises(service.RunRefused, match="a reason goes with"):
        service.set_step(board_db, running, "1", status, reason="why")


def test_an_unknown_status_is_a_value_error(board_db, running):
    with pytest.raises(ValueError, match="unknown step status"):
        service.set_step(board_db, running, "1", "nope")


def test_a_skip_finishes_the_step_and_comments_each_time(board_db, running):
    service.set_step(board_db, running, "2", STEP_SKIPPED, reason="tiny change")
    service.set_step(board_db, running, "2", STEP_SKIPPED, reason="really tiny")
    step = _step(board_db, running, 2)
    assert step["finished_at"] is not None and step["reason"] == "really tiny"
    bodies = [c["body"] for c in service.get_comments(board_db, running)]
    assert bodies == [
        "Skipped step 2 (Design review): tiny change",
        "Skipped step 2 (Design review): really tiny",
    ]


def test_a_failed_skip_comment_rolls_the_step_back(board_db, running):
    board_db.execute(
        "CREATE TEMP TRIGGER no_comments BEFORE INSERT ON card_comments "
        "BEGIN SELECT RAISE(ABORT, 'comments are down'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="comments are down"):
        service.set_step(board_db, running, "2", STEP_SKIPPED, reason="tiny")
    assert _step(board_db, running, 2)["status"] == STEP_PENDING


def test_a_step_change_bumps_the_run_and_the_card(board_db, running):
    board_db.execute("UPDATE card_runs SET updated_at = '2000-01-01'")
    board_db.execute("UPDATE cards SET updated_at = '2000-01-01'")
    board_db.commit()
    service.set_step(board_db, running, "1", STEP_DONE)
    assert _run(board_db, running)["updated_at"] > "2000-01-02"
    assert service.get_card(board_db, running)["updated_at"] > "2000-01-02"


def test_an_unknown_card_is_reported_before_a_reason_problem(board_db):
    with pytest.raises(service.CardNotFound):
        service.set_step(board_db, 999, "1", STEP_DONE, reason="why")


def test_a_step_change_needs_an_open_run(board_db):
    cid = _card(board_db)
    with pytest.raises(service.RunRefused, match="has no open run"):
        service.set_step(board_db, cid, "1", STEP_DONE)


# --- ending a run ---


def test_a_run_never_ends_when_its_steps_finish(board_db, running):
    for position in ("1", "2", "3"):
        service.set_step(board_db, running, position, STEP_DONE)
    run = _run(board_db, running)
    assert run["ended_at"] is None
    service.set_step(board_db, running, "3", STEP_IN_PROGRESS)  # still redoable


def test_end_run_keeps_it_as_history_and_bumps_the_card(board_db, running):
    board_db.execute("UPDATE cards SET updated_at = '2000-01-01'")
    board_db.commit()
    service.end_run(board_db, running)
    assert service.get_run(board_db, running) is None
    assert _runs(board_db, running) == [("work", 0)]
    assert service.get_card(board_db, running)["updated_at"] > "2000-01-02"
    with pytest.raises(service.RunRefused, match="has no open run"):
        service.end_run(board_db, running)


@pytest.mark.parametrize(
    "close",
    [
        lambda conn, cid: service.complete_card(conn, cid, summary="done"),
        lambda conn, cid: service.archive_card(conn, cid),
        lambda conn, cid: service.move_card(conn, cid, DONE),
        lambda conn, cid: service.move_card(conn, cid, ARCHIVED),
        lambda conn, cid: service.promote_epic(conn, cid),
    ],
    ids=["complete", "archive", "move-done", "move-archived", "promote"],
)
def test_closing_a_card_ends_its_run(board_db, running, close):
    close(board_db, running)
    assert _runs(board_db, running) == [("work", 0)]


@pytest.mark.parametrize(
    "move",
    [
        lambda conn, cid: service.review_card(conn, cid),
        lambda conn, cid: service.move_card(conn, cid, REFINED),
        lambda conn, cid: service.refine_card(conn, cid, acceptance="AC"),
    ],
    ids=["review", "move-refined", "refine"],
)
def test_open_moves_keep_the_run(board_db, running, move):
    move(board_db, running)
    assert _runs(board_db, running) == [("work", 1)]


# --- history ---


def test_list_runs_returns_every_run_newest_first(board_db, running):
    service.set_step(board_db, running, "2", STEP_SKIPPED, reason="tiny")
    service.start_run(board_db, running, "redo", ["Only"], replace=True)
    service.end_run(board_db, running)
    service.start_run(board_db, running, "third", STEPS)
    runs = service.list_runs(board_db, running)
    assert [r["playbook"] for r in runs] == ["third", "redo", "work"]
    assert runs[0] == _run(board_db, running)
    assert runs[0]["ended_at"] is None
    assert runs[1]["ended_at"] and runs[2]["ended_at"]
    assert runs[2]["steps"][1]["reason"] == "tiny"


def test_list_runs_orders_by_id_not_start_time(board_db, running):
    service.end_run(board_db, running)
    service.start_run(board_db, running, "later", ["A"])
    board_db.execute(
        "UPDATE card_runs SET started_at = '2000-01-01' WHERE playbook = 'later'"
    )
    board_db.commit()
    assert [r["playbook"] for r in service.list_runs(board_db, running)] == [
        "later",
        "work",
    ]


def test_an_ended_run_has_no_current_step(board_db, running):
    service.set_step(board_db, running, "2", STEP_IN_PROGRESS)
    service.start_run(board_db, running, "redo", STEPS, replace=True)
    old = service.list_runs(board_db, running)[1]
    assert old["steps"][1]["status"] == STEP_IN_PROGRESS
    assert old["current"] is None
    assert not any("current" in line for line in export.run_lines(old))


def test_list_runs_on_a_card_without_runs(board_db):
    assert service.list_runs(board_db, _card(board_db)) == []


def test_list_runs_unknown_card(board_db):
    with pytest.raises(service.CardNotFound):
        service.list_runs(board_db, 999)


def test_run_lines_header_names_the_end_only_when_ended(board_db, running):
    assert "ended" not in export.run_lines(_run(board_db, running))[0]
    service.end_run(board_db, running)
    header = export.run_lines(service.list_runs(board_db, running)[0])[0]
    assert header.startswith("Run: work · started ") and " · ended " in header


# --- concurrency ---


def _race(db_path, *calls) -> list[BaseException | None]:
    """Run each call on its own connection at once; return what each raised."""
    barrier = threading.Barrier(len(calls))
    results: list[BaseException | None] = [None] * len(calls)

    def worker(i: int, call) -> None:
        conn = get_connection(db_path)
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            barrier.wait()
            call(conn)
        except BaseException as exc:  # noqa: BLE001 - returned for the asserts
            results[i] = exc
        finally:
            conn.close()

    threads = [
        threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_two_racing_starts_leave_one_open_run(board_db, tmp_path):
    cid = _card(board_db)
    db_path = tmp_path / "test_board.db"
    results = _race(
        db_path,
        lambda conn: service.start_run(conn, cid, "first", STEPS),
        lambda conn: service.start_run(conn, cid, "second", STEPS),
    )
    assert sum(r is None for r in results) == 1
    assert all(isinstance(r, service.RunRefused) for r in results if r is not None)
    assert [open_ for _, open_ in _runs(board_db, cid)] == [1]


def test_two_racing_step_starts_leave_one_in_progress(board_db, running, tmp_path):
    db_path = tmp_path / "test_board.db"
    results = _race(
        db_path,
        lambda conn: service.set_step(conn, running, "1", STEP_IN_PROGRESS),
        lambda conn: service.set_step(conn, running, "2", STEP_IN_PROGRESS),
    )
    assert sum(r is None for r in results) == 1
    statuses = [s["status"] for s in _run(board_db, running)["steps"]]
    assert statuses.count(STEP_IN_PROGRESS) == 1


# --- reads ---


def test_every_card_read_carries_its_run(board_db, running):
    plain = _card(board_db, "plain")
    by_id = {c["id"]: c for c in service.list_cards(board_db)}
    assert by_id[running]["run"]["playbook"] == "work"
    assert by_id[plain]["run"] is None
    assert service.get_card(board_db, running)["run"] == _run(board_db, running)


def test_list_reads_runs_in_a_fixed_number_of_queries(board_db):
    def run_queries(count: int) -> int:
        for i in range(count):
            cid = _card(board_db, f"card {i}")
            service.start_run(board_db, cid, "work", STEPS)
        statements: list[str] = []
        board_db.set_trace_callback(statements.append)
        try:
            service.list_cards(board_db)
        finally:
            board_db.set_trace_callback(None)
        return sum("card_run" in s for s in statements)

    assert run_queries(1) == run_queries(5) == 2


# --- CLI ---


def _main(monkeypatch, *argv: str) -> None:
    from mait_code.tools.board.cli import main

    monkeypatch.setattr("mait_code.tools.board.cli.get_project", lambda: TEST_PROJECT)
    monkeypatch.setattr("sys.argv", ["mc-tool-board", *argv])
    main()


def _cli_card(status: str = IN_PROGRESS) -> int:
    with connection() as conn:
        return _card(conn, status=status)


def test_cli_run_verbs(monkeypatch, capsys):
    cid = _cli_card()
    _main(
        monkeypatch, "run", "start", str(cid), "--playbook", "work", "--steps", *STEPS
    )
    assert capsys.readouterr().out == f"Card #{cid}: started run 'work' (3 steps).\n"
    _main(
        monkeypatch,
        "run",
        "step",
        str(cid),
        "Design review",
        "skipped",
        "--reason",
        "too",
        "small",
    )
    assert "step 2 (Design review) → skipped." in capsys.readouterr().out
    _main(monkeypatch, "run", "step", str(cid), "3", "in_progress")
    assert "step 3 (Implement) → in progress." in capsys.readouterr().out

    _main(monkeypatch, "run", "show", str(cid))
    out = capsys.readouterr().out
    assert out.startswith("Run: work · started ")
    assert "  2. skipped      Design review — too small\n" in out
    assert "  3. in progress  Implement  ← current\n" in out

    _main(monkeypatch, "run", "end", str(cid))
    assert capsys.readouterr().out == f"Card #{cid}: run ended.\n"
    _main(monkeypatch, "run", "show", str(cid), "--json")
    assert json.loads(capsys.readouterr().out) is None
    _main(monkeypatch, "run", "show", str(cid))
    assert capsys.readouterr().out == f"Card #{cid} has no open run.\n"


def test_cli_mutating_run_verbs_emit_the_card(monkeypatch, capsys):
    cid = _cli_card()
    _main(
        monkeypatch,
        "run",
        "start",
        str(cid),
        "--playbook",
        "work",
        "--steps",
        "A",
        "--json",
    )
    card = json.loads(capsys.readouterr().out)
    assert card["id"] == cid and "comments" in card
    assert card["run"]["steps"][0]["name"] == "A"
    _main(monkeypatch, "run", "step", str(cid), "1", "done", "--json")
    assert json.loads(capsys.readouterr().out)["run"]["steps"][0]["status"] == "done"
    _main(monkeypatch, "run", "end", str(cid), "--json")
    assert json.loads(capsys.readouterr().out)["run"] is None


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["run", "step", "{cid}", "1", "done"], "has no open run"),
        (["run", "end", "{cid}"], "has no open run"),
        (
            ["run", "start", "{cid}", "--playbook", "w", "--steps", "A", "A"],
            "appears twice",
        ),
    ],
)
def test_cli_run_refusals_exit_1(monkeypatch, capsys, argv, message):
    cid = _cli_card()
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, *(a.format(cid=cid) for a in argv))
    assert exc.value.code == 1
    assert f"card #{cid}" in (err := capsys.readouterr().err) and message in err


def test_cli_run_unknown_card(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _main(monkeypatch, "run", "show", "999")
    assert "not found" in capsys.readouterr().err


def test_cli_run_show_all(monkeypatch, capsys):
    cid = _cli_card()
    _main(monkeypatch, "run", "show", str(cid), "--all")
    assert capsys.readouterr().out == f"Card #{cid} has no runs.\n"
    _main(monkeypatch, "run", "show", str(cid), "--all", "--json")
    assert json.loads(capsys.readouterr().out) == []

    with connection() as conn:
        service.start_run(conn, cid, "work", STEPS)
        service.set_step(conn, cid, "1", STEP_IN_PROGRESS)
        service.start_run(conn, cid, "redo", STEPS, replace=True)
        service.set_step(conn, cid, "2", STEP_SKIPPED, reason="tiny")
    _main(monkeypatch, "run", "show", str(cid))
    open_block = capsys.readouterr().out
    _main(monkeypatch, "run", "show", str(cid), "--all")
    out = capsys.readouterr().out
    newest, oldest = out.split("\n\n")
    assert newest + "\n" == open_block
    assert "  2. skipped      Design review — tiny\n" in newest
    assert oldest.startswith("Run: work · started ") and " · ended " in oldest
    assert "  1. in progress  Refine\n" in oldest + "\n"
    assert "current" not in oldest

    _main(monkeypatch, "run", "show", str(cid), "--all", "--json")
    runs = json.loads(capsys.readouterr().out)
    with connection() as conn:
        assert runs == service.list_runs(conn, cid)
    assert [r["playbook"] for r in runs] == ["redo", "work"]


def test_cli_run_show_all_unknown_card(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "run", "show", "999", "--all")
    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_cli_show_prints_the_run(monkeypatch, capsys):
    cid = _cli_card()
    with connection() as conn:
        service.start_run(conn, cid, "work", STEPS)
    _main(monkeypatch, "show", str(cid))
    assert "\nRun: work · started " in capsys.readouterr().out


# --- export and summary ---


def test_markdown_export_has_a_run_section(board_db, running):
    service.set_step(board_db, running, "2", STEP_SKIPPED, reason="tiny")
    service.set_step(board_db, running, "3", STEP_IN_PROGRESS)
    md = export.card_markdown(service.get_card(board_db, running))
    assert "## Run\n\n`work`, started " in md
    assert "2. **Design review** — skipped: tiny" in md
    assert "3. **Implement** — in progress *(current)*" in md


def test_summary_session_bound_cards_carry_their_run(monkeypatch, capsys):
    """A Refined card bound to the session shows its run, as /work refines."""
    monkeypatch.setenv(SESSION_ENV, "playbook")
    monkeypatch.setenv(PID_ENV, str(os.getpid()))
    with connection() as conn:
        cid = _card(conn, "refining", status=REFINED)
        service.bind_session(conn, cid, SessionRef("playbook", os.getpid()))
        service.start_run(conn, cid, "work", STEPS)
        service.set_step(conn, cid, "1", STEP_IN_PROGRESS)

    _main(monkeypatch, "summary", "--json", "--session", "playbook")
    [card] = json.loads(capsys.readouterr().out)["bound"]
    assert (card["id"], card["status"]) == (cid, REFINED)
    assert card["run"]["current"] == 1
    assert card["run"]["steps"][0]["name"] == "Refine"


def test_remote_get_card_carries_the_run(tmp_path):
    from mait_code import remote
    from mait_code.tools.board.db import get_data_dir

    with connection() as conn:
        cid = _card(conn)
        service.start_run(conn, cid, "work", STEPS)
    card = remote.get_card(get_data_dir(), cid)
    assert card["run"]["playbook"] == "work"
    assert [
        c["run"]["playbook"]
        for c in remote.list_cards(get_data_dir())
        if c["id"] == cid
    ] == ["work"]
