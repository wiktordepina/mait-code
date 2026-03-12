"""Tests for decisions tool — migrations, CLI commands, FTS sync, and rendering."""

import argparse
import sqlite3
from unittest.mock import patch

import pytest

from mait_code.tools.decisions.cli import _now
from mait_code.tools.decisions.migrate import ensure_schema
from mait_code.tools.decisions.render import render_decisions_md

from tests.tools.decisions.conftest import TEST_PROJECT


# --- Migration tests ---


def test_ensure_schema_creates_tables(decisions_db: sqlite3.Connection):
    tables = decisions_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]
    assert "decisions" in table_names
    assert "schema_version" in table_names


def test_ensure_schema_idempotent(decisions_db: sqlite3.Connection):
    ensure_schema(decisions_db)
    ensure_schema(decisions_db)
    versions = decisions_db.execute("SELECT version FROM schema_version").fetchall()
    assert len(versions) == 1
    assert versions[0][0] == 1


def test_decisions_columns(decisions_db: sqlite3.Connection):
    columns = decisions_db.execute("PRAGMA table_info(decisions)").fetchall()
    col_names = [c[1] for c in columns]
    assert col_names == [
        "id",
        "project",
        "title",
        "context",
        "alternatives",
        "consequences",
        "status",
        "superseded_by",
        "tags",
        "created_at",
        "updated_at",
    ]


def test_fts_table_exists(decisions_db: sqlite3.Connection):
    tables = decisions_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='decisions_fts'"
    ).fetchall()
    assert len(tables) == 1


def test_index_exists(decisions_db: sqlite3.Connection):
    indexes = decisions_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='idx_decisions_project_status'"
    ).fetchall()
    assert len(indexes) == 1


# --- Helpers ---


def _insert_decision(
    conn,
    title,
    project=TEST_PROJECT,
    context=None,
    alternatives=None,
    consequences=None,
    status="accepted",
    tags=None,
):
    now = _now().isoformat()
    conn.execute(
        "INSERT INTO decisions (project, title, context, alternatives, consequences, "
        "status, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project, title, context, alternatives, consequences, status, tags, now),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# --- FTS sync tests ---


def test_fts_insert_sync(decisions_db: sqlite3.Connection):
    _insert_decision(decisions_db, "Use PostgreSQL", context="Need relational store")
    results = decisions_db.execute(
        "SELECT rowid FROM decisions_fts WHERE decisions_fts MATCH 'PostgreSQL'"
    ).fetchall()
    assert len(results) == 1


def test_fts_update_sync(decisions_db: sqlite3.Connection):
    did = _insert_decision(decisions_db, "Use MySQL")
    decisions_db.execute(
        "UPDATE decisions SET title = 'Use PostgreSQL' WHERE id = ?", (did,)
    )
    decisions_db.commit()

    old = decisions_db.execute(
        "SELECT rowid FROM decisions_fts WHERE decisions_fts MATCH 'MySQL'"
    ).fetchall()
    assert len(old) == 0

    new = decisions_db.execute(
        "SELECT rowid FROM decisions_fts WHERE decisions_fts MATCH 'PostgreSQL'"
    ).fetchall()
    assert len(new) == 1


def test_fts_delete_sync(decisions_db: sqlite3.Connection):
    did = _insert_decision(decisions_db, "Use Redis")
    decisions_db.execute("DELETE FROM decisions WHERE id = ?", (did,))
    decisions_db.commit()

    results = decisions_db.execute(
        "SELECT rowid FROM decisions_fts WHERE decisions_fts MATCH 'Redis'"
    ).fetchall()
    assert len(results) == 0


# --- CLI command tests ---


def test_cmd_record(mock_conn, capsys):
    from mait_code.tools.decisions.cli import cmd_record

    args = argparse.Namespace(
        title=["Use", "PostgreSQL"],
        context="Need relational store",
        alternatives="MySQL, SQLite",
        consequences="Requires managed instance",
        status="accepted",
        tags="db,infra",
    )
    cmd_record(args)

    rows = mock_conn.execute(
        "SELECT title, context, status, tags FROM decisions"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Use PostgreSQL"
    assert rows[0][1] == "Need relational store"
    assert rows[0][2] == "accepted"
    assert rows[0][3] == "db,infra"

    output = capsys.readouterr().out
    assert "Use PostgreSQL" in output


def test_cmd_record_empty_title(mock_conn):
    from mait_code.tools.decisions.cli import cmd_record

    with pytest.raises(SystemExit, match="1"):
        cmd_record(
            argparse.Namespace(
                title=["  "],
                context=None,
                alternatives=None,
                consequences=None,
                status="accepted",
                tags=None,
            )
        )


def test_cmd_list_default(mock_conn, capsys):
    _insert_decision(mock_conn, "Accepted one", status="accepted")
    _insert_decision(mock_conn, "Proposed one", status="proposed")
    _insert_decision(mock_conn, "Deprecated one", status="deprecated")

    from mait_code.tools.decisions.cli import cmd_list

    cmd_list(argparse.Namespace(all=False, tag=None, status=None))
    output = capsys.readouterr().out
    assert "Accepted one" in output
    assert "Proposed one" in output
    assert "Deprecated one" not in output


def test_cmd_list_all(mock_conn, capsys):
    _insert_decision(mock_conn, "Accepted one", status="accepted")
    _insert_decision(mock_conn, "Deprecated one", status="deprecated")

    from mait_code.tools.decisions.cli import cmd_list

    cmd_list(argparse.Namespace(all=True, tag=None, status=None))
    output = capsys.readouterr().out
    assert "Accepted one" in output
    assert "Deprecated one" in output


def test_cmd_list_by_tag(mock_conn, capsys):
    _insert_decision(mock_conn, "DB decision", tags="db,infra")
    _insert_decision(mock_conn, "API decision", tags="api")

    from mait_code.tools.decisions.cli import cmd_list

    cmd_list(argparse.Namespace(all=True, tag="db", status=None))
    output = capsys.readouterr().out
    assert "DB decision" in output
    assert "API decision" not in output


def test_cmd_list_by_status(mock_conn, capsys):
    _insert_decision(mock_conn, "Accepted one", status="accepted")
    _insert_decision(mock_conn, "Proposed one", status="proposed")

    from mait_code.tools.decisions.cli import cmd_list

    cmd_list(argparse.Namespace(all=False, tag=None, status="proposed"))
    output = capsys.readouterr().out
    assert "Proposed one" in output
    assert "Accepted one" not in output


def test_cmd_list_empty(mock_conn, capsys):
    from mait_code.tools.decisions.cli import cmd_list

    cmd_list(argparse.Namespace(all=False, tag=None, status=None))
    output = capsys.readouterr().out
    assert "No decisions found" in output


def test_cmd_list_project_scoped(mock_conn, capsys):
    _insert_decision(mock_conn, "My decision", project=TEST_PROJECT)
    _insert_decision(mock_conn, "Other decision", project="other-project")

    from mait_code.tools.decisions.cli import cmd_list

    cmd_list(argparse.Namespace(all=True, tag=None, status=None))
    output = capsys.readouterr().out
    assert "My decision" in output
    assert "Other decision" not in output


def test_cmd_show(mock_conn, capsys):
    did = _insert_decision(
        mock_conn,
        "Use PostgreSQL",
        context="Need relational store",
        alternatives="MySQL",
        consequences="Hosting cost",
        tags="db",
    )

    from mait_code.tools.decisions.cli import cmd_show

    cmd_show(argparse.Namespace(id=did))
    output = capsys.readouterr().out
    assert "Use PostgreSQL" in output
    assert "Need relational store" in output
    assert "MySQL" in output
    assert "Hosting cost" in output
    assert "db" in output


def test_cmd_show_not_found(mock_conn):
    from mait_code.tools.decisions.cli import cmd_show

    with pytest.raises(SystemExit, match="1"):
        cmd_show(argparse.Namespace(id=999))


def test_cmd_amend(mock_conn, capsys):
    did = _insert_decision(mock_conn, "Original", context="Old context")

    from mait_code.tools.decisions.cli import cmd_amend

    cmd_amend(
        argparse.Namespace(
            id=did,
            context="New context",
            alternatives=None,
            consequences=None,
            status=None,
            tags=None,
        )
    )

    row = mock_conn.execute(
        "SELECT context, updated_at FROM decisions WHERE id = ?", (did,)
    ).fetchone()
    assert row[0] == "New context"
    assert row[1] is not None

    output = capsys.readouterr().out
    assert "amended" in output


def test_cmd_amend_nothing(mock_conn, capsys):
    did = _insert_decision(mock_conn, "Original")

    from mait_code.tools.decisions.cli import cmd_amend

    cmd_amend(
        argparse.Namespace(
            id=did,
            context=None,
            alternatives=None,
            consequences=None,
            status=None,
            tags=None,
        )
    )
    output = capsys.readouterr().out
    assert "Nothing to update" in output


def test_cmd_amend_not_found(mock_conn):
    from mait_code.tools.decisions.cli import cmd_amend

    with pytest.raises(SystemExit, match="1"):
        cmd_amend(
            argparse.Namespace(
                id=999,
                context="x",
                alternatives=None,
                consequences=None,
                status=None,
                tags=None,
            )
        )


def test_cmd_supersede(mock_conn, capsys):
    old_id = _insert_decision(mock_conn, "Old approach")
    new_id = _insert_decision(mock_conn, "New approach")

    from mait_code.tools.decisions.cli import cmd_supersede

    cmd_supersede(argparse.Namespace(old_id=old_id, new_id=new_id))

    row = mock_conn.execute(
        "SELECT status, superseded_by FROM decisions WHERE id = ?", (old_id,)
    ).fetchone()
    assert row[0] == "superseded"
    assert row[1] == new_id

    output = capsys.readouterr().out
    assert "superseded" in output


def test_cmd_supersede_old_not_found(mock_conn):
    new_id = _insert_decision(mock_conn, "New approach")

    from mait_code.tools.decisions.cli import cmd_supersede

    with pytest.raises(SystemExit, match="1"):
        cmd_supersede(argparse.Namespace(old_id=999, new_id=new_id))


def test_cmd_supersede_new_not_found(mock_conn):
    old_id = _insert_decision(mock_conn, "Old approach")

    from mait_code.tools.decisions.cli import cmd_supersede

    with pytest.raises(SystemExit, match="1"):
        cmd_supersede(argparse.Namespace(old_id=old_id, new_id=999))


def test_cmd_search(mock_conn, capsys):
    _insert_decision(mock_conn, "Use PostgreSQL", context="Relational data")
    _insert_decision(mock_conn, "Use Redis", context="Caching layer")

    from mait_code.tools.decisions.cli import cmd_search

    cmd_search(argparse.Namespace(query=["PostgreSQL"]))
    output = capsys.readouterr().out
    assert "PostgreSQL" in output
    assert "Redis" not in output


def test_cmd_search_empty_query(mock_conn):
    from mait_code.tools.decisions.cli import cmd_search

    with pytest.raises(SystemExit, match="1"):
        cmd_search(argparse.Namespace(query=["  "]))


def test_cmd_search_no_results(mock_conn, capsys):
    _insert_decision(mock_conn, "Use PostgreSQL")

    from mait_code.tools.decisions.cli import cmd_search

    cmd_search(argparse.Namespace(query=["nonexistent"]))
    output = capsys.readouterr().out
    assert "No matching decisions" in output


def test_cmd_remove(mock_conn, capsys):
    did = _insert_decision(mock_conn, "Remove me")

    from mait_code.tools.decisions.cli import cmd_remove

    cmd_remove(argparse.Namespace(id=did))

    row = mock_conn.execute(
        "SELECT id FROM decisions WHERE id = ?", (did,)
    ).fetchone()
    assert row is None

    output = capsys.readouterr().out
    assert "removed" in output


def test_cmd_remove_clears_superseded_by(mock_conn, capsys):
    """Removing a decision that others reference via superseded_by clears the FK."""
    old_id = _insert_decision(mock_conn, "Old approach")
    new_id = _insert_decision(mock_conn, "New approach")
    mock_conn.execute(
        "UPDATE decisions SET status = 'superseded', superseded_by = ? WHERE id = ?",
        (new_id, old_id),
    )
    mock_conn.commit()

    from mait_code.tools.decisions.cli import cmd_remove

    cmd_remove(argparse.Namespace(id=new_id))

    row = mock_conn.execute(
        "SELECT superseded_by FROM decisions WHERE id = ?", (old_id,)
    ).fetchone()
    assert row[0] is None


def test_cmd_remove_not_found(mock_conn):
    from mait_code.tools.decisions.cli import cmd_remove

    with pytest.raises(SystemExit, match="1"):
        cmd_remove(argparse.Namespace(id=999))


# --- Render tests ---


def test_render_empty(decisions_db: sqlite3.Connection):
    md = render_decisions_md(decisions_db)
    assert "No decisions recorded yet" in md
    assert "Auto-generated" in md


def test_render_basic(decisions_db: sqlite3.Connection):
    _insert_decision(
        decisions_db,
        "Use PostgreSQL",
        context="Need relational store",
        alternatives="MySQL",
        consequences="Hosting cost",
        tags="db,infra",
    )
    md = render_decisions_md(decisions_db)
    assert "DR-1: Use PostgreSQL" in md
    assert "### Context" in md
    assert "Need relational store" in md
    assert "### Alternatives considered" in md
    assert "MySQL" in md
    assert "### Consequences" in md
    assert "Hosting cost" in md
    assert "db,infra" in md


def test_render_omits_empty_fields(decisions_db: sqlite3.Connection):
    _insert_decision(decisions_db, "Simple decision")
    md = render_decisions_md(decisions_db)
    assert "DR-1: Simple decision" in md
    assert "### Context" not in md
    assert "### Alternatives" not in md
    assert "### Consequences" not in md


def test_render_superseded_strikethrough(decisions_db: sqlite3.Connection):
    old_id = _insert_decision(decisions_db, "Old approach", status="superseded")
    md = render_decisions_md(decisions_db)
    assert "~~Old approach~~" in md


def test_render_deprecated_strikethrough(decisions_db: sqlite3.Connection):
    _insert_decision(decisions_db, "Deprecated thing", status="deprecated")
    md = render_decisions_md(decisions_db)
    assert "~~Deprecated thing~~" in md


def test_render_superseded_by_link(decisions_db: sqlite3.Connection):
    old_id = _insert_decision(decisions_db, "Old approach")
    new_id = _insert_decision(decisions_db, "New approach")
    decisions_db.execute(
        "UPDATE decisions SET status = 'superseded', superseded_by = ? WHERE id = ?",
        (new_id, old_id),
    )
    decisions_db.commit()
    md = render_decisions_md(decisions_db)
    assert f"Superseded by:** DR-{new_id}" in md


def test_render_multiple_ordered(decisions_db: sqlite3.Connection):
    _insert_decision(decisions_db, "First decision")
    _insert_decision(decisions_db, "Second decision")
    md = render_decisions_md(decisions_db)
    assert md.index("DR-1") < md.index("DR-2")


def test_write_decisions_md_creates_file(decisions_db, tmp_path):
    """write_decisions_md creates docs/decisions.md at git root."""
    from mait_code.tools.decisions.render import write_decisions_md

    _insert_decision(decisions_db, "Test decision")
    with patch(
        "mait_code.tools.decisions.render._get_git_root", return_value=tmp_path
    ):
        write_decisions_md(decisions_db)

    docs_file = tmp_path / "docs" / "decisions.md"
    assert docs_file.exists()
    content = docs_file.read_text()
    assert "Test decision" in content


def test_write_decisions_md_skips_outside_git(decisions_db, tmp_path):
    """write_decisions_md does nothing when not in a git repo."""
    from mait_code.tools.decisions.render import write_decisions_md

    with patch(
        "mait_code.tools.decisions.render._get_git_root", return_value=None
    ):
        write_decisions_md(decisions_db)

    assert not (tmp_path / "docs" / "decisions.md").exists()
