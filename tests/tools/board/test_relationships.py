"""Tests for board relationships: epics, parents and ``blocks`` links.

Exercises the service-layer invariants from schema v6 — an epic is exactly a
card on the reserved :data:`EPIC_PROJECT`, a parent is always an epic, and
``blocks`` links never form a loop — plus the readiness rule ``next_refined``
now applies.
"""

import sqlite3

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BLOCKED_TAG,
    CARD,
    DONE,
    EPIC,
    EPIC_PROJECT,
    IN_PROGRESS,
    IN_REVIEW,
    ORIGIN_LABEL,
    REFINED,
)
from mait_code.tools.board.sessions import SessionRef

from tests.tools.board.conftest import TEST_PROJECT


def _card(conn, title="card", *, project=TEST_PROJECT, status=None, parent_id=None):
    card_id = service.add_card(conn, project=project, title=title, parent_id=parent_id)
    if status is not None:
        service.move_card(conn, card_id, status)
    return card_id


def _epic(conn, title="epic"):
    return service.add_card(conn, project=None, title=title, kind=EPIC)


# --- Epics and the reserved project ---


def test_epic_gets_the_reserved_project(board_db: sqlite3.Connection):
    epic = service.get_card(board_db, _epic(board_db))
    assert epic is not None
    assert (epic["kind"], epic["project"]) == (EPIC, EPIC_PROJECT)


def test_epic_accepts_the_reserved_project_explicitly(board_db):
    eid = service.add_card(board_db, project=EPIC_PROJECT, title="e", kind=EPIC)
    assert service.get_card(board_db, eid)["project"] == EPIC_PROJECT


def test_epic_refuses_a_real_project(board_db):
    with pytest.raises(service.RelationError, match="no project"):
        service.add_card(board_db, project="homelab", title="e", kind=EPIC)


def test_card_refuses_the_reserved_project(board_db):
    with pytest.raises(service.RelationError, match="reserved for epics"):
        service.add_card(board_db, project=EPIC_PROJECT, title="c")


def test_card_needs_a_project(board_db):
    with pytest.raises(service.RelationError, match="needs a project"):
        service.add_card(board_db, project=None, title="c")


def test_unknown_kind_refused(board_db):
    with pytest.raises(service.RelationError, match="unknown kind"):
        service.add_card(board_db, project=TEST_PROJECT, title="c", kind="story")


def test_edit_refuses_moving_a_card_onto_the_reserved_project(board_db):
    cid = _card(board_db)
    with pytest.raises(service.RelationError):
        service.edit_card(board_db, cid, project=EPIC_PROJECT)


def test_edit_refuses_moving_an_epic_off_the_reserved_project(board_db):
    eid = _epic(board_db)
    with pytest.raises(service.RelationError, match="is an epic"):
        service.edit_card(board_db, eid, project="homelab")


def test_edit_still_retitles_an_epic(board_db):
    eid = _epic(board_db)
    service.edit_card(board_db, eid, title="renamed")
    assert service.get_card(board_db, eid)["title"] == "renamed"


def test_edit_refuses_kind(board_db):
    cid = _card(board_db)
    with pytest.raises(service.RelationError, match="can't be edited"):
        service.edit_card(board_db, cid, kind=EPIC)


def test_edit_sets_parent_and_fields_together(board_db):
    eid, cid = _epic(board_db), _card(board_db)
    service.edit_card(board_db, cid, parent_id=eid, title="renamed")
    card = service.get_card(board_db, cid)
    assert (card["parent_id"], card["title"]) == (eid, "renamed")
    service.edit_card(board_db, cid, parent_id=None)
    assert service.get_card(board_db, cid)["parent_id"] is None


def test_edit_leaves_parent_alone_unless_asked(board_db):
    eid = _epic(board_db)
    cid = _card(board_db, parent_id=eid)
    service.edit_card(board_db, cid, title="renamed")
    assert service.get_card(board_db, cid)["parent_id"] == eid


def test_refused_field_leaves_the_parent_unset(board_db):
    """A refused project must not let the parent change land on its own."""
    eid, cid = _epic(board_db), _card(board_db)
    with pytest.raises(service.RelationError, match="reserved for epics"):
        service.edit_card(board_db, cid, parent_id=eid, project=EPIC_PROJECT)
    assert service.get_card(board_db, cid)["parent_id"] is None
    assert not board_db.in_transaction


def test_refused_parent_leaves_the_fields_unchanged(board_db):
    cid, other = _card(board_db, "before"), _card(board_db)
    with pytest.raises(service.RelationError, match="isn't an epic"):
        service.edit_card(board_db, cid, parent_id=other, title="after")
    assert service.get_card(board_db, cid)["title"] == "before"


def test_edit_refuses_a_parent_for_an_epic(board_db):
    outer, inner = _epic(board_db), _epic(board_db)
    with pytest.raises(service.RelationError, match="can't have a parent"):
        service.edit_card(board_db, inner, parent_id=outer)


def test_epic_never_binds_a_session(board_db):
    eid = _epic(board_db)
    service.move_card(board_db, eid, IN_PROGRESS, session=SessionRef("s", 1))
    assert board_db.execute("SELECT COUNT(*) FROM card_sessions").fetchone()[0] == 0
    with pytest.raises(service.RelationError, match="epic"):
        service.bind_session(board_db, eid, SessionRef("s", 1))


# --- Parents ---


def test_add_card_with_a_parent(board_db):
    eid = _epic(board_db, "Voice")
    cid = _card(board_db, parent_id=eid)
    card = service.get_card(board_db, cid)
    assert card["parent_id"] == eid
    assert card["parent"] == {"id": eid, "title": "Voice"}


def test_parent_must_be_an_epic(board_db):
    other = _card(board_db)
    with pytest.raises(service.RelationError, match="isn't an epic"):
        _card(board_db, parent_id=other)
    cid = _card(board_db)
    with pytest.raises(service.RelationError, match="isn't an epic"):
        service.set_parent(board_db, cid, other)


def test_unknown_parent_is_not_found(board_db):
    with pytest.raises(service.CardNotFound):
        _card(board_db, parent_id=999)


def test_epic_cannot_have_a_parent(board_db):
    outer, inner = _epic(board_db), _epic(board_db)
    with pytest.raises(service.RelationError, match="can't have a parent"):
        service.set_parent(board_db, inner, outer)
    with pytest.raises(service.RelationError, match="can't have a parent"):
        service.add_card(board_db, project=None, title="e", kind=EPIC, parent_id=outer)


def test_set_parent_and_clear(board_db):
    eid, cid = _epic(board_db), _card(board_db)
    service.set_parent(board_db, cid, eid)
    assert service.get_card(board_db, cid)["parent_id"] == eid
    service.set_parent(board_db, cid, None)
    card = service.get_card(board_db, cid)
    assert card["parent_id"] is None and card["parent"] is None


def test_deleting_an_epic_orphans_its_members(board_db):
    eid = _epic(board_db)
    cid = _card(board_db, parent_id=eid)
    service.remove_card(board_db, eid)
    card = service.get_card(board_db, cid)
    assert card is not None and card["parent_id"] is None


# --- Origins (cards born from other cards) ---


def test_origin_passes_on_its_epic_and_is_referenced(board_db):
    eid = _epic(board_db)
    origin = _card(board_db, parent_id=eid)
    cid = service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=origin)
    card = service.get_card(board_db, cid)
    assert card["parent_id"] == eid
    assert card["references"] == [{"label": ORIGIN_LABEL, "value": f"#{origin}"}]


def test_origin_without_an_epic_gives_none(board_db):
    origin = _card(board_db)
    cid = service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=origin)
    assert service.get_card(board_db, cid)["parent_id"] is None


def test_explicit_parent_overrides_the_origins_epic(board_db):
    inherited, chosen = _epic(board_db), _epic(board_db)
    origin = _card(board_db, parent_id=inherited)
    for parent_id in (chosen, None):
        cid = service.add_card(
            board_db,
            project=TEST_PROJECT,
            title="f",
            origin_id=origin,
            parent_id=parent_id,
        )
        assert service.get_card(board_db, cid)["parent_id"] == parent_id


def test_origin_may_sit_in_another_project(board_db):
    eid = _epic(board_db)
    origin = _card(board_db, project="homelab", parent_id=eid)
    cid = service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=origin)
    assert service.get_card(board_db, cid)["parent_id"] == eid


def test_unknown_origin_is_not_found_and_adds_nothing(board_db):
    with pytest.raises(service.CardNotFound):
        service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=999)
    assert board_db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0


def test_a_failed_origin_reference_leaves_no_card(board_db):
    origin = _card(board_db)
    board_db.execute(
        "CREATE TRIGGER refuse_refs BEFORE INSERT ON card_references "
        "BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="refused"):
        service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=origin)
    assert [c["id"] for c in service.list_cards(board_db)] == [origin]


def test_an_epic_is_no_origin(board_db):
    eid = _epic(board_db)
    with pytest.raises(service.EpicOrigin, match="use it as the parent") as exc:
        service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=eid)
    assert isinstance(exc.value, service.RelationError)
    assert exc.value.card_id == eid


@pytest.mark.parametrize("status", [DONE, ARCHIVED])
def test_a_closed_inherited_epic_is_joined_by_default(board_db, status):
    eid = _epic(board_db)
    origin = _card(board_db, parent_id=eid)
    service.move_card(board_db, eid, status)
    cid = service.add_card(board_db, project=TEST_PROJECT, title="f", origin_id=origin)
    assert service.get_card(board_db, cid)["parent_id"] == eid


@pytest.mark.parametrize("status", [DONE, ARCHIVED])
def test_refuse_closed_epic_refuses_and_adds_nothing(board_db, status):
    eid = _epic(board_db)
    origin = _card(board_db, parent_id=eid)
    service.move_card(board_db, eid, status)
    with pytest.raises(service.InheritedEpicClosed) as exc:
        service.add_card(
            board_db,
            project=TEST_PROJECT,
            title="f",
            origin_id=origin,
            refuse_closed_epic=True,
        )
    assert isinstance(exc.value, service.RelationError)
    assert (exc.value.origin_id, exc.value.epic_id, exc.value.status) == (
        origin,
        eid,
        status,
    )
    assert board_db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2


def test_refuse_closed_epic_spares_an_open_epic(board_db):
    eid = _epic(board_db)
    origin = _card(board_db, parent_id=eid)
    cid = service.add_card(
        board_db,
        project=TEST_PROJECT,
        title="f",
        origin_id=origin,
        refuse_closed_epic=True,
    )
    assert service.get_card(board_db, cid)["parent_id"] == eid


def test_refuse_closed_epic_spares_an_explicit_parent(board_db):
    inherited, closed = _epic(board_db), _epic(board_db)
    service.move_card(board_db, inherited, DONE)
    service.move_card(board_db, closed, DONE)
    origin = _card(board_db, parent_id=inherited)
    for parent_id in (closed, None):
        cid = service.add_card(
            board_db,
            project=TEST_PROJECT,
            title="f",
            origin_id=origin,
            parent_id=parent_id,
            refuse_closed_epic=True,
        )
        assert service.get_card(board_db, cid)["parent_id"] == parent_id


def test_an_epic_has_no_origin(board_db):
    origin = _card(board_db)
    with pytest.raises(service.RelationError, match="can't come from a card"):
        service.add_card(board_db, project=None, title="e", kind=EPIC, origin_id=origin)


# --- Links ---


def test_link_shows_on_both_ends(board_db):
    a, b = _card(board_db, "a"), _card(board_db, "b")
    service.add_link(board_db, a, b)
    blocker, blocked = service.get_card(board_db, a), service.get_card(board_db, b)
    assert [c["id"] for c in blocker["blocks"]] == [b]
    assert blocker["blocked_by"] == []
    assert blocked["blocked_by"] == [
        {"id": a, "title": "a", "status": "backlog", "project": TEST_PROJECT}
    ]
    assert blocked["waiting_on"] == [a]


def test_self_link_refused(board_db):
    a = _card(board_db)
    with pytest.raises(service.RelationError, match="itself"):
        service.add_link(board_db, a, a)


def test_duplicate_link_refused(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    with pytest.raises(service.RelationError, match="already blocks"):
        service.add_link(board_db, a, b)


def test_link_to_an_epic_refused(board_db):
    a, eid = _card(board_db), _epic(board_db)
    with pytest.raises(service.RelationError, match="is an epic"):
        service.add_link(board_db, a, eid)
    with pytest.raises(service.RelationError, match="is an epic"):
        service.add_link(board_db, eid, a)


def test_unknown_link_type_refused(board_db):
    a, b = _card(board_db), _card(board_db)
    with pytest.raises(service.RelationError, match="unknown link type"):
        service.add_link(board_db, a, b, "relates_to")


def test_link_to_unknown_card_is_not_found(board_db):
    a = _card(board_db)
    with pytest.raises(service.CardNotFound):
        service.add_link(board_db, a, 999)


def test_two_card_loop_refused(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    with pytest.raises(service.LinkCycle) as exc:
        service.add_link(board_db, b, a)
    assert exc.value.path == [b, a, b]


def test_longer_loop_refused_with_its_path(board_db):
    a, b, c = _card(board_db), _card(board_db), _card(board_db)
    service.add_link(board_db, b, c)
    service.add_link(board_db, c, a)
    with pytest.raises(service.LinkCycle) as exc:
        service.add_link(board_db, a, b)
    assert exc.value.path == [a, b, c, a]
    assert f"#{a} → #{b} → #{c} → #{a}" in str(exc.value)


def test_refused_link_leaves_no_row_and_no_open_transaction(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    with pytest.raises(service.LinkCycle):
        service.add_link(board_db, b, a)
    assert not board_db.in_transaction
    assert board_db.execute("SELECT COUNT(*) FROM card_links").fetchone()[0] == 1
    # The connection is still usable for the next write.
    service.add_link(board_db, a, _card(board_db))


def test_diamond_is_not_a_loop(board_db):
    a, b, c, d = (_card(board_db) for _ in range(4))
    for from_id, to_id in ((a, b), (a, c), (b, d), (c, d)):
        service.add_link(board_db, from_id, to_id)
    assert service.get_card(board_db, d)["waiting_on"] == [b, c]


def test_remove_link(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    assert service.remove_link(board_db, a, b) is True
    assert service.remove_link(board_db, a, b) is False
    assert service.get_card(board_db, b)["blocked_by"] == []


def test_deleting_a_card_drops_its_links(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    service.remove_card(board_db, a)
    assert service.get_card(board_db, b)["blocked_by"] == []


@pytest.mark.parametrize("status", ["backlog", REFINED, IN_PROGRESS, IN_REVIEW])
def test_open_blocker_keeps_waiting(board_db, status):
    a, b = _card(board_db, status=status), _card(board_db)
    service.add_link(board_db, a, b)
    assert service.get_card(board_db, b)["waiting_on"] == [a]


def test_done_blocker_clears_waiting(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    service.complete_card(board_db, a)
    card = service.get_card(board_db, b)
    assert card["waiting_on"] == [] and card["archived_blockers"] == []


def test_archived_blocker_clears_waiting_but_is_flagged(board_db):
    a, b = _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    service.archive_card(board_db, a)
    card = service.get_card(board_db, b)
    assert card["waiting_on"] == [] and card["archived_blockers"] == [a]


# --- Readiness ---


def test_next_skips_a_card_waiting_on_a_blocker(board_db):
    blocker = _card(board_db, "blocker")
    waiting = _card(board_db, "waiting", status=REFINED)
    later = _card(board_db, "later", status=REFINED)
    service.add_link(board_db, blocker, waiting)
    assert service.next_refined(board_db, TEST_PROJECT)["id"] == later
    service.complete_card(board_db, blocker)
    assert service.next_refined(board_db, TEST_PROJECT)["id"] == waiting


def test_next_treats_an_archived_blocker_as_settled(board_db):
    blocker = _card(board_db)
    waiting = _card(board_db, status=REFINED)
    service.add_link(board_db, blocker, waiting)
    service.archive_card(board_db, blocker)
    assert service.next_refined(board_db, TEST_PROJECT)["id"] == waiting


def test_next_skips_a_tag_blocked_card(board_db):
    tagged = _card(board_db, "tagged", status=REFINED)
    service.add_tag(board_db, tagged, BLOCKED_TAG)
    assert service.next_refined(board_db, TEST_PROJECT) is None


def test_next_keeps_priority_then_oldest(board_db):
    low = _card(board_db, "low", status=REFINED)
    high = _card(board_db, "high", status=REFINED)
    service.edit_card(board_db, low, priority="low")
    service.edit_card(board_db, high, priority="high")
    assert service.next_refined(board_db, TEST_PROJECT)["id"] == high


def test_next_never_returns_an_epic(board_db):
    eid = _epic(board_db)
    service.move_card(board_db, eid, REFINED)
    assert service.next_refined(board_db, EPIC_PROJECT) is None


def test_next_by_epic_spans_projects(board_db):
    eid = _epic(board_db)
    _card(board_db, "outside", status=REFINED)
    member = _card(board_db, "member", project="homelab", status=REFINED, parent_id=eid)
    found = service.next_refined(board_db, TEST_PROJECT, epic_id=eid)
    assert found["id"] == member


def test_next_claim_still_claims(board_db):
    cid = _card(board_db, status=REFINED)
    claimed = service.next_refined(board_db, TEST_PROJECT, claim=True)
    assert claimed["id"] == cid and claimed["status"] == IN_PROGRESS


# --- Promotion ---


def test_promote_turns_a_card_into_an_epic(board_db):
    cid = _card(board_db, "roadmap", project="homelab", status=IN_PROGRESS)
    service.bind_session(board_db, cid, SessionRef("s", 1))
    service.promote_epic(board_db, cid)
    card = service.get_card(board_db, cid)
    assert (card["kind"], card["project"]) == (EPIC, EPIC_PROJECT)
    assert card["status"] == IN_PROGRESS  # status is kept, by hand from here
    assert board_db.execute("SELECT COUNT(*) FROM card_sessions").fetchone()[0] == 0
    notes = [c["body"] for c in service.get_comments(board_db, cid)]
    assert notes == ["Promoted to an epic (was in project homelab)."]


def test_promote_refuses_an_epic(board_db):
    with pytest.raises(service.RelationError, match="already an epic"):
        service.promote_epic(board_db, _epic(board_db))


def test_promote_refuses_a_member(board_db):
    cid = _card(board_db, parent_id=_epic(board_db))
    with pytest.raises(service.RelationError, match="belongs to epic"):
        service.promote_epic(board_db, cid)


@pytest.mark.parametrize("end", ["from", "to"])
def test_promote_refuses_a_linked_card(board_db, end):
    cid, other = _card(board_db), _card(board_db)
    if end == "from":
        service.add_link(board_db, cid, other)
    else:
        service.add_link(board_db, other, cid)
    with pytest.raises(service.RelationError, match="blocks links"):
        service.promote_epic(board_db, cid)


# --- Epic listings and the graph ---


def test_epic_members(board_db):
    eid = _epic(board_db)
    member = _card(board_db, parent_id=eid)
    _card(board_db)  # not a member
    assert [c["id"] for c in service.epic_members(board_db, eid)] == [member]
    with pytest.raises(service.RelationError):
        service.epic_members(board_db, member)


def test_list_epics_with_progress(board_db):
    eid = _epic(board_db, "Voice")
    blocker = _card(board_db, parent_id=eid, status=IN_PROGRESS)
    waiting = _card(board_db, parent_id=eid, status=REFINED)
    _card(board_db, parent_id=eid, status=DONE)
    gone = _card(board_db, parent_id=eid)
    service.archive_card(board_db, gone)
    service.add_link(board_db, blocker, waiting)
    [epic] = service.list_epics(board_db)
    assert epic["id"] == eid
    progress = epic["progress"]
    assert progress["total"] == 3  # archived members don't count
    assert (progress[IN_PROGRESS], progress[REFINED], progress[DONE]) == (1, 1, 1)
    assert progress["waiting"] == 1


def test_list_epics_hides_done_unless_asked(board_db):
    eid = _epic(board_db)
    service.complete_card(board_db, eid)
    assert service.list_epics(board_db) == []
    assert [e["id"] for e in service.list_epics(board_db, include_done=True)] == [eid]


def test_dependency_graph_for_an_epic_marks_outside_cards_as_stubs(board_db):
    eid = _epic(board_db)
    outside = _card(board_db, "outside")
    first = _card(board_db, "first", parent_id=eid)
    second = _card(board_db, "second", parent_id=eid)
    lonely = _card(board_db, "lonely", parent_id=eid)
    unrelated_a, unrelated_b = _card(board_db), _card(board_db)
    service.add_link(board_db, outside, first)
    service.add_link(board_db, first, second)
    service.add_link(board_db, unrelated_a, unrelated_b)
    graph = service.dependency_graph(board_db, epic_id=eid)
    assert graph["edges"] == [
        {"from": outside, "to": first},
        {"from": first, "to": second},
    ]
    stubs = {n["id"]: n["stub"] for n in graph["nodes"]}
    assert stubs == {outside: True, first: False, second: False, lonely: False}


def test_dependency_graph_without_an_epic_skips_archived(board_db):
    a, b, c = _card(board_db), _card(board_db), _card(board_db)
    service.add_link(board_db, a, b)
    service.add_link(board_db, b, c)
    service.archive_card(board_db, c)
    graph = service.dependency_graph(board_db)
    assert graph["edges"] == [{"from": a, "to": b}]
    assert [n["id"] for n in graph["nodes"]] == [a, b]
    assert not any(n["stub"] for n in graph["nodes"])


def test_cards_carry_kind_card_by_default(board_db):
    assert service.get_card(board_db, _card(board_db))["kind"] == CARD


def test_archived_constant_is_settled(board_db):
    # Guard against _SETTLED drifting from the documented rule.
    assert set(service._SETTLED) == {DONE, ARCHIVED}


# --- Write locking against a parallel writer ---


class _Interleave:
    """A connection proxy that runs *meanwhile* right after a matching query.

    Simulates another process writing between a mutation's checks and its
    write. With the mutation holding the write lock from the start, that
    writer must be refused rather than slip in.
    """

    def __init__(self, conn, marker, meanwhile):
        self._conn, self._marker, self._meanwhile = conn, marker, meanwhile
        self.attempted = False

    def execute(self, sql, *args):
        cursor = self._conn.execute(sql, *args)
        if self._marker in sql and not self.attempted:
            self.attempted = True
            rows = cursor.fetchall()
            self._meanwhile()

            class _Rows:
                def fetchone(self):
                    return rows[0] if rows else None

                def fetchall(self):
                    return rows

            return _Rows()
        return cursor

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def two_writers(tmp_path):
    from mait_code.tools.board.db import get_connection

    path = tmp_path / "shared.db"
    first = get_connection(path)
    second = sqlite3.connect(path, timeout=0.1)  # fail fast instead of waiting
    second.execute("PRAGMA foreign_keys = ON")
    yield first, second
    first.close()
    second.close()


def test_promote_holds_the_lock_across_its_link_check(two_writers):
    first, second = two_writers
    x, y = _card(first), _card(first)
    proxy = _Interleave(
        first, "FROM card_links WHERE type", lambda: service.add_link(second, x, y)
    )
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        service.promote_epic(proxy, x)  # type: ignore[arg-type]
    assert proxy.attempted
    # The parallel writer was refused; promote never ran into its write either
    # (the OperationalError surfaced inside its transaction and rolled it back).
    assert first.execute("SELECT COUNT(*) FROM card_links").fetchone()[0] == 0
    service.promote_epic(first, x)
    assert service.get_card(first, x)["kind"] == EPIC


def test_set_parent_holds_the_lock_across_its_checks(two_writers):
    first, second = two_writers
    eid, x = _epic(first), _card(first)
    proxy = _Interleave(
        first, "FROM cards WHERE id", lambda: service.promote_epic(second, x)
    )
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        service.set_parent(proxy, x, eid)  # type: ignore[arg-type]
    assert service.get_card(first, x)["kind"] == CARD
    assert not first.in_transaction


def test_next_by_unknown_or_non_epic_id_raises(board_db):
    cid = _card(board_db)
    with pytest.raises(service.CardNotFound):
        service.next_refined(board_db, None, epic_id=999)
    with pytest.raises(service.RelationError, match="isn't an epic"):
        service.next_refined(board_db, None, epic_id=cid)


def test_next_needs_a_project_or_an_epic(board_db):
    with pytest.raises(ValueError, match="project or an epic_id"):
        service.next_refined(board_db, None)
