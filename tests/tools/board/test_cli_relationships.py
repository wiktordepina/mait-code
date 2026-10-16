"""End-to-end tests for the board CLI's relationship surface.

Drives ``mc-tool-board`` through :func:`main` with a real argv, so argument
parsing (``link A blocks B``, ``--parent none``, ``epic …``) is exercised along
with the handlers, all against the temp database from ``mock_conn``.
"""

import json
import sys

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.cli import main
from mait_code.tools.board.columns import (
    DONE,
    EPIC,
    EPIC_PROJECT,
    IN_PROGRESS,
    REFINED,
)

from tests.tools.board.conftest import TEST_PROJECT


@pytest.fixture
def run(mock_conn, monkeypatch, capsys):
    """Run ``mc-tool-board <argv>``; return ``(exit_code, stdout, stderr)``."""

    def _run(*argv: object) -> tuple[int, str, str]:
        monkeypatch.setattr(sys, "argv", ["mc-tool-board", *map(str, argv)])
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        out, err = capsys.readouterr()
        return code, out, err

    return _run


def _card(conn, title="card", *, project=TEST_PROJECT, status=None, parent_id=None):
    card_id = service.add_card(conn, project=project, title=title, parent_id=parent_id)
    if status is not None:
        service.move_card(conn, card_id, status)
    return card_id


def _epic(conn, title="Umbrella"):
    return service.add_card(conn, project=None, title=title, kind=EPIC)


# --- link / unlink ---


def test_link_and_unlink(run, mock_conn):
    a, b = _card(mock_conn, "a"), _card(mock_conn, "b")
    code, out, _ = run("link", a, "blocks", b)
    assert code == 0 and out.strip() == f"#{a} blocks #{b}."
    assert service.get_card(mock_conn, b)["waiting_on"] == [a]
    code, out, _ = run("unlink", a, "blocks", b)
    assert code == 0 and "no longer blocks" in out
    assert service.get_card(mock_conn, b)["blocked_by"] == []


def test_link_json_emits_the_waiting_card(run, mock_conn):
    a, b = _card(mock_conn), _card(mock_conn)
    code, out, _ = run("link", a, "blocks", b, "--json")
    assert code == 0 and json.loads(out)["waiting_on"] == [a]


def test_link_loop_is_refused_with_its_path(run, mock_conn):
    a, b, c = (_card(mock_conn) for _ in range(3))
    run("link", b, "blocks", c)
    run("link", c, "blocks", a)
    code, _, err = run("link", a, "blocks", b)
    assert code == 1
    assert f"#{a} → #{b} → #{c} → #{a}" in err


@pytest.mark.parametrize("case", ["self", "duplicate", "epic"])
def test_link_refusals_exit_1(run, mock_conn, case):
    a, b = _card(mock_conn), _card(mock_conn)
    if case == "self":
        argv, expected = (a, "blocks", a), "itself"
    elif case == "duplicate":
        run("link", a, "blocks", b)
        argv, expected = (a, "blocks", b), "already blocks"
    else:
        argv, expected = (a, "blocks", _epic(mock_conn)), "is an epic"
    code, out, err = run("link", *argv)
    assert code == 1 and expected in err and "Traceback" not in out + err


def test_link_unknown_card_names_it(run, mock_conn):
    a = _card(mock_conn)
    code, _, err = run("link", a, "blocks", 999)
    assert code == 1 and "card #999 not found" in err


def test_unlink_missing_link_exits_1(run, mock_conn):
    a, b = _card(mock_conn), _card(mock_conn)
    code, _, err = run("unlink", a, "blocks", b)
    assert code == 1 and f"#{a} doesn't block #{b}" in err


# --- add / edit with epics and parents ---


def test_add_epic(run, mock_conn):
    code, out, _ = run("add", "Voice", "assistant", "--epic", "--json")
    card = json.loads(out)
    assert code == 0
    assert (card["kind"], card["project"], card["title"]) == (
        EPIC,
        EPIC_PROJECT,
        "Voice assistant",
    )


@pytest.mark.parametrize("extra", [["--project", "homelab"], ["--parent", "1"]])
def test_add_epic_refuses_project_and_parent(run, extra):
    code, _, err = run("add", "e", "--epic", *extra)
    assert code == 1 and ("no project" in err or "can't have a parent" in err)


def test_add_with_parent(run, mock_conn):
    eid = _epic(mock_conn)
    code, out, _ = run("add", "member", "--parent", eid, "--json")
    assert code == 0 and json.loads(out)["parent"]["id"] == eid


def test_add_with_a_non_epic_parent_is_refused(run, mock_conn):
    other = _card(mock_conn)
    code, _, err = run("add", "member", "--parent", other)
    assert code == 1 and "isn't an epic" in err


def test_edit_parent_set_and_clear(run, mock_conn):
    eid, cid = _epic(mock_conn), _card(mock_conn)
    assert run("edit", cid, "--parent", eid)[0] == 0
    assert service.get_card(mock_conn, cid)["parent_id"] == eid
    assert run("edit", cid, "--parent", "none")[0] == 0
    assert service.get_card(mock_conn, cid)["parent_id"] is None


def test_edit_parent_with_another_field(run, mock_conn):
    eid, cid = _epic(mock_conn), _card(mock_conn)
    assert run("edit", cid, "--parent", eid, "--title", "renamed")[0] == 0
    card = service.get_card(mock_conn, cid)
    assert (card["parent_id"], card["title"]) == (eid, "renamed")


def test_edit_parent_rejects_garbage(run, mock_conn):
    cid = _card(mock_conn)
    code, _, err = run("edit", cid, "--parent", "soon")
    assert code == 2 and "epic id or 'none'" in err


def test_edit_refused_project_does_not_set_the_parent(run, mock_conn):
    eid, cid = _epic(mock_conn), _card(mock_conn)
    code, _, err = run("edit", cid, "--parent", eid, "--project", EPIC_PROJECT)
    assert code == 1 and "reserved for epics" in err
    assert service.get_card(mock_conn, cid)["parent_id"] is None


def test_edit_unknown_parent_names_the_parent(run, mock_conn):
    cid = _card(mock_conn)
    code, _, err = run("edit", cid, "--parent", 999)
    assert code == 1 and "card #999 not found" in err


def test_edit_project_on_an_epic_is_refused(run, mock_conn):
    eid = _epic(mock_conn)
    code, _, err = run("edit", eid, "--project", "homelab")
    assert code == 1 and "is an epic" in err


# --- epic list / show / promote ---


def test_epic_list_with_progress(run, mock_conn):
    eid = _epic(mock_conn, "Voice")
    blocker = _card(mock_conn, parent_id=eid, status=IN_PROGRESS)
    waiting = _card(mock_conn, parent_id=eid, status=REFINED)
    _card(mock_conn, parent_id=eid, status=DONE)
    service.add_link(mock_conn, blocker, waiting)
    code, out, _ = run("epic", "list")
    assert code == 0
    assert (
        f"[#{eid}] (medium) Voice — Backlog — 1/3 done · 1 waiting · 1 in progress"
        in out
    )


def test_epic_list_done_flag(run, mock_conn):
    eid = _epic(mock_conn)
    service.complete_card(mock_conn, eid)
    assert run("epic", "list")[1].strip() == "No epics."
    assert f"[#{eid}]" in run("epic", "list", "--done")[1]


def test_epic_list_json(run, mock_conn):
    eid = _epic(mock_conn)
    code, out, _ = run("epic", "list", "--json")
    [epic] = json.loads(out)
    assert code == 0 and epic["id"] == eid and epic["progress"]["total"] == 0


def test_epic_show_groups_members_with_waiting_markers(run, mock_conn):
    eid = _epic(mock_conn, "Voice")
    blocker = _card(mock_conn, "Wake word", project="homelab", parent_id=eid)
    waiting = _card(mock_conn, "Router", parent_id=eid, status=REFINED)
    service.add_link(mock_conn, blocker, waiting)
    code, out, _ = run("epic", "show", eid)
    assert code == 0
    assert "0/2 done · 1 waiting" in out
    assert "Backlog (1):" in out and "Refined (1):" in out
    assert f"[#{blocker}] (medium) Wake word [homelab]" in out
    assert f"Router [{TEST_PROJECT}]  waiting on #{blocker}" in out


def test_epic_show_json_has_members_and_comments(run, mock_conn):
    eid = _epic(mock_conn)
    member = _card(mock_conn, parent_id=eid)
    code, out, _ = run("epic", "show", eid, "--json")
    epic = json.loads(out)
    assert code == 0
    assert [m["id"] for m in epic["members"]] == [member]
    assert epic["comments"] == [] and epic["progress"]["total"] == 1


def test_epic_show_refuses_a_plain_card(run, mock_conn):
    cid = _card(mock_conn)
    code, _, err = run("epic", "show", cid)
    assert code == 1 and "isn't an epic" in err


def test_epic_promote(run, mock_conn):
    cid = _card(mock_conn, "roadmap", project="homelab")
    code, out, _ = run("epic", "promote", cid)
    assert code == 0 and "now an epic (was in project homelab)" in out
    assert service.get_card(mock_conn, cid)["kind"] == EPIC


def test_epic_promote_explains_a_refusal(run, mock_conn):
    cid, other = _card(mock_conn), _card(mock_conn)
    service.add_link(mock_conn, cid, other)
    code, _, err = run("epic", "promote", cid)
    assert code == 1 and "blocks links" in err


# --- list / next scoping ---


def test_list_epic_spans_projects(run, mock_conn):
    eid = _epic(mock_conn)
    here = _card(mock_conn, "here", parent_id=eid)
    there = _card(mock_conn, "there", project="homelab", parent_id=eid)
    _card(mock_conn, "not a member")
    code, out, _ = run("list", "--epic", eid, "--json")
    assert code == 0 and {c["id"] for c in json.loads(out)} == {here, there}
    text = run("list", "--epic", eid)[1]
    assert "[homelab]" in text and "not a member" not in text


def test_list_epic_refuses_a_plain_card(run, mock_conn):
    code, _, err = run("list", "--epic", _card(mock_conn))
    assert code == 1 and "isn't an epic" in err


def test_list_ready(run, mock_conn):
    blocker = _card(mock_conn)
    ready = _card(mock_conn, "ready", status=REFINED)
    waiting = _card(mock_conn, "waiting", status=REFINED)
    tagged = _card(mock_conn, "tagged", status=REFINED)
    service.add_link(mock_conn, blocker, waiting)
    service.block_card(mock_conn, tagged)
    code, out, _ = run("list", "--ready", "--json")
    assert code == 0 and [c["id"] for c in json.loads(out)] == [ready]


def test_list_rows_mark_waiting_cards(run, mock_conn):
    a, b = _card(mock_conn, "a"), _card(mock_conn, "b")
    service.add_link(mock_conn, a, b)
    out = run("list")[1]
    assert f"[#{b}] (medium) b  waiting on #{a}" in out
    assert f"[#{a}] (medium) a\n" in out


def test_next_epic_and_claim(run, mock_conn):
    eid = _epic(mock_conn)
    _card(mock_conn, "outside", status=REFINED)
    member = _card(
        mock_conn, "member", project="homelab", parent_id=eid, status=REFINED
    )
    code, out, _ = run("next", "--epic", eid, "--json")
    assert code == 0 and json.loads(out)["id"] == member
    code, out, _ = run("next", "--epic", eid, "--claim")
    assert code == 0 and out.startswith(f"Picked up: #{member}")
    assert service.get_card(mock_conn, member)["status"] == IN_PROGRESS


def test_next_epic_with_nothing_ready(run, mock_conn):
    eid = _epic(mock_conn)
    code, out, _ = run("next", "--epic", eid)
    assert code == 0 and f"No ready cards in epic #{eid}" in out


def test_next_epic_refuses_project_too(run, mock_conn):
    code, _, err = run("next", "--epic", _epic(mock_conn), "--project", "x")
    assert code == 1 and "not both" in err


# --- show ---


def test_show_relationship_lines(run, mock_conn):
    eid = _epic(mock_conn, "Voice")
    blocker = _card(mock_conn, "blocker")
    dropped = _card(mock_conn, "dropped")
    card = _card(mock_conn, "card", parent_id=eid)
    downstream = _card(mock_conn, "downstream")
    for from_id, to_id in ((blocker, card), (dropped, card), (card, downstream)):
        service.add_link(mock_conn, from_id, to_id)
    service.archive_card(mock_conn, dropped)
    out = run("show", card)[1]
    assert f"epic: #{eid} Voice" in out
    assert f"waiting on: #{blocker} blocker (Backlog)" in out
    assert f"blocks: #{downstream} downstream (Backlog)" in out
    assert f"archived blockers: #{dropped} dropped (Archived)" in out


def test_show_epic_has_progress_not_project(run, mock_conn):
    eid = _epic(mock_conn)
    _card(mock_conn, parent_id=eid, status=DONE)
    out = run("show", eid)[1]
    assert "1/1 done" in out and EPIC_PROJECT not in out


# --- the "no open members" reminder ---


@pytest.mark.parametrize(
    "argv",
    [("complete", "{id}"), ("move", "{id}", "done"), ("archive", "{id}")],
)
def test_last_open_member_reminds_about_the_epic(run, mock_conn, argv):
    eid = _epic(mock_conn)
    _card(mock_conn, parent_id=eid, status=DONE)
    last = _card(mock_conn, parent_id=eid)
    code, out, err = run(*(a.format(id=last) for a in argv), "--json")
    assert code == 0
    json.loads(out)  # stdout stays one JSON document
    assert f"epic #{eid} has no open members" in err
    assert service.get_card(mock_conn, eid)["status"] == "backlog"  # never moved


def test_reminder_suggests_complete_when_work_finished(run, mock_conn):
    eid = _epic(mock_conn)
    last = _card(mock_conn, parent_id=eid)
    err = run("complete", last)[2]
    assert f"complete it with 'mc-tool-board complete {eid}'" in err


def test_reminder_suggests_archive_when_every_member_was_dropped(run, mock_conn):
    eid = _epic(mock_conn)
    _card(mock_conn, parent_id=eid, status="archived")
    last = _card(mock_conn, parent_id=eid)
    err = run("archive", last)[2]
    assert f"archive it with 'mc-tool-board archive {eid}' if it's dropped" in err


def test_no_reminder_while_members_are_open(run, mock_conn):
    eid = _epic(mock_conn)
    first = _card(mock_conn, parent_id=eid)
    _card(mock_conn, parent_id=eid)
    assert "no open members" not in run("complete", first)[2]


def test_no_reminder_for_a_settled_epic(run, mock_conn):
    eid = _epic(mock_conn)
    last = _card(mock_conn, parent_id=eid)
    service.complete_card(mock_conn, eid)
    assert "no open members" not in run("complete", last)[2]


# --- export ---


def test_export_card_markdown_has_relationship_lines(run, mock_conn):
    eid = _epic(mock_conn, "Voice")
    blocker = _card(mock_conn, "blocker")
    card = _card(mock_conn, "card", parent_id=eid)
    service.add_link(mock_conn, blocker, card)
    out = run("export", card)[1]
    assert f"- **Epic:** #{eid} Voice" in out
    assert f"- **Waiting on:** #{blocker} blocker (Backlog)" in out
    assert f"- **Blocks:** #{card} card (Backlog)" in run("export", blocker)[1]


def test_export_epic_markdown_and_json(run, mock_conn):
    eid = _epic(mock_conn, "Voice")
    member = _card(mock_conn, "member", parent_id=eid, status=REFINED)
    service.add_comment(mock_conn, member, "note")
    markdown = run("export", "--epic", eid)[1]
    assert markdown.startswith("# Voice")
    assert (
        f"- **Epic:** #{eid}" in markdown
        and "**Project:**" not in markdown.split("##")[0]
    )
    assert "## Members — 0/1 done" in markdown and "### Refined (1)" in markdown
    assert "#### member" in markdown
    epic = json.loads(run("export", "--epic", eid, "--format", "json")[1])
    assert epic["members"][0]["comments"][0]["body"] == "note"
    assert "sessions" not in epic and "sessions" not in epic["members"][0]


@pytest.mark.parametrize(
    "flags",
    [
        ["--status", "done"],
        ["--search", "x"],
        ["--all"],
        ["--project", "p"],
        ["--archived"],
    ],
)
def test_export_epic_refuses_board_filters(run, mock_conn, flags):
    code, _, err = run("export", "--epic", _epic(mock_conn), *flags)
    assert code == 1 and flags[0] in err and "filter a board export" in err


def test_refining_an_epic_does_not_warn_about_acceptance(run, mock_conn):
    eid = _epic(mock_conn)
    code, _, err = run("refine", eid, "--description", "umbrella")
    assert code == 0 and "no acceptance criteria" not in err


def test_export_card_and_epic_together_refused(run, mock_conn):
    code, _, err = run("export", 1, "--epic", _epic(mock_conn))
    assert code == 1 and "not both" in err
