"""Tests for the board export layer — rendering, exporters, and the CLI subcommand."""

import argparse
import json
import sqlite3

import pytest

from mait_code.tools.board import export, service
from mait_code.tools.board.columns import ARCHIVED, BACKLOG, REFINED

from tests.tools.board.conftest import TEST_PROJECT


def _ns(**kwargs):
    """An export-command Namespace with every flag defaulted."""
    defaults = dict(
        id=None,
        format="markdown",
        out=None,
        all=False,
        project=None,
        status=None,
        archived=False,
        search=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _full_card(conn: sqlite3.Connection) -> int:
    """A card exercising every exportable field."""
    cid = service.add_card(
        conn,
        project=TEST_PROJECT,
        title="Ship the exporter",
        description="A **bold** plan.\n\n- step one\n- step two",
        priority="high",
    )
    service.refine_card(conn, cid, acceptance="- it exports\n- it round-trips")
    service.add_tag(conn, cid, "tui")
    service.add_reference(conn, cid, "PR", "https://example.com/pr/1")
    service.add_comment(conn, cid, "first\nsecond line", author="claude")
    return cid


# --- card_markdown ---


def test_card_markdown_full_document(board_db):
    cid = _full_card(board_db)
    card = service.get_card(board_db, cid)
    card["comments"] = service.get_comments(board_db, cid)

    doc = export.card_markdown(card)

    assert doc.startswith("# Ship the exporter\n")
    assert f"- **Card:** #{cid}" in doc
    assert f"- **Project:** {TEST_PROJECT}" in doc
    assert "- **Status:** Refined" in doc
    assert "- **Priority:** high" in doc
    assert "- **Tags:** tui" in doc
    # Stored markdown round-trips verbatim.
    assert "A **bold** plan.\n\n- step one\n- step two" in doc
    assert "## Acceptance criteria\n\n- it exports\n- it round-trips" in doc
    assert "- **PR:** https://example.com/pr/1" in doc
    # Comments: attribution line, multi-line body as a blockquote.
    assert "**claude** —" in doc
    assert "> first\n> second" in doc


def test_card_markdown_omits_empty_sections(board_db):
    cid = service.add_card(board_db, project=TEST_PROJECT, title="Bare")
    card = service.get_card(board_db, cid)

    doc = export.card_markdown(card)

    for heading in (
        "## Description",
        "## Acceptance criteria",
        "## Completion summary",
        "## References",
        "## Comments",
        "- **Tags:**",
        "- **Completed:**",
    ):
        assert heading not in doc


def test_card_markdown_completed_card(board_db):
    cid = service.add_card(board_db, project=TEST_PROJECT, title="Done deal")
    service.complete_card(board_db, cid, summary="shipped it")
    card = service.get_card(board_db, cid)

    doc = export.card_markdown(card)

    assert "- **Status:** Done" in doc
    assert "- **Completed:**" in doc
    assert "## Completion summary\n\nshipped it" in doc


def test_card_markdown_heading_level(board_db):
    cid = _full_card(board_db)
    card = service.get_card(board_db, cid)

    doc = export.card_markdown(card, level=3)

    assert doc.startswith("### Ship the exporter")
    assert "#### Description" in doc


# --- board_markdown ---


def test_board_markdown_groups_by_column(board_db):
    service.add_card(board_db, project=TEST_PROJECT, title="In backlog")
    cid = service.add_card(board_db, project=TEST_PROJECT, title="Refined card")
    service.refine_card(board_db, cid)
    cards = service.list_cards(board_db, project=TEST_PROJECT)

    doc = export.board_markdown(cards, project=TEST_PROJECT)

    assert doc.startswith(f"# Board export — {TEST_PROJECT}")
    assert "## Backlog (1)" in doc
    assert "## Refined (1)" in doc
    assert "### In backlog" in doc
    assert doc.index("## Backlog (1)") < doc.index("## Refined (1)")


def test_board_markdown_all_projects_title():
    assert export.board_markdown([]).startswith("# Board export — all projects")


def test_board_markdown_empty():
    assert "No cards." in export.board_markdown([], project=TEST_PROJECT)


# --- export_card / export_board ---


def test_export_card_json_matches_show_shape(board_db):
    cid = _full_card(board_db)

    data = json.loads(export.export_card(board_db, cid, fmt="json"))

    expected = service.get_card(board_db, cid)
    expected["comments"] = service.get_comments(board_db, cid)
    assert data == expected
    assert data["tags"] == ["tui"]
    assert data["references"][0]["label"] == "PR"
    assert data["comments"][0]["author"] == "claude"


def test_export_card_unknown_id_raises(board_db):
    with pytest.raises(service.CardNotFound):
        export.export_card(board_db, 999)


def test_export_unknown_format_raises(board_db):
    cid = _full_card(board_db)
    with pytest.raises(ValueError):
        export.export_card(board_db, cid, fmt="yaml")
    with pytest.raises(ValueError):
        export.export_board(board_db, fmt="yaml")


def test_export_board_json_is_array_with_comments(board_db):
    _full_card(board_db)
    service.add_card(board_db, project="other", title="Elsewhere")

    data = json.loads(export.export_board(board_db, fmt="json", project=TEST_PROJECT))

    assert [c["title"] for c in data] == ["Ship the exporter"]
    assert data[0]["comments"][0]["body"] == "first\nsecond line"


def test_export_board_filters(board_db):
    backlog = service.add_card(board_db, project=TEST_PROJECT, title="Stays put")
    refined = service.add_card(board_db, project=TEST_PROJECT, title="Moves on")
    service.refine_card(board_db, refined)
    hidden = service.add_card(board_db, project=TEST_PROJECT, title="Out of sight")
    service.archive_card(board_db, hidden)

    by_status = json.loads(
        export.export_board(
            board_db, fmt="json", project=TEST_PROJECT, statuses=[BACKLOG]
        )
    )
    assert [c["id"] for c in by_status] == [backlog]

    default = json.loads(
        export.export_board(board_db, fmt="json", project=TEST_PROJECT)
    )
    assert hidden not in [c["id"] for c in default]

    with_archived = json.loads(
        export.export_board(
            board_db, fmt="json", project=TEST_PROJECT, include_archived=True
        )
    )
    assert hidden in [c["id"] for c in with_archived]

    searched = json.loads(
        export.export_board(board_db, fmt="json", project=TEST_PROJECT, search="moves")
    )
    assert [c["id"] for c in searched] == [refined]


def test_export_board_archived_in_markdown(board_db):
    cid = service.add_card(board_db, project=TEST_PROJECT, title="Old news")
    service.archive_card(board_db, cid)

    doc = export.export_board(board_db, project=TEST_PROJECT, include_archived=True)

    assert "## Archived (1)" in doc
    assert ARCHIVED not in export.export_board(board_db, project=TEST_PROJECT)


# --- cmd_export ---


def test_cmd_export_card_markdown(mock_conn, capsys):
    cid = _full_card(mock_conn)
    from mait_code.tools.board.cli import cmd_export

    cmd_export(_ns(id=cid))

    out = capsys.readouterr().out
    assert out.startswith("# Ship the exporter")
    assert "A **bold** plan." in out


def test_cmd_export_card_json(mock_conn, capsys):
    cid = _full_card(mock_conn)
    from mait_code.tools.board.cli import cmd_export

    cmd_export(_ns(id=cid, format="json"))

    data = json.loads(capsys.readouterr().out)
    assert data["id"] == cid
    assert data["comments"][0]["author"] == "claude"


def test_cmd_export_board_scoped_to_project(mock_conn, capsys):
    _full_card(mock_conn)
    service.add_card(mock_conn, project="other", title="Elsewhere")
    from mait_code.tools.board.cli import cmd_export

    cmd_export(_ns(format="json"))
    assert [c["title"] for c in json.loads(capsys.readouterr().out)] == [
        "Ship the exporter"
    ]

    cmd_export(_ns(format="json", all=True))
    titles = [c["title"] for c in json.loads(capsys.readouterr().out)]
    assert "Elsewhere" in titles


def test_cmd_export_board_status_filter(mock_conn, capsys):
    cid = _full_card(mock_conn)
    service.add_card(mock_conn, project=TEST_PROJECT, title="Still raw")
    from mait_code.tools.board.cli import cmd_export

    cmd_export(_ns(format="json", status=REFINED))

    assert [c["id"] for c in json.loads(capsys.readouterr().out)] == [cid]


def test_cmd_export_out_writes_file(mock_conn, capsys, tmp_path):
    cid = _full_card(mock_conn)
    from mait_code.tools.board.cli import cmd_export

    target = tmp_path / "card.md"
    cmd_export(_ns(id=cid, out=str(target)))

    assert f"Exported to {target}" in capsys.readouterr().out
    content = target.read_text(encoding="utf-8")
    assert content.startswith("# Ship the exporter")
    assert content.endswith("\n")


def test_cmd_export_out_expands_tilde(mock_conn, capsys, tmp_path, monkeypatch):
    cid = _full_card(mock_conn)
    monkeypatch.setenv("HOME", str(tmp_path))
    from mait_code.tools.board.cli import cmd_export

    cmd_export(_ns(id=cid, out="~/card.md"))

    capsys.readouterr()
    assert (tmp_path / "card.md").exists()


def test_cmd_export_missing_card_exits(mock_conn):
    from mait_code.tools.board.cli import cmd_export

    with pytest.raises(SystemExit):
        cmd_export(_ns(id=999))


def test_cmd_export_empty_board_message(mock_conn, capsys):
    from mait_code.tools.board.cli import cmd_export

    cmd_export(_ns())

    assert "No cards." in capsys.readouterr().out
