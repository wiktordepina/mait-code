"""Tests for the ``--*-file`` options that read long text fields from a file.

Driven through ``main()`` and ``sys.argv`` so the mutually exclusive groups and
the handler-side resolution are exercised together.
"""

import json

import pytest

from mait_code.tools.board import service
from mait_code.tools.board.columns import IN_PROGRESS, REFINED

from tests.tools.board.conftest import TEST_PROJECT


def _run(monkeypatch, *argv: str) -> None:
    from mait_code.tools.board.cli import main

    monkeypatch.setattr("sys.argv", ["mc-tool-board", *argv])
    main()


def _card(conn, card_id: int) -> dict:
    card = service.get_card(conn, card_id)
    assert card is not None
    return card


def _comment_count(conn, card_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM card_comments WHERE card_id = ?", (card_id,)
    ).fetchone()[0]


def _new_card(conn, title: str = "card") -> int:
    return service.add_card(conn, project=TEST_PROJECT, title=title)


def _write(tmp_path, name: str, text: str, newline: str = "") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline=newline)
    return str(path)


MARKDOWN = "## Heading\n\n- `code` with $HOME and $(not expanded)\n- second"


# --- Each subcommand: file vs inline ---


def test_add_description_file(mock_conn, monkeypatch, capsys, tmp_path):
    path = _write(tmp_path, "d.md", MARKDOWN + "\n")
    _run(monkeypatch, "add", "from file", "--description-file", path, "--json")
    card_id = json.loads(capsys.readouterr().out)["id"]
    assert _card(mock_conn, card_id)["description"] == MARKDOWN


def test_add_description_inline_unchanged(mock_conn, monkeypatch, capsys):
    _run(monkeypatch, "add", "inline", "--description", "plain", "--json")
    card_id = json.loads(capsys.readouterr().out)["id"]
    assert _card(mock_conn, card_id)["description"] == "plain"


def test_edit_description_file_alone_is_an_edit(
    mock_conn, monkeypatch, capsys, tmp_path
):
    card_id = _new_card(mock_conn)
    path = _write(tmp_path, "d.md", MARKDOWN + "\n")
    _run(monkeypatch, "edit", str(card_id), "--description-file", path)
    assert "updated" in capsys.readouterr().out
    assert _card(mock_conn, card_id)["description"] == MARKDOWN


def test_edit_acceptance_file(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    path = _write(tmp_path, "a.md", "- done when X\n")
    _run(monkeypatch, "edit", str(card_id), "--acceptance-file", path)
    capsys.readouterr()
    assert _card(mock_conn, card_id)["acceptance_criteria"] == "- done when X"


def test_refine_files(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    desc = _write(tmp_path, "d.md", MARKDOWN + "\n")
    acc = _write(tmp_path, "a.md", "- done when X\n")
    _run(
        monkeypatch,
        "refine",
        str(card_id),
        "--description-file",
        desc,
        "--acceptance-file",
        acc,
    )
    captured = capsys.readouterr()
    card = _card(mock_conn, card_id)
    assert card["status"] == REFINED
    assert card["description"] == MARKDOWN
    assert card["acceptance_criteria"] == "- done when X"
    assert "no acceptance criteria" not in captured.err


def test_refine_acceptance_file_suppresses_missing_warning(
    mock_conn, monkeypatch, capsys, tmp_path
):
    card_id = _new_card(mock_conn)
    acc = _write(tmp_path, "a.md", "- done when X\n")
    _run(monkeypatch, "refine", str(card_id), "--acceptance-file", acc)
    assert "no acceptance criteria" not in capsys.readouterr().err


def test_complete_summary_file(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    service.move_card(mock_conn, card_id, IN_PROGRESS)
    path = _write(tmp_path, "s.md", "  Shipped:\n\n- one\n- two\n\n\n")
    _run(monkeypatch, "complete", str(card_id), "--summary-file", path)
    capsys.readouterr()
    # Summaries get the same strip as inline input, so outer whitespace goes.
    assert _card(mock_conn, card_id)["completion_summary"] == "Shipped:\n\n- one\n- two"


def test_comment_body_file(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    path = _write(tmp_path, "c.md", MARKDOWN + "\n")
    _run(
        monkeypatch,
        "comment",
        str(card_id),
        "--author",
        "claude",
        "--body-file",
        path,
        "--json",
    )
    comments = json.loads(capsys.readouterr().out)["comments"]
    assert comments[-1]["body"] == MARKDOWN
    assert comments[-1]["author"] == "claude"


def test_comment_inline_body_still_works(mock_conn, monkeypatch, capsys):
    card_id = _new_card(mock_conn)
    _run(monkeypatch, "comment", str(card_id), "looks", "good", "--json")
    assert json.loads(capsys.readouterr().out)["comments"][-1]["body"] == "looks good"


# --- Mutual exclusion ---


@pytest.mark.parametrize(
    "argv",
    [
        ["add", "t", "--description", "x", "--description-file", "{path}"],
        ["edit", "{id}", "--description", "x", "--description-file", "{path}"],
        ["edit", "{id}", "--acceptance", "x", "--acceptance-file", "{path}"],
        ["refine", "{id}", "--description", "x", "--description-file", "{path}"],
        ["refine", "{id}", "--acceptance", "x", "--acceptance-file", "{path}"],
        ["complete", "{id}", "--summary", "x", "--summary-file", "{path}"],
        ["comment", "{id}", "inline", "--body-file", "{path}"],
    ],
)
def test_inline_and_file_together_is_a_usage_error(
    mock_conn, monkeypatch, capsys, tmp_path, argv
):
    card_id = _new_card(mock_conn)
    path = _write(tmp_path, "f.md", "text")
    argv = [a.format(id=card_id, path=path) for a in argv]
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, *argv)
    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_comment_needs_body_or_body_file(mock_conn, monkeypatch, capsys):
    card_id = _new_card(mock_conn)
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "comment", str(card_id))
    assert exc.value.code == 2
    assert "is required" in capsys.readouterr().err


# --- Reading the file ---


@pytest.mark.parametrize(
    ("argv", "field"),
    [
        (["add", "t", "--description-file"], None),
        (["edit", "{id}", "--description-file"], "description"),
        (["edit", "{id}", "--acceptance-file"], "acceptance_criteria"),
        (["refine", "{id}", "--description-file"], "description"),
        (["complete", "{id}", "--summary-file"], "completion_summary"),
        (["comment", "{id}", "--body-file"], None),
    ],
)
def test_missing_file_fails_cleanly_and_writes_nothing(
    mock_conn, monkeypatch, capsys, tmp_path, argv, field
):
    card_id = _new_card(mock_conn)
    before = _card(mock_conn, card_id)
    missing = str(tmp_path / "nope.md")
    argv = [a.format(id=card_id) for a in argv] + [missing]
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, *argv)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: ")
    assert missing in err
    assert "Traceback" not in err
    assert _card(mock_conn, card_id) == before
    assert len(service.list_cards(mock_conn, project=TEST_PROJECT)) == 1
    assert _comment_count(mock_conn, card_id) == 0


def test_directory_path_fails_cleanly(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "edit", str(card_id), "--description-file", str(tmp_path))
    assert exc.value.code == 1
    assert capsys.readouterr().err.startswith("Error: ")


def test_non_utf8_file_fails_cleanly(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    path = tmp_path / "latin1.md"
    path.write_bytes("caf\xe9".encode("latin-1"))
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "edit", str(card_id), "--description-file", str(path))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "not valid UTF-8" in err
    assert str(path) in err


@pytest.mark.parametrize(
    ("content", "stored"),
    [
        ("text\n", "text"),
        ("text\r\n", "text"),
        ("text\n\n", "text\n"),
        ("text", "text"),
        ("one\r\ntwo\n", "one\r\ntwo"),
    ],
)
def test_one_trailing_newline_stripped_rest_verbatim(
    mock_conn, monkeypatch, capsys, tmp_path, content, stored
):
    card_id = _new_card(mock_conn)
    path = tmp_path / "d.md"
    path.write_bytes(content.encode("utf-8"))
    _run(monkeypatch, "edit", str(card_id), "--description-file", str(path))
    capsys.readouterr()
    assert _card(mock_conn, card_id)["description"] == stored


def test_tilde_path_is_expanded(mock_conn, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "d.md").write_text("from home\n", encoding="utf-8")
    card_id = _new_card(mock_conn)
    _run(monkeypatch, "edit", str(card_id), "--description-file", "~/d.md")
    capsys.readouterr()
    assert _card(mock_conn, card_id)["description"] == "from home"


def test_empty_description_file_stores_empty(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    service.edit_card(mock_conn, card_id, description="old")
    path = _write(tmp_path, "empty.md", "")
    _run(monkeypatch, "edit", str(card_id), "--description-file", path)
    capsys.readouterr()
    assert _card(mock_conn, card_id)["description"] == ""


def test_empty_body_file_is_refused(mock_conn, monkeypatch, capsys, tmp_path):
    card_id = _new_card(mock_conn)
    path = _write(tmp_path, "empty.md", "\n")
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "comment", str(card_id), "--body-file", path)
    assert exc.value.code == 1
    assert "comment body cannot be empty" in capsys.readouterr().err
    assert _comment_count(mock_conn, card_id) == 0


# --- Existing errors routed through _fail ---


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["add", " "], "card title cannot be empty."),
        (["edit", "{id}"], "nothing to edit (pass at least one field)."),
        (["edit", "{id}", "--project", " "], "--project cannot be blank."),
        (["comment", "{id}", " "], "comment body cannot be empty."),
    ],
)
def test_handler_errors_go_through_fail(
    mock_conn, monkeypatch, capsys, caplog, argv, message
):
    card_id = _new_card(mock_conn)
    argv = [a.format(id=card_id) for a in argv]
    with caplog.at_level("WARNING", logger="mait_code.tools.board.cli"):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, *argv)
    assert exc.value.code == 1
    assert capsys.readouterr().err == f"Error: {message}\n"
    assert message in caplog.text
