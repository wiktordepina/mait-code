"""End-to-end tests for the inbox CLI command handlers.

Mirrors the board CLI tests: the ``cmd_*`` functions are called directly with
an ``argparse.Namespace`` over the monkeypatched ``mock_conn`` connection.
"""

import argparse
import json
import sqlite3

import pytest


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


# --- add ---


def test_cmd_add(mock_conn: sqlite3.Connection, capsys):
    from mait_code.tools.inbox.cli import cmd_add

    cmd_add(_ns(body=["buy", "milk"]))
    rows = mock_conn.execute("SELECT body, project FROM inbox_items").fetchall()
    assert rows[0] == ("buy milk", "test-project")
    assert "Captured #1: buy milk" in capsys.readouterr().out


def test_cmd_add_empty_body(mock_conn: sqlite3.Connection):
    from mait_code.tools.inbox.cli import cmd_add

    with pytest.raises(SystemExit):
        cmd_add(_ns(body=["   "]))


# --- list ---


def test_cmd_list(mock_conn: sqlite3.Connection, capsys):
    from mait_code.tools.inbox.cli import cmd_add, cmd_list

    cmd_add(_ns(body=["thought one"]))
    capsys.readouterr()
    cmd_list(_ns(json=False))
    out = capsys.readouterr().out
    assert "[#1] thought one" in out


def test_cmd_list_empty(mock_conn: sqlite3.Connection, capsys):
    from mait_code.tools.inbox.cli import cmd_list

    cmd_list(_ns(json=False))
    assert "Inbox is empty." in capsys.readouterr().out


def test_cmd_list_json(mock_conn: sqlite3.Connection, capsys):
    from mait_code.tools.inbox.cli import cmd_add, cmd_list

    cmd_add(_ns(body=["json me"]))
    capsys.readouterr()
    cmd_list(_ns(json=True))
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["body"] == "json me"


# --- remove ---


def test_cmd_remove(mock_conn: sqlite3.Connection, capsys):
    from mait_code.tools.inbox.cli import cmd_add, cmd_remove

    cmd_add(_ns(body=["temp"]))
    capsys.readouterr()
    cmd_remove(_ns(id=1))
    assert "removed" in capsys.readouterr().out
    assert mock_conn.execute("SELECT COUNT(*) FROM inbox_items").fetchone()[0] == 0


def test_cmd_remove_not_found(mock_conn: sqlite3.Connection):
    from mait_code.tools.inbox.cli import cmd_remove

    with pytest.raises(SystemExit):
        cmd_remove(_ns(id=42))


# --- count ---


def test_cmd_count(mock_conn: sqlite3.Connection, capsys):
    from mait_code.tools.inbox.cli import cmd_add, cmd_count

    cmd_add(_ns(body=["one"]))
    cmd_add(_ns(body=["two"]))
    capsys.readouterr()
    cmd_count(_ns())
    assert capsys.readouterr().out.strip() == "2"


# --- main() dispatch ---


def test_main_dispatches_subcommand(mock_conn: sqlite3.Connection, capsys, monkeypatch):
    """``main()`` should parse argv and route to the matching handler."""
    monkeypatch.setattr("sys.argv", ["mc-tool-inbox", "add", "via", "main"])

    from mait_code.tools.inbox.cli import main

    main()
    assert "Captured #1: via main" in capsys.readouterr().out
    rows = mock_conn.execute("SELECT body FROM inbox_items").fetchall()
    assert rows[0][0] == "via main"


def test_main_requires_a_subcommand(monkeypatch):
    # The subparser is ``required=True`` — a bare invocation is a usage error.
    monkeypatch.setattr("sys.argv", ["mc-tool-inbox"])

    from mait_code.tools.inbox.cli import main

    with pytest.raises(SystemExit):
        main()
