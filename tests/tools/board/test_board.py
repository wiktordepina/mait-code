"""Tests for the board tool — migrations, CLI commands, and DB operations."""

import argparse
import json
import sqlite3

import pytest

from mait_code.tools.board.cli import _now
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    DONE,
    IN_PROGRESS,
    REFINED,
)
from mait_code.tools.board.migrate import ensure_schema

from tests.tools.board.conftest import TEST_PROJECT


# --- Migration tests ---


def test_ensure_schema_creates_tables(board_db: sqlite3.Connection):
    tables = board_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "cards" in names
    assert "card_comments" in names
    assert "card_tags" in names
    assert "card_references" in names
    assert "schema_version" in names


def test_ensure_schema_idempotent(board_db: sqlite3.Connection):
    ensure_schema(board_db)
    ensure_schema(board_db)
    versions = board_db.execute("SELECT version FROM schema_version").fetchall()
    assert len(versions) == 3
    assert versions[-1][0] == 3


def test_migration_blocked_becomes_refined_with_tag(tmp_path):
    """Migration #2 tags legacy blocked cards and moves them to refined."""
    from mait_code.tools.board.migrate import MIGRATIONS

    # Build a v1 database by applying only migration #1, then stamping the
    # schema at version 1 — the state a pre-tags board would be in on disk.
    conn = sqlite3.connect(tmp_path / "v1.db")
    conn.execute("PRAGMA foreign_keys = ON")
    for sql in MIGRATIONS[0][2]:
        conn.execute(sql)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
        "applied_at DATETIME DEFAULT CURRENT_TIMESTAMP, description TEXT)"
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    # 'blocked' as a *status* is the legacy v1 shape the migration fixes up.
    cid = _insert_card(conn, "stuck", status="blocked")
    conn.commit()

    ensure_schema(conn)

    status = conn.execute("SELECT status FROM cards WHERE id = ?", (cid,)).fetchone()[0]
    tags = [
        r[0]
        for r in conn.execute(
            "SELECT tag FROM card_tags WHERE card_id = ?", (cid,)
        ).fetchall()
    ]
    conn.close()
    assert status == REFINED
    assert tags == [BLOCKED_TAG]


def test_cards_columns(board_db: sqlite3.Connection):
    columns = board_db.execute("PRAGMA table_info(cards)").fetchall()
    col_names = [c[1] for c in columns]
    assert col_names == [
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
    ]


def test_fk_cascade_deletes_comments(board_db: sqlite3.Connection):
    cid = _insert_card(board_db, "with comments")
    board_db.execute(
        "INSERT INTO card_comments (card_id, author, body, created_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, "me", "a note", _now().isoformat()),
    )
    board_db.commit()
    board_db.execute("DELETE FROM cards WHERE id = ?", (cid,))
    board_db.commit()
    remaining = board_db.execute(
        "SELECT COUNT(*) FROM card_comments WHERE card_id = ?", (cid,)
    ).fetchone()[0]
    assert remaining == 0


def test_any_project_accepted(board_db: sqlite3.Connection):
    _insert_card(board_db, "free-form", project="some-idea-no-repo")
    row = board_db.execute(
        "SELECT project FROM cards WHERE title = 'free-form'"
    ).fetchone()
    assert row[0] == "some-idea-no-repo"


# --- Helpers ---


def _insert_card(
    conn,
    title,
    status=BACKLOG,
    priority="medium",
    project=TEST_PROJECT,
    description=None,
    acceptance=None,
    created_at=None,
):
    now = _now().isoformat()
    conn.execute(
        "INSERT INTO cards (project, title, description, acceptance_criteria, "
        "status, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project,
            title,
            description,
            acceptance,
            status,
            priority,
            created_at or now,
            now,
        ),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


# --- add ---


def test_cmd_add(mock_conn, capsys):
    from mait_code.tools.board.cli import cmd_add

    cmd_add(
        _ns(title=["Fix", "login"], description=None, priority="medium", project=None)
    )
    rows = mock_conn.execute(
        "SELECT title, status, priority, project FROM cards"
    ).fetchall()
    assert rows[0] == ("Fix login", BACKLOG, "medium", TEST_PROJECT)
    assert "Fix login" in capsys.readouterr().out


def test_cmd_add_priority_and_description(mock_conn):
    from mait_code.tools.board.cli import cmd_add

    cmd_add(_ns(title=["Card"], description="details", priority="high", project=None))
    row = mock_conn.execute("SELECT priority, description FROM cards").fetchone()
    assert row == ("high", "details")


def test_cmd_add_project_override(mock_conn):
    from mait_code.tools.board.cli import cmd_add

    cmd_add(
        _ns(title=["Idea"], description=None, priority="medium", project="app-idea")
    )
    row = mock_conn.execute("SELECT project FROM cards").fetchone()
    assert row[0] == "app-idea"


def test_cmd_add_empty_title(mock_conn):
    from mait_code.tools.board.cli import cmd_add

    with pytest.raises(SystemExit):
        cmd_add(_ns(title=["   "], description=None, priority="medium", project=None))


# --- list ---


def test_cmd_list_project_scoped(mock_conn, capsys):
    _insert_card(mock_conn, "mine", project=TEST_PROJECT)
    _insert_card(mock_conn, "theirs", project="other")
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search=None))
    out = capsys.readouterr().out
    assert "mine" in out
    assert "theirs" not in out


def test_cmd_list_excludes_archived_by_default(mock_conn, capsys):
    _insert_card(mock_conn, "live")
    _insert_card(mock_conn, "old", status=ARCHIVED)
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search=None))
    out = capsys.readouterr().out
    assert "live" in out
    assert "old" not in out


def test_cmd_list_archived_flag(mock_conn, capsys):
    _insert_card(mock_conn, "old", status=ARCHIVED)
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=True, json=False, search=None))
    assert "old" in capsys.readouterr().out


def test_cmd_list_all_projects(mock_conn, capsys):
    _insert_card(mock_conn, "a", project="proj-a")
    _insert_card(mock_conn, "b", project="proj-b")
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=True, status=None, archived=False, json=False, search=None))
    out = capsys.readouterr().out
    assert "a" in out and "b" in out
    assert "[proj-a]" in out and "[proj-b]" in out


def test_cmd_list_priority_order(mock_conn, capsys):
    _insert_card(mock_conn, "low one", priority="low")
    _insert_card(mock_conn, "high one", priority="high")
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search=None))
    out = capsys.readouterr().out
    assert out.index("high one") < out.index("low one")


def test_cmd_list_grouped_headers(mock_conn, capsys):
    _insert_card(mock_conn, "b1", status=BACKLOG)
    _insert_card(mock_conn, "r1", status=REFINED)
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search=None))
    out = capsys.readouterr().out
    assert "Backlog (1):" in out
    assert "Refined (1):" in out


def test_cmd_list_json(mock_conn, capsys):
    _insert_card(mock_conn, "j1")
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=True, search=None))
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["title"] == "j1"


def test_cmd_list_empty(mock_conn, capsys):
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search=None))
    assert "No cards" in capsys.readouterr().out


def test_cmd_list_search_filters_by_title(mock_conn, capsys):
    _insert_card(mock_conn, "board tui polish")
    _insert_card(mock_conn, "memory backlinks")
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search="TUI"))
    out = capsys.readouterr().out
    assert "board tui polish" in out
    assert "memory backlinks" not in out


def test_cmd_list_search_no_match(mock_conn, capsys):
    _insert_card(mock_conn, "alpha")
    from mait_code.tools.board.cli import cmd_list

    cmd_list(_ns(all=False, status=None, archived=False, json=False, search="zzz"))
    assert "No cards" in capsys.readouterr().out


# --- show ---


def test_cmd_show(mock_conn, capsys):
    cid = _insert_card(mock_conn, "showme", description="d", acceptance="ac")
    mock_conn.execute(
        "INSERT INTO card_comments (card_id, author, body, created_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, "claude", "a comment", _now().isoformat()),
    )
    mock_conn.commit()
    from mait_code.tools.board.cli import cmd_show

    cmd_show(_ns(id=cid, json=False))
    out = capsys.readouterr().out
    assert "showme" in out
    assert "a comment" in out
    assert "ac" in out


def test_cmd_show_json(mock_conn, capsys):
    cid = _insert_card(mock_conn, "j")
    mock_conn.execute(
        "INSERT INTO card_comments (card_id, author, body, created_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, "me", "note", _now().isoformat()),
    )
    mock_conn.commit()
    from mait_code.tools.board.cli import cmd_show

    cmd_show(_ns(id=cid, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["title"] == "j"
    assert data["comments"][0]["body"] == "note"


def test_cmd_show_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_show

    with pytest.raises(SystemExit):
        cmd_show(_ns(id=999, json=False))


# --- move ---


def test_cmd_move(mock_conn):
    cid = _insert_card(mock_conn, "m")
    from mait_code.tools.board.cli import cmd_move

    cmd_move(_ns(id=cid, status=IN_PROGRESS))
    row = mock_conn.execute("SELECT status FROM cards WHERE id = ?", (cid,)).fetchone()
    assert row[0] == IN_PROGRESS


def test_cmd_move_to_done_sets_completed_at(mock_conn):
    cid = _insert_card(mock_conn, "m")
    from mait_code.tools.board.cli import cmd_move

    cmd_move(_ns(id=cid, status=DONE))
    row = mock_conn.execute(
        "SELECT status, completed_at FROM cards WHERE id = ?", (cid,)
    ).fetchone()
    assert row[0] == DONE
    assert row[1] is not None


def test_cmd_move_out_of_done_clears_completed_at(mock_conn):
    cid = _insert_card(mock_conn, "m", status=DONE)
    mock_conn.execute(
        "UPDATE cards SET completed_at = ? WHERE id = ?", (_now().isoformat(), cid)
    )
    mock_conn.commit()
    from mait_code.tools.board.cli import cmd_move

    cmd_move(_ns(id=cid, status=BACKLOG))
    row = mock_conn.execute(
        "SELECT status, completed_at FROM cards WHERE id = ?", (cid,)
    ).fetchone()
    assert row[0] == BACKLOG
    assert row[1] is None


def test_cmd_move_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_move

    with pytest.raises(SystemExit):
        cmd_move(_ns(id=999, status=DONE))


# --- refine ---


def test_cmd_refine(mock_conn):
    cid = _insert_card(mock_conn, "r")
    from mait_code.tools.board.cli import cmd_refine

    cmd_refine(_ns(id=cid, description="why", acceptance="done when X"))
    row = mock_conn.execute(
        "SELECT status, description, acceptance_criteria FROM cards WHERE id = ?",
        (cid,),
    ).fetchone()
    assert row == (REFINED, "why", "done when X")


def test_cmd_refine_warns_without_acceptance(mock_conn, capsys):
    cid = _insert_card(mock_conn, "r")
    from mait_code.tools.board.cli import cmd_refine

    cmd_refine(_ns(id=cid, description="why", acceptance=None))
    assert "no acceptance criteria" in capsys.readouterr().err


# --- next ---


def test_cmd_next_top_priority(mock_conn, capsys):
    _insert_card(mock_conn, "low", status=REFINED, priority="low")
    _insert_card(mock_conn, "high", status=REFINED, priority="high")
    from mait_code.tools.board.cli import cmd_next

    cmd_next(_ns(project=None, claim=False, json=False))
    assert "high" in capsys.readouterr().out


def test_cmd_next_oldest_within_priority(mock_conn, capsys):
    _insert_card(mock_conn, "newer", status=REFINED, created_at="2026-05-02T00:00:00Z")
    _insert_card(mock_conn, "older", status=REFINED, created_at="2026-05-01T00:00:00Z")
    from mait_code.tools.board.cli import cmd_next

    cmd_next(_ns(project=None, claim=False, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["title"] == "older"


def test_cmd_next_claim_moves_to_in_progress(mock_conn):
    cid = _insert_card(mock_conn, "pick", status=REFINED)
    from mait_code.tools.board.cli import cmd_next

    cmd_next(_ns(project=None, claim=True, json=True))
    row = mock_conn.execute("SELECT status FROM cards WHERE id = ?", (cid,)).fetchone()
    assert row[0] == IN_PROGRESS


def test_cmd_next_ignores_non_refined(mock_conn, capsys):
    _insert_card(mock_conn, "backlogged", status=BACKLOG)
    from mait_code.tools.board.cli import cmd_next

    cmd_next(_ns(project=None, claim=False, json=False))
    assert "No refined cards" in capsys.readouterr().out


def test_cmd_next_empty_json(mock_conn, capsys):
    from mait_code.tools.board.cli import cmd_next

    cmd_next(_ns(project=None, claim=False, json=True))
    assert capsys.readouterr().out.strip() == "null"


def test_cmd_next_project_scoped(mock_conn, capsys):
    _insert_card(mock_conn, "other-refined", status=REFINED, project="other")
    from mait_code.tools.board.cli import cmd_next

    cmd_next(_ns(project=None, claim=False, json=False))
    assert "No refined cards" in capsys.readouterr().out


# --- complete ---


def test_cmd_complete(mock_conn, capsys):
    cid = _insert_card(mock_conn, "c", status=IN_PROGRESS)
    from mait_code.tools.board.cli import cmd_complete

    cmd_complete(_ns(id=cid, summary=["shipped", "it"]))
    row = mock_conn.execute(
        "SELECT status, completion_summary, completed_at FROM cards WHERE id = ?",
        (cid,),
    ).fetchone()
    assert row[0] == DONE
    assert row[1] == "shipped it"
    assert row[2] is not None
    assert "completed" in capsys.readouterr().out


def test_cmd_complete_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_complete

    with pytest.raises(SystemExit):
        cmd_complete(_ns(id=999, summary=[]))


# --- block / unblock / archive ---


def test_cmd_block(mock_conn):
    cid = _insert_card(mock_conn, "b", status=IN_PROGRESS)
    from mait_code.tools.board.cli import cmd_block

    cmd_block(_ns(id=cid, reason=[]))
    # Blocking tags the card in place; its status is untouched.
    status = mock_conn.execute(
        "SELECT status FROM cards WHERE id = ?", (cid,)
    ).fetchone()[0]
    tag = mock_conn.execute(
        "SELECT tag FROM card_tags WHERE card_id = ?", (cid,)
    ).fetchone()
    assert status == IN_PROGRESS
    assert tag[0] == BLOCKED_TAG


def test_cmd_block_records_reason_as_comment(mock_conn):
    cid = _insert_card(mock_conn, "b")
    from mait_code.tools.board.cli import cmd_block

    cmd_block(_ns(id=cid, reason=["need", "a", "decision"]))
    row = mock_conn.execute(
        "SELECT body FROM card_comments WHERE card_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "Blocked: need a decision"


def test_cmd_unblock(mock_conn):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_unblock

    cid = _insert_card(mock_conn, "u", status=IN_PROGRESS)
    service.block_card(mock_conn, cid)
    cmd_unblock(_ns(id=cid))
    # Tag removed; flow position preserved.
    status = mock_conn.execute(
        "SELECT status FROM cards WHERE id = ?", (cid,)
    ).fetchone()[0]
    remaining = mock_conn.execute(
        "SELECT COUNT(*) FROM card_tags WHERE card_id = ? AND tag = ?",
        (cid, BLOCKED_TAG),
    ).fetchone()[0]
    assert status == IN_PROGRESS
    assert remaining == 0


def test_cmd_tag(mock_conn):
    cid = _insert_card(mock_conn, "t")
    from mait_code.tools.board.cli import cmd_tag

    cmd_tag(_ns(id=cid, tag="urgent"))
    row = mock_conn.execute(
        "SELECT tag FROM card_tags WHERE card_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "urgent"


def test_cmd_tag_empty(mock_conn):
    cid = _insert_card(mock_conn, "t")
    from mait_code.tools.board.cli import cmd_tag

    with pytest.raises(SystemExit):
        cmd_tag(_ns(id=cid, tag="   "))


def test_cmd_tag_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_tag

    with pytest.raises(SystemExit):
        cmd_tag(_ns(id=999, tag="urgent"))


def test_cmd_untag(mock_conn):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_untag

    cid = _insert_card(mock_conn, "t")
    service.add_tag(mock_conn, cid, "urgent")
    cmd_untag(_ns(id=cid, tag="urgent"))
    remaining = mock_conn.execute(
        "SELECT COUNT(*) FROM card_tags WHERE card_id = ?", (cid,)
    ).fetchone()[0]
    assert remaining == 0


def test_cmd_show_renders_tags(mock_conn, capsys):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_show

    cid = _insert_card(mock_conn, "t")
    service.add_tag(mock_conn, cid, "urgent")
    cmd_show(_ns(id=cid, json=False))
    assert "tags: urgent" in capsys.readouterr().out


def test_cmd_list_renders_tags(mock_conn, capsys):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_list

    cid = _insert_card(mock_conn, "t", status=REFINED)
    service.add_tag(mock_conn, cid, "urgent")
    cmd_list(_ns(all=False, status=None, archived=False, json=False, search=None))
    assert "#urgent" in capsys.readouterr().out


# --- references ---


def test_add_and_list_references_preserve_order(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    service.add_reference(board_db, cid, "JIRA", "WIKTOR-1")
    service.add_reference(board_db, cid, "PR", "https://example.com/pr/1")
    refs = service.list_references(board_db, cid)
    assert refs == [
        {"label": "JIRA", "value": "WIKTOR-1"},
        {"label": "PR", "value": "https://example.com/pr/1"},
    ]


def test_remove_reference_by_display_position(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    for label_, value in [("a", "1"), ("b", "2"), ("c", "3")]:
        service.add_reference(board_db, cid, label_, value)
    # Remove the middle one; the third should slide up to position 2.
    assert service.remove_reference(board_db, cid, 2) is True
    refs = service.list_references(board_db, cid)
    assert [r["label"] for r in refs] == ["a", "c"]
    # The new position 2 ('c') removes cleanly — no stale-position gap.
    assert service.remove_reference(board_db, cid, 2) is True
    assert [r["label"] for r in service.list_references(board_db, cid)] == ["a"]


def test_remove_reference_out_of_range_returns_false(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    service.add_reference(board_db, cid, "a", "1")
    assert service.remove_reference(board_db, cid, 5) is False
    assert service.remove_reference(board_db, cid, 0) is False
    assert len(service.list_references(board_db, cid)) == 1


def test_set_references_replaces_and_renumbers(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    service.add_reference(board_db, cid, "old", "0")
    service.set_references(
        board_db,
        cid,
        [{"label": "PR", "value": "p"}, {"label": "JIRA", "value": "j"}],
    )
    refs = service.list_references(board_db, cid)
    assert refs == [
        {"label": "PR", "value": "p"},
        {"label": "JIRA", "value": "j"},
    ]
    # Positions renumber from 1, so display-order removal stays stable.
    assert service.remove_reference(board_db, cid, 1) is True
    assert [r["label"] for r in service.list_references(board_db, cid)] == ["JIRA"]


def test_set_references_to_empty_clears(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    service.add_reference(board_db, cid, "gone", "x")
    service.set_references(board_db, cid, [])
    assert service.list_references(board_db, cid) == []


def test_add_reference_card_not_found(board_db):
    from mait_code.tools.board import service

    with pytest.raises(service.CardNotFound):
        service.add_reference(board_db, 999, "a", "1")


def test_references_cascade_on_card_delete(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    service.add_reference(board_db, cid, "a", "1")
    board_db.execute("DELETE FROM cards WHERE id = ?", (cid,))
    board_db.commit()
    remaining = board_db.execute(
        "SELECT COUNT(*) FROM card_references WHERE card_id = ?", (cid,)
    ).fetchone()[0]
    assert remaining == 0


def test_get_card_attaches_references(board_db):
    from mait_code.tools.board import service

    cid = _insert_card(board_db, "r")
    service.add_reference(board_db, cid, "PR", "https://example.com")
    card = service.get_card(board_db, cid)
    assert card["references"] == [{"label": "PR", "value": "https://example.com"}]


def test_list_cards_attaches_empty_references(board_db):
    from mait_code.tools.board import service

    _insert_card(board_db, "r")
    cards = service.list_cards(board_db)
    assert cards[0]["references"] == []


def test_cmd_ref_add(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_add

    cid = _insert_card(mock_conn, "r")
    cmd_ref_add(_ns(id=cid, label="PR", value=["https://example.com/x"]))
    row = mock_conn.execute(
        "SELECT label, value FROM card_references WHERE card_id = ?", (cid,)
    ).fetchone()
    assert row == ("PR", "https://example.com/x")


def test_cmd_ref_add_joins_multiword_value(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_add

    cid = _insert_card(mock_conn, "r")
    cmd_ref_add(_ns(id=cid, label="Note", value=["see", "the", "plan"]))
    row = mock_conn.execute(
        "SELECT value FROM card_references WHERE card_id = ?", (cid,)
    ).fetchone()
    assert row[0] == "see the plan"


def test_cmd_ref_add_empty_label_or_value(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_add

    cid = _insert_card(mock_conn, "r")
    with pytest.raises(SystemExit):
        cmd_ref_add(_ns(id=cid, label="   ", value=["v"]))
    with pytest.raises(SystemExit):
        cmd_ref_add(_ns(id=cid, label="L", value=["   "]))


def test_cmd_ref_add_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_add

    with pytest.raises(SystemExit):
        cmd_ref_add(_ns(id=999, label="PR", value=["v"]))


def test_cmd_ref_remove(mock_conn):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_ref_remove

    cid = _insert_card(mock_conn, "r")
    service.add_reference(mock_conn, cid, "a", "1")
    cmd_ref_remove(_ns(id=cid, position=1))
    assert service.list_references(mock_conn, cid) == []


def test_cmd_ref_remove_out_of_range_exits(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_remove

    cid = _insert_card(mock_conn, "r")
    with pytest.raises(SystemExit):
        cmd_ref_remove(_ns(id=cid, position=3))


def test_cmd_ref_list(mock_conn, capsys):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_ref_list

    cid = _insert_card(mock_conn, "r")
    service.add_reference(mock_conn, cid, "JIRA", "WIKTOR-9")
    cmd_ref_list(_ns(id=cid, json=False))
    out = capsys.readouterr().out
    assert "1. JIRA: WIKTOR-9" in out


def test_cmd_ref_list_json(mock_conn, capsys):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_ref_list

    cid = _insert_card(mock_conn, "r")
    service.add_reference(mock_conn, cid, "PR", "https://example.com")
    cmd_ref_list(_ns(id=cid, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data == [{"label": "PR", "value": "https://example.com"}]


def test_cmd_show_renders_references(mock_conn, capsys):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_show

    cid = _insert_card(mock_conn, "r")
    service.add_reference(mock_conn, cid, "JIRA", "WIKTOR-9")
    cmd_show(_ns(id=cid, json=False))
    out = capsys.readouterr().out
    assert "References (1):" in out
    assert "1. JIRA: WIKTOR-9" in out


def test_cmd_show_json_includes_references(mock_conn, capsys):
    from mait_code.tools.board import service
    from mait_code.tools.board.cli import cmd_show

    cid = _insert_card(mock_conn, "r")
    service.add_reference(mock_conn, cid, "PR", "https://example.com")
    cmd_show(_ns(id=cid, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["references"] == [{"label": "PR", "value": "https://example.com"}]


def test_cmd_archive_then_excluded_from_next(mock_conn, capsys):
    cid = _insert_card(mock_conn, "a", status=REFINED)
    from mait_code.tools.board.cli import cmd_archive, cmd_next

    cmd_archive(_ns(id=cid))
    row = mock_conn.execute("SELECT status FROM cards WHERE id = ?", (cid,)).fetchone()
    assert row[0] == ARCHIVED
    cmd_next(_ns(project=None, claim=False, json=False))
    assert "No refined cards" in capsys.readouterr().out


# --- comment / edit / remove ---


def test_cmd_comment(mock_conn):
    cid = _insert_card(mock_conn, "c")
    from mait_code.tools.board.cli import cmd_comment

    cmd_comment(_ns(id=cid, body=["looks", "good"], author="claude"))
    row = mock_conn.execute(
        "SELECT author, body FROM card_comments WHERE card_id = ?", (cid,)
    ).fetchone()
    assert row == ("claude", "looks good")


def test_cmd_comment_empty(mock_conn):
    cid = _insert_card(mock_conn, "c")
    from mait_code.tools.board.cli import cmd_comment

    with pytest.raises(SystemExit):
        cmd_comment(_ns(id=cid, body=["  "], author="me"))


def test_cmd_edit(mock_conn):
    cid = _insert_card(mock_conn, "old title")
    from mait_code.tools.board.cli import cmd_edit

    cmd_edit(
        _ns(
            id=cid,
            title="new title",
            description=None,
            priority="high",
            acceptance=None,
        )
    )
    row = mock_conn.execute(
        "SELECT title, priority FROM cards WHERE id = ?", (cid,)
    ).fetchone()
    assert row == ("new title", "high")


def test_cmd_edit_no_fields(mock_conn):
    cid = _insert_card(mock_conn, "c")
    from mait_code.tools.board.cli import cmd_edit

    with pytest.raises(SystemExit):
        cmd_edit(
            _ns(id=cid, title=None, description=None, priority=None, acceptance=None)
        )


def test_cmd_remove_cascades(mock_conn):
    cid = _insert_card(mock_conn, "r")
    mock_conn.execute(
        "INSERT INTO card_comments (card_id, author, body, created_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, "me", "x", _now().isoformat()),
    )
    mock_conn.commit()
    from mait_code.tools.board.cli import cmd_remove

    cmd_remove(_ns(id=cid))
    assert (
        mock_conn.execute("SELECT id FROM cards WHERE id = ?", (cid,)).fetchone()
        is None
    )
    assert (
        mock_conn.execute(
            "SELECT COUNT(*) FROM card_comments WHERE card_id = ?", (cid,)
        ).fetchone()[0]
        == 0
    )


def test_cmd_remove_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_remove

    with pytest.raises(SystemExit):
        cmd_remove(_ns(id=999))


# --- summary ---


def test_cmd_summary_counts(mock_conn, capsys):
    _insert_card(mock_conn, "b", status=BACKLOG)
    _insert_card(mock_conn, "r", status=REFINED)
    _insert_card(mock_conn, "r2", status=REFINED)
    from mait_code.tools.board.cli import cmd_summary

    cmd_summary(_ns(all=False, project=None, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["counts"][REFINED] == 2
    assert data["counts"][BACKLOG] == 1
    assert data["project"] == TEST_PROJECT


def test_cmd_summary_excludes_archived(mock_conn, capsys):
    _insert_card(mock_conn, "old", status=ARCHIVED)
    from mait_code.tools.board.cli import cmd_summary

    cmd_summary(_ns(all=False, project=None, json=False))
    assert "No cards" in capsys.readouterr().out


def test_cmd_summary_all_projects(mock_conn, capsys):
    _insert_card(mock_conn, "a", status=REFINED, project="proj-a")
    _insert_card(mock_conn, "b", status=DONE, project="proj-b")
    from mait_code.tools.board.cli import cmd_summary

    cmd_summary(_ns(all=True, project=None, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["project"] is None
    assert data["counts"][REFINED] == 1
    assert data["counts"][DONE] == 1
