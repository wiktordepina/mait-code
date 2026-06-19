"""Tests for the board CLI's thin layer — not-found branches, residual text-output
paths, and ``main()`` argparse dispatch.

The bulk of the per-handler behaviour lives in ``test_board.py`` and
``test_export.py``; this module fills the gaps those leave: every
``CardNotFound``-to-``exit(1)`` handler branch, the presentation branches that
only fire with richer card state, and the ``main()`` dispatcher itself (driven
through ``sys.argv`` so the parser is exercised end to end).
"""

import argparse
import json

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.cli import _now
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    DONE,
    IN_PROGRESS,
    REFINED,
)

from tests.tools.board.conftest import TEST_PROJECT


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
    """Insert a card directly and return its id (mirrors test_board.py's helper)."""
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
    """A Namespace with ``--json`` defaulted off (every subparser defines it)."""
    kwargs.setdefault("json", False)
    return argparse.Namespace(**kwargs)


# --- not-found → exit(1) on the mutating handlers ---
#
# Each of these handlers catches CardNotFound and routes through _not_found,
# which prints to stderr and exits 1. The happy paths are covered elsewhere;
# this batch pins the error branch on every handler that has one.


def test_cmd_refine_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_refine

    with pytest.raises(SystemExit):
        cmd_refine(_ns(id=999, description="d", acceptance="a"))


def test_cmd_comment_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_comment

    with pytest.raises(SystemExit):
        cmd_comment(_ns(id=999, body=["hi"], author="me"))


def test_cmd_block_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_block

    with pytest.raises(SystemExit):
        cmd_block(_ns(id=999, reason=[]))


def test_cmd_unblock_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_unblock

    with pytest.raises(SystemExit):
        cmd_unblock(_ns(id=999))


def test_cmd_untag_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_untag

    with pytest.raises(SystemExit):
        cmd_untag(_ns(id=999, tag="urgent"))


def test_cmd_ref_remove_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_remove

    with pytest.raises(SystemExit):
        cmd_ref_remove(_ns(id=999, position=1))


def test_cmd_ref_list_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_ref_list

    with pytest.raises(SystemExit):
        cmd_ref_list(_ns(id=999))


def test_cmd_archive_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_archive

    with pytest.raises(SystemExit):
        cmd_archive(_ns(id=999))


def test_cmd_edit_not_found(mock_conn):
    from mait_code.tools.board.cli import cmd_edit

    with pytest.raises(SystemExit):
        cmd_edit(
            _ns(id=999, title="x", description=None, priority=None, acceptance=None)
        )


# --- residual presentation branches ---


def test_cmd_edit_sets_description_and_acceptance(mock_conn):
    # Exercises the description/acceptance field-collection branches that the
    # title/priority-only edit tests don't reach.
    from mait_code.tools.board.cli import cmd_edit

    cid = _insert_card(mock_conn, "c")
    cmd_edit(
        _ns(
            id=cid,
            title=None,
            description="new desc",
            priority=None,
            acceptance="done when X",
        )
    )
    row = mock_conn.execute(
        "SELECT description, acceptance_criteria FROM cards WHERE id = ?", (cid,)
    ).fetchone()
    assert row == ("new desc", "done when X")


def test_cmd_show_renders_completion_summary(mock_conn, capsys):
    # The completion-summary block only prints for a completed card.
    from mait_code.tools.board.cli import cmd_complete, cmd_show

    cid = _insert_card(mock_conn, "c", status=IN_PROGRESS)
    cmd_complete(_ns(id=cid, summary=["shipped", "it"]))
    capsys.readouterr()  # drop the complete-command output

    cmd_show(_ns(id=cid, json=False))
    out = capsys.readouterr().out
    assert "Completion summary:" in out
    assert "shipped it" in out


def test_cmd_next_prints_acceptance_criteria(mock_conn, capsys):
    # Text mode appends the acceptance criteria when the next card carries it.
    from mait_code.tools.board.cli import cmd_next

    _insert_card(mock_conn, "ready", status=REFINED, acceptance="- it works")
    cmd_next(_ns(project=None, claim=False, json=False))
    out = capsys.readouterr().out
    assert "Next: " in out
    assert "Acceptance criteria:" in out
    assert "- it works" in out


def test_cmd_ref_list_empty(mock_conn, capsys):
    from mait_code.tools.board.cli import cmd_ref_list

    cid = _insert_card(mock_conn, "r")
    cmd_ref_list(_ns(id=cid, json=False))
    assert "has no references" in capsys.readouterr().out


def test_cmd_summary_text_with_cards(mock_conn, capsys):
    # The non-empty text branch of cmd_summary (the JSON and empty paths are
    # covered in test_board.py).
    from mait_code.tools.board.cli import cmd_summary

    _insert_card(mock_conn, "b", status=BACKLOG)
    _insert_card(mock_conn, "r", status=REFINED)
    cmd_summary(_ns(all=False, project=None, json=False))
    out = capsys.readouterr().out
    assert TEST_PROJECT in out
    assert "Backlog: 1" in out
    assert "Refined: 1" in out


def test_cmd_summary_text_all_projects_header(mock_conn, capsys):
    from mait_code.tools.board.cli import cmd_summary

    _insert_card(mock_conn, "a", status=REFINED, project="proj-a")
    cmd_summary(_ns(all=True, project=None, json=False))
    assert "All projects —" in capsys.readouterr().out


# --- main() dispatch ---
#
# Driving main() through sys.argv exercises the whole argparse build and the
# func dispatch. mock_conn patches the connection + get_project, so the handlers
# run against the temp db.


def test_main_add_dispatch(mock_conn, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "add", "Fix", "the", "thing"])
    from mait_code.tools.board.cli import main

    main()
    assert "Fix the thing" in capsys.readouterr().out
    row = mock_conn.execute("SELECT title FROM cards").fetchone()
    assert row[0] == "Fix the thing"


def test_main_list_dispatch(mock_conn, capsys, monkeypatch):
    _insert_card(mock_conn, "listed card")
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "list"])
    from mait_code.tools.board.cli import main

    main()
    assert "listed card" in capsys.readouterr().out


def test_main_show_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "shown card")
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "show", str(cid)])
    from mait_code.tools.board.cli import main

    main()
    assert "shown card" in capsys.readouterr().out


def test_main_move_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "movable")
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "move", str(cid), REFINED])
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    status = mock_conn.execute(
        "SELECT status FROM cards WHERE id = ?", (cid,)
    ).fetchone()[0]
    assert status == REFINED


def test_main_refine_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "to refine")
    monkeypatch.setattr(
        "sys.argv",
        ["mc-tool-board", "refine", str(cid), "--acceptance", "done when X"],
    )
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    row = mock_conn.execute(
        "SELECT status, acceptance_criteria FROM cards WHERE id = ?", (cid,)
    ).fetchone()
    assert row == (REFINED, "done when X")


def test_main_next_dispatch(mock_conn, capsys, monkeypatch):
    _insert_card(mock_conn, "up next", status=REFINED)
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "next"])
    from mait_code.tools.board.cli import main

    main()
    assert "up next" in capsys.readouterr().out


def test_main_complete_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "finish me", status=IN_PROGRESS)
    monkeypatch.setattr(
        "sys.argv", ["mc-tool-board", "complete", str(cid), "--summary", "shipped"]
    )
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    status = mock_conn.execute(
        "SELECT status FROM cards WHERE id = ?", (cid,)
    ).fetchone()[0]
    assert status == DONE


def test_main_block_and_unblock_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "blockable", status=IN_PROGRESS)
    from mait_code.tools.board.cli import main

    monkeypatch.setattr(
        "sys.argv", ["mc-tool-board", "block", str(cid), "waiting", "on", "infra"]
    )
    main()
    capsys.readouterr()
    assert (
        mock_conn.execute(
            "SELECT COUNT(*) FROM card_tags WHERE card_id = ? AND tag = ?",
            (cid, BLOCKED_TAG),
        ).fetchone()[0]
        == 1
    )

    monkeypatch.setattr("sys.argv", ["mc-tool-board", "unblock", str(cid)])
    main()
    capsys.readouterr()
    assert (
        mock_conn.execute(
            "SELECT COUNT(*) FROM card_tags WHERE card_id = ? AND tag = ?",
            (cid, BLOCKED_TAG),
        ).fetchone()[0]
        == 0
    )


def test_main_tag_and_untag_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "taggable")
    from mait_code.tools.board.cli import main

    monkeypatch.setattr("sys.argv", ["mc-tool-board", "tag", str(cid), "urgent"])
    main()
    capsys.readouterr()
    assert (
        mock_conn.execute(
            "SELECT tag FROM card_tags WHERE card_id = ?", (cid,)
        ).fetchone()[0]
        == "urgent"
    )

    monkeypatch.setattr("sys.argv", ["mc-tool-board", "untag", str(cid), "urgent"])
    main()
    capsys.readouterr()
    assert (
        mock_conn.execute(
            "SELECT COUNT(*) FROM card_tags WHERE card_id = ?", (cid,)
        ).fetchone()[0]
        == 0
    )


def test_main_ref_add_list_remove_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "ref host")
    from mait_code.tools.board.cli import main

    monkeypatch.setattr(
        "sys.argv",
        ["mc-tool-board", "ref", "add", str(cid), "PR", "https://example.com/x"],
    )
    main()
    capsys.readouterr()
    assert service.list_references(mock_conn, cid) == [
        {"label": "PR", "value": "https://example.com/x"}
    ]

    monkeypatch.setattr(
        "sys.argv", ["mc-tool-board", "ref", "list", str(cid), "--json"]
    )
    main()
    assert json.loads(capsys.readouterr().out) == [
        {"label": "PR", "value": "https://example.com/x"}
    ]

    monkeypatch.setattr("sys.argv", ["mc-tool-board", "ref", "remove", str(cid), "1"])
    main()
    capsys.readouterr()
    assert service.list_references(mock_conn, cid) == []


def test_main_ref_requires_subcommand(monkeypatch):
    # The ref subparser is required=True, so a bare 'ref' is a usage error.
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "ref"])
    from mait_code.tools.board.cli import main

    with pytest.raises(SystemExit):
        main()


def test_main_archive_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "archivable")
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "archive", str(cid)])
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    status = mock_conn.execute(
        "SELECT status FROM cards WHERE id = ?", (cid,)
    ).fetchone()[0]
    assert status == ARCHIVED


def test_main_comment_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "commentable")
    monkeypatch.setattr(
        "sys.argv",
        ["mc-tool-board", "comment", str(cid), "--author", "claude", "looks", "good"],
    )
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    row = mock_conn.execute(
        "SELECT author, body FROM card_comments WHERE card_id = ?", (cid,)
    ).fetchone()
    assert row == ("claude", "looks good")


def test_main_edit_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "old title")
    monkeypatch.setattr(
        "sys.argv", ["mc-tool-board", "edit", str(cid), "--title", "new title"]
    )
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    title = mock_conn.execute(
        "SELECT title FROM cards WHERE id = ?", (cid,)
    ).fetchone()[0]
    assert title == "new title"


def test_main_remove_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "doomed")
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "remove", str(cid)])
    from mait_code.tools.board.cli import main

    main()
    capsys.readouterr()
    assert (
        mock_conn.execute("SELECT id FROM cards WHERE id = ?", (cid,)).fetchone()
        is None
    )


def test_main_export_dispatch(mock_conn, capsys, monkeypatch):
    cid = _insert_card(mock_conn, "exportable")
    monkeypatch.setattr(
        "sys.argv", ["mc-tool-board", "export", str(cid), "--format", "json"]
    )
    from mait_code.tools.board.cli import main

    main()
    assert json.loads(capsys.readouterr().out)["id"] == cid


def test_main_summary_dispatch(mock_conn, capsys, monkeypatch):
    _insert_card(mock_conn, "counted", status=REFINED)
    monkeypatch.setattr("sys.argv", ["mc-tool-board", "summary", "--json"])
    from mait_code.tools.board.cli import main

    main()
    data = json.loads(capsys.readouterr().out)
    assert data["counts"][REFINED] == 1


def test_main_requires_a_subcommand(monkeypatch):
    # The top-level subparser is required=True — a bare invocation is a usage error.
    monkeypatch.setattr("sys.argv", ["mc-tool-board"])
    from mait_code.tools.board.cli import main

    with pytest.raises(SystemExit):
        main()
