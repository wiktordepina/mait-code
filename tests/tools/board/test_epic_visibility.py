"""Epics stay off every kanban-shaped reader of the board.

An epic is a card row on the reserved :data:`EPIC_PROJECT`; it belongs in the
initiatives view only. Each test seeds one live card and one epic into the
isolated data dir and asserts a reader sees the card and not the epic — so a
reader that bypasses the service's ``kind='card'`` default shows up here.
"""

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.columns import EPIC, EPIC_PROJECT, IN_PROGRESS
from mait_code.tools.board.db import get_connection, get_data_dir

EPIC_TITLE = "Umbrella initiative"
CARD_TITLE = "Real work"


@pytest.fixture
def seeded(monkeypatch):
    """One in-progress card on project ``p`` and one in-progress epic."""
    monkeypatch.setattr("mait_code.tools.board.db.get_project", lambda: "p")
    conn = get_connection()
    try:
        epic = service.add_card(conn, project=None, title=EPIC_TITLE, kind=EPIC)
        service.move_card(conn, epic, IN_PROGRESS)
        card = service.add_card(conn, project="p", title=CARD_TITLE, parent_id=epic)
        service.move_card(conn, card, IN_PROGRESS)
    finally:
        conn.close()
    return {"epic": epic, "card": card}


def test_service_listings(seeded):
    conn = get_connection()
    try:
        assert [c["id"] for c in service.list_cards(conn)] == [seeded["card"]]
        assert service.summary_counts(conn)[IN_PROGRESS] == 1
        assert service.list_projects(conn) == ["p"]
        both = service.list_cards(conn, kind=None)
        assert {c["id"] for c in both} == set(seeded.values())
    finally:
        conn.close()


def test_session_start_board_line(seeded):
    from mait_code.hooks.session_start.context import board_section

    assert board_section() == "1 in progress"


def test_hub_badges(seeded):
    from mait_code.cli._home_tui import _Badges

    badges = _Badges()
    assert (badges.board_live, badges.board_in_progress, badges.board_projects) == (
        1,
        1,
        1,
    )


def test_plain_board_and_home_renders(seeded, capsys):
    from mait_code.cli import _board_render, _home_render

    _board_render()
    _home_render()
    out = capsys.readouterr().out
    assert CARD_TITLE in out
    assert EPIC_TITLE not in out and EPIC_PROJECT not in out


def test_dashboard_tiles(seeded):
    from mait_code.cli._dashboard import builtin_tile_lines

    board = " ".join(line.text for line in builtin_tile_lines("board"))
    assert "1 live" in board and EPIC_TITLE not in board
    velocity = next(
        line.text
        for line in builtin_tile_lines("velocity")
        if line.text.startswith("cards")
    )
    assert "1 this week" in velocity


def test_export_board(seeded):
    from mait_code.tools.board.export import export_board

    conn = get_connection()
    try:
        out = export_board(conn)
    finally:
        conn.close()
    assert CARD_TITLE in out and EPIC_TITLE not in out


def test_remote_reads(seeded):
    from mait_code import remote

    data_dir = get_data_dir()
    assert [c["id"] for c in remote.list_cards(data_dir)] == [seeded["card"]]
    assert remote.list_projects(data_dir) == ["p"]
