"""Tests for the session-start hook — board summary and context assembly."""

import io
import json
import logging
from types import SimpleNamespace

import pytest

import mait_code.hooks.session_start.cli as cli_mod
from mait_code.hooks.session_start.cli import _check_board, main


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Restore the mait_code logger's handlers after each test.

    Calling ``main()`` runs the ``@log_invocation`` decorator, which invokes
    ``setup_logging()`` and adds a file handler to the global ``mait_code``
    logger. Without this, that handler leaks into ``tests/test_logging.py``.
    """
    logger = logging.getLogger("mait_code")
    original = logger.handlers[:]
    yield
    for handler in logger.handlers[:]:
        if handler not in original:
            logger.removeHandler(handler)
    logger.handlers = original


def _fake_run_factory(stdout="", raises=None):
    def fake_run(*_args, **_kwargs):
        if raises is not None:
            raise raises
        return SimpleNamespace(stdout=stdout)

    return fake_run


def _counts(**kwargs):
    base = {
        "backlog": 0,
        "refined": 0,
        "in_progress": 0,
        "blocked": 0,
        "done": 0,
    }
    base.update(kwargs)
    return json.dumps({"project": "p", "counts": base})


# --- _check_board ---


def test_check_board_summarises_live_columns(monkeypatch):
    monkeypatch.setattr(
        cli_mod.subprocess,
        "run",
        _fake_run_factory(_counts(refined=3, in_progress=1, done=9)),
    )
    out = _check_board()
    assert out == "3 refined · 1 in progress"
    assert "done" not in out  # done is not actionable at session start


def test_check_board_empty_when_only_done(monkeypatch):
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(_counts(done=5)))
    assert _check_board() == ""


def test_check_board_empty_when_no_cards(monkeypatch):
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory(_counts()))
    assert _check_board() == ""


def test_check_board_tool_missing(monkeypatch):
    monkeypatch.setattr(
        cli_mod.subprocess, "run", _fake_run_factory(raises=FileNotFoundError())
    )
    assert _check_board() == ""


def test_check_board_bad_json(monkeypatch):
    monkeypatch.setattr(cli_mod.subprocess, "run", _fake_run_factory("not json"))
    assert _check_board() == ""


# --- main() integration ---


def test_main_includes_board_section(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_check_reminders", lambda: "")
    monkeypatch.setattr(cli_mod, "_check_board", lambda: "2 refined · 1 blocked")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    main()

    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "## Board" in context
    assert "2 refined · 1 blocked" in context


def test_main_silent_when_nothing(monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "_check_reminders", lambda: "")
    monkeypatch.setattr(cli_mod, "_check_board", lambda: "")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    main()

    assert capsys.readouterr().out == ""
