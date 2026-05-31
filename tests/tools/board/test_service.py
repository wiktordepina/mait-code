"""Unit tests for the board service layer.

These exercise :mod:`mait_code.tools.board.service` directly on a temp
connection — the function-level analogue of the end-to-end CLI tests in
``test_board.py``. The focus is the shared invariants the TUI relies on:
the done-stamp, ``CardNotFound`` on missing ids, ordering, and the
archived-exclusion in summaries.
"""

import sqlite3

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    DONE,
    IN_PROGRESS,
    REFINED,
)

from tests.tools.board.conftest import TEST_PROJECT


def _insert(
    conn,
    title,
    status=BACKLOG,
    priority="medium",
    project=TEST_PROJECT,
    description=None,
    acceptance=None,
    created_at=None,
):
    now = service._now()
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


# --- Queries ---


def test_list_cards_excludes_archived_by_default(board_db: sqlite3.Connection):
    _insert(board_db, "live")
    _insert(board_db, "old", status=ARCHIVED)
    titles = [c["title"] for c in service.list_cards(board_db)]
    assert titles == ["live"]


def test_list_cards_include_archived(board_db: sqlite3.Connection):
    _insert(board_db, "old", status=ARCHIVED)
    titles = [c["title"] for c in service.list_cards(board_db, include_archived=True)]
    assert titles == ["old"]


def test_list_cards_project_filter(board_db: sqlite3.Connection):
    _insert(board_db, "mine", project="a")
    _insert(board_db, "theirs", project="b")
    titles = [c["title"] for c in service.list_cards(board_db, project="a")]
    assert titles == ["mine"]


def test_list_cards_statuses_filter(board_db: sqlite3.Connection):
    _insert(board_db, "b", status=BACKLOG)
    _insert(board_db, "r", status=REFINED)
    titles = [c["title"] for c in service.list_cards(board_db, statuses=[REFINED])]
    assert titles == ["r"]


def test_list_cards_priority_then_oldest(board_db: sqlite3.Connection):
    _insert(board_db, "low", priority="low")
    _insert(board_db, "high", priority="high")
    titles = [c["title"] for c in service.list_cards(board_db)]
    assert titles == ["high", "low"]


def test_get_card_returns_dict(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", acceptance="ac")
    card = service.get_card(board_db, cid)
    assert card is not None
    assert card["title"] == "x"
    assert card["acceptance_criteria"] == "ac"


def test_get_card_missing_returns_none(board_db: sqlite3.Connection):
    assert service.get_card(board_db, 999) is None


def test_get_comments_in_order(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_comment(board_db, cid, "first")
    service.add_comment(board_db, cid, "second", author="claude")
    comments = service.get_comments(board_db, cid)
    assert [c["body"] for c in comments] == ["first", "second"]
    assert comments[1]["author"] == "claude"


def test_list_projects_distinct_sorted(board_db: sqlite3.Connection):
    _insert(board_db, "a", project="zeta")
    _insert(board_db, "b", project="alpha")
    _insert(board_db, "c", project="alpha")
    assert service.list_projects(board_db) == ["alpha", "zeta"]


def test_summary_counts_excludes_archived(board_db: sqlite3.Connection):
    _insert(board_db, "b", status=BACKLOG)
    _insert(board_db, "r", status=REFINED)
    _insert(board_db, "r2", status=REFINED)
    _insert(board_db, "gone", status=ARCHIVED)
    counts = service.summary_counts(board_db)
    assert counts[BACKLOG] == 1
    assert counts[REFINED] == 2
    assert ARCHIVED not in counts


def test_summary_counts_project_scoped(board_db: sqlite3.Connection):
    _insert(board_db, "a", status=REFINED, project="x")
    _insert(board_db, "b", status=REFINED, project="y")
    counts = service.summary_counts(board_db, project="x")
    assert counts[REFINED] == 1


# --- Tags ---


def test_add_tag_idempotent(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_tag(board_db, cid, "urgent")
    service.add_tag(board_db, cid, "urgent")
    assert service.list_tags(board_db, cid) == ["urgent"]


def test_list_tags_sorted(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_tag(board_db, cid, "zeta")
    service.add_tag(board_db, cid, "alpha")
    assert service.list_tags(board_db, cid) == ["alpha", "zeta"]


def test_remove_tag_no_op_when_absent(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.remove_tag(board_db, cid, "ghost")  # must not raise
    assert service.list_tags(board_db, cid) == []


def test_remove_tag_deletes(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_tag(board_db, cid, "urgent")
    service.remove_tag(board_db, cid, "urgent")
    assert service.list_tags(board_db, cid) == []


def test_set_tags_replaces_whole_set(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_tag(board_db, cid, "old")
    service.set_tags(board_db, cid, ["alpha", "beta"])
    assert service.list_tags(board_db, cid) == ["alpha", "beta"]


def test_set_tags_from_empty(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.set_tags(board_db, cid, ["solo"])
    assert service.list_tags(board_db, cid) == ["solo"]


def test_set_tags_to_empty_clears(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_tag(board_db, cid, "gone")
    service.set_tags(board_db, cid, [])
    assert service.list_tags(board_db, cid) == []


def test_set_tags_collapses_duplicates(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.set_tags(board_db, cid, ["dup", "dup", "keep"])
    assert service.list_tags(board_db, cid) == ["dup", "keep"]


def test_set_tags_preserves_blocked_when_carried(board_db: sqlite3.Connection):
    # The TUI carries 'blocked' through so a form save can't silently unblock.
    cid = _insert(board_db, "x")
    service.block_card(board_db, cid)
    service.set_tags(board_db, cid, ["blocked", "new"])
    assert service.list_tags(board_db, cid) == ["blocked", "new"]


def test_cards_carry_tags_key(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_tag(board_db, cid, "b")
    service.add_tag(board_db, cid, "a")
    assert service.get_card(board_db, cid)["tags"] == ["a", "b"]
    assert service.list_cards(board_db)[0]["tags"] == ["a", "b"]


def test_cards_tags_key_empty_when_untagged(board_db: sqlite3.Connection):
    _insert(board_db, "x")
    assert service.list_cards(board_db)[0]["tags"] == []
    cid = _insert(board_db, "y")
    assert service.get_card(board_db, cid)["tags"] == []


def test_list_cards_tag_filter(board_db: sqlite3.Connection):
    tagged = _insert(board_db, "tagged")
    _insert(board_db, "plain")
    service.add_tag(board_db, tagged, "keep")
    titles = [c["title"] for c in service.list_cards(board_db, tag="keep")]
    assert titles == ["tagged"]


def test_list_cards_search_substring(board_db: sqlite3.Connection):
    _insert(board_db, "board TUI polish")
    _insert(board_db, "memory backlinks")
    titles = [c["title"] for c in service.list_cards(board_db, search="tui")]
    assert titles == ["board TUI polish"]


def test_list_cards_search_case_insensitive(board_db: sqlite3.Connection):
    _insert(board_db, "Search the Board")
    titles = [c["title"] for c in service.list_cards(board_db, search="SEARCH")]
    assert titles == ["Search the Board"]


def test_list_cards_search_no_match(board_db: sqlite3.Connection):
    _insert(board_db, "alpha")
    assert service.list_cards(board_db, search="zzz") == []


def test_list_cards_search_treats_wildcards_literally(board_db: sqlite3.Connection):
    # '%'/'_' in a query must match literally, not act as LIKE wildcards.
    _insert(board_db, "100% done")
    _insert(board_db, "100 nearly")
    titles = [c["title"] for c in service.list_cards(board_db, search="100%")]
    assert titles == ["100% done"]


def test_list_cards_search_composes_with_project(board_db: sqlite3.Connection):
    _insert(board_db, "shared name", project="a")
    _insert(board_db, "shared name", project="b")
    cards = service.list_cards(board_db, project="a", search="shared")
    assert [c["project"] for c in cards] == ["a"]


# --- next_refined ---


def test_next_refined_top_priority(board_db: sqlite3.Connection):
    _insert(board_db, "low", status=REFINED, priority="low")
    _insert(board_db, "high", status=REFINED, priority="high")
    card = service.next_refined(board_db, TEST_PROJECT)
    assert card is not None
    assert card["title"] == "high"


def test_next_refined_none_when_empty(board_db: sqlite3.Connection):
    _insert(board_db, "b", status=BACKLOG)
    assert service.next_refined(board_db, TEST_PROJECT) is None


def test_next_refined_claim_moves_to_in_progress(board_db: sqlite3.Connection):
    cid = _insert(board_db, "r", status=REFINED)
    card = service.next_refined(board_db, TEST_PROJECT, claim=True)
    assert card is not None
    assert card["status"] == IN_PROGRESS
    assert service.get_card(board_db, cid)["status"] == IN_PROGRESS


# --- Mutations ---


def test_add_card_returns_id(board_db: sqlite3.Connection):
    cid = service.add_card(board_db, project="p", title="t", priority="high")
    card = service.get_card(board_db, cid)
    assert card["title"] == "t"
    assert card["status"] == BACKLOG
    assert card["priority"] == "high"


def test_move_card_to_done_sets_completed_at(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", status=IN_PROGRESS)
    service.move_card(board_db, cid, DONE)
    card = service.get_card(board_db, cid)
    assert card["status"] == DONE
    assert card["completed_at"] is not None


def test_move_card_out_of_done_clears_completed_at(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", status=IN_PROGRESS)
    service.move_card(board_db, cid, DONE)
    assert service.get_card(board_db, cid)["completed_at"] is not None
    service.move_card(board_db, cid, IN_PROGRESS)
    assert service.get_card(board_db, cid)["completed_at"] is None


def test_move_card_within_non_done_keeps_completed_null(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", status=BACKLOG)
    service.move_card(board_db, cid, REFINED)
    assert service.get_card(board_db, cid)["completed_at"] is None


def test_move_card_missing_raises(board_db: sqlite3.Connection):
    with pytest.raises(service.CardNotFound):
        service.move_card(board_db, 999, DONE)


def test_refine_card_sets_fields(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.refine_card(board_db, cid, description="d", acceptance="ac")
    card = service.get_card(board_db, cid)
    assert card["status"] == REFINED
    assert card["description"] == "d"
    assert card["acceptance_criteria"] == "ac"


def test_complete_card_sets_summary_and_stamp(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", status=IN_PROGRESS)
    service.complete_card(board_db, cid, summary="shipped")
    card = service.get_card(board_db, cid)
    assert card["status"] == DONE
    assert card["completion_summary"] == "shipped"
    assert card["completed_at"] is not None


def test_block_card_tags_in_place(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", status=REFINED)
    service.block_card(board_db, cid, reason="waiting on review")
    card = service.get_card(board_db, cid)
    # Status is unchanged — blocking is now an in-place tag, not a move.
    assert card["status"] == REFINED
    assert BLOCKED_TAG in card["tags"]
    comments = service.get_comments(board_db, cid)
    assert comments[0]["body"] == "Blocked: waiting on review"


def test_block_card_no_reason_no_comment(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.block_card(board_db, cid)
    assert service.list_tags(board_db, cid) == [BLOCKED_TAG]
    assert service.get_comments(board_db, cid) == []


def test_unblock_card_removes_tag(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", status=IN_PROGRESS)
    service.block_card(board_db, cid)
    service.unblock_card(board_db, cid)
    card = service.get_card(board_db, cid)
    # Tag gone, flow position preserved (not forced back to refined).
    assert card["status"] == IN_PROGRESS
    assert BLOCKED_TAG not in card["tags"]


def test_archive_card(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.archive_card(board_db, cid)
    assert service.get_card(board_db, cid)["status"] == ARCHIVED


def test_add_comment_bumps_updated_at(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x", created_at="2020-01-01T00:00:00+00:00")
    before = service.get_card(board_db, cid)["updated_at"]
    service.add_comment(board_db, cid, "note")
    after = service.get_card(board_db, cid)["updated_at"]
    assert after >= before
    assert service.get_comments(board_db, cid)[0]["body"] == "note"


def test_edit_card_updates_fields(board_db: sqlite3.Connection):
    cid = _insert(board_db, "old")
    service.edit_card(board_db, cid, title="new", priority="high")
    card = service.get_card(board_db, cid)
    assert card["title"] == "new"
    assert card["priority"] == "high"


def test_remove_card_cascades_comments(board_db: sqlite3.Connection):
    cid = _insert(board_db, "x")
    service.add_comment(board_db, cid, "note")
    service.remove_card(board_db, cid)
    assert service.get_card(board_db, cid) is None
    assert (
        board_db.execute(
            "SELECT COUNT(*) FROM card_comments WHERE card_id = ?", (cid,)
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: service.move_card(c, 999, DONE),
        lambda c: service.refine_card(c, 999),
        lambda c: service.complete_card(c, 999),
        lambda c: service.block_card(c, 999),
        lambda c: service.unblock_card(c, 999),
        lambda c: service.archive_card(c, 999),
        lambda c: service.add_comment(c, 999, "x"),
        lambda c: service.edit_card(c, 999, title="x"),
        lambda c: service.remove_card(c, 999),
        lambda c: service.add_tag(c, 999, "x"),
        lambda c: service.remove_tag(c, 999, "x"),
        lambda c: service.set_tags(c, 999, ["x"]),
        lambda c: service.set_references(c, 999, [{"label": "a", "value": "1"}]),
    ],
)
def test_mutations_raise_card_not_found(board_db: sqlite3.Connection, mutation):
    with pytest.raises(service.CardNotFound):
        mutation(board_db)
