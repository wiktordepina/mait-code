"""Tests for the In Review column — its place in the flow, the ``review_card``
service call, and the ``review`` CLI verb.

In Review is a normal status (always valid, no setting); only the board TUI
hides it while empty, and that's covered in ``tests/cli/test_board_tui.py``.
"""

import json
import sqlite3

import pytest

from mait_code.tools.board import export, service
from mait_code.tools.board.columns import (
    ALL_STATUSES,
    BOARD_ORDER,
    DONE,
    IN_PROGRESS,
    IN_REVIEW,
    is_valid_status,
    label,
)

from tests.tools.board.conftest import TEST_PROJECT


def _card(conn: sqlite3.Connection, title: str, status: str) -> int:
    cid = service.add_card(conn, project=TEST_PROJECT, title=title)
    service.move_card(conn, cid, status)
    return cid


def _main(monkeypatch, *argv: str) -> None:
    from mait_code.tools.board.cli import main

    monkeypatch.setattr("sys.argv", ["mc-tool-board", *argv])
    main()


# --- columns ---


def test_in_review_sits_between_in_progress_and_done():
    idx = BOARD_ORDER.index(IN_REVIEW)
    assert BOARD_ORDER[idx - 1] == IN_PROGRESS
    assert BOARD_ORDER[idx + 1] == DONE


def test_in_review_is_always_a_valid_status():
    assert is_valid_status(IN_REVIEW)
    assert IN_REVIEW in ALL_STATUSES
    assert label(IN_REVIEW) == "In Review"


# --- service ---


def test_review_card_moves_and_records_pr(board_db):
    cid = _card(board_db, "x", IN_PROGRESS)
    service.review_card(board_db, cid, pr="https://example.com/pr/7")
    card = service.get_card(board_db, cid)
    assert card["status"] == IN_REVIEW
    assert card["references"] == [{"label": "PR", "value": "https://example.com/pr/7"}]


def test_review_card_without_pr_adds_no_reference(board_db):
    cid = _card(board_db, "x", IN_PROGRESS)
    service.review_card(board_db, cid)
    card = service.get_card(board_db, cid)
    assert card["status"] == IN_REVIEW
    assert card["references"] == []


def test_review_card_from_done_clears_completed_at(board_db):
    # Reopening a done card into review must honour the done-invariant.
    cid = _card(board_db, "x", DONE)
    service.review_card(board_db, cid)
    assert service.get_card(board_db, cid)["completed_at"] is None


def test_review_card_unknown_id_raises(board_db):
    with pytest.raises(service.CardNotFound):
        service.review_card(board_db, 999)


def test_summary_counts_include_in_review(board_db):
    _card(board_db, "x", IN_REVIEW)
    counts = service.summary_counts(board_db, project=TEST_PROJECT)
    assert counts[IN_REVIEW] == 1


# --- CLI ---


def test_review_verb_moves_card(mock_conn, capsys, monkeypatch):
    cid = _card(mock_conn, "x", IN_PROGRESS)
    _main(monkeypatch, "review", str(cid))
    assert f"Card #{cid} → In Review." in capsys.readouterr().out
    assert service.get_card(mock_conn, cid)["status"] == IN_REVIEW


def test_review_verb_json_returns_card_with_pr(mock_conn, capsys, monkeypatch):
    cid = _card(mock_conn, "x", IN_PROGRESS)
    _main(monkeypatch, "review", str(cid), "--pr", "https://example.com/pr/9", "--json")
    card = json.loads(capsys.readouterr().out)
    assert card["id"] == cid
    assert card["status"] == IN_REVIEW
    assert {"label": "PR", "value": "https://example.com/pr/9"} in card["references"]
    assert "comments" in card  # the show --json shape


def test_review_verb_unknown_id_exits(mock_conn, capsys, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "review", "999")
    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_move_accepts_in_review(mock_conn, monkeypatch):
    cid = _card(mock_conn, "x", IN_PROGRESS)
    _main(monkeypatch, "move", str(cid), "in_review")
    assert service.get_card(mock_conn, cid)["status"] == IN_REVIEW


def test_list_groups_in_review_between_in_progress_and_done(
    mock_conn, capsys, monkeypatch
):
    _card(mock_conn, "shipped", DONE)
    _card(mock_conn, "parked", IN_REVIEW)
    _card(mock_conn, "working", IN_PROGRESS)
    _main(monkeypatch, "list")
    out = capsys.readouterr().out
    assert out.index("In Progress (1)") < out.index("In Review (1)")
    assert out.index("In Review (1)") < out.index("Done (1)")


def test_list_status_filter_in_review(mock_conn, capsys, monkeypatch):
    _card(mock_conn, "parked", IN_REVIEW)
    _card(mock_conn, "working", IN_PROGRESS)
    _main(monkeypatch, "list", "--status", "in_review", "--json")
    cards = json.loads(capsys.readouterr().out)
    assert [c["title"] for c in cards] == ["parked"]


def test_export_groups_in_review(board_db):
    _card(board_db, "parked", IN_REVIEW)
    _card(board_db, "working", IN_PROGRESS)
    md = export.export_board(board_db, project=TEST_PROJECT)
    assert md.index("In Progress") < md.index("In Review") < md.index("parked")
