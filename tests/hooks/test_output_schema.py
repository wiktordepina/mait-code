"""Shared contract test for hook stdout payloads.

Two layers:

* unit tests pin down ``validate_hook_output`` itself — including the exact
  0.25.3 regression (``hookSpecificOutput`` with no ``hookEventName``); and
* integration tests drive each real hook's ``main()`` and push its actual
  stdout through the validator, so a new or changed hook is held to the
  contract without writing a bespoke shape assertion per hook.
"""

import io
import json
import logging

import pytest

import mait_code.hooks.auto_format.cli as auto_format_cli
import mait_code.hooks.session_start.cli as session_start_cli
from tests.hooks.hook_schema import validate_hook_output


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Drop file handlers that ``@log_invocation`` adds to the global logger."""
    logger = logging.getLogger("mait_code")
    original = logger.handlers[:]
    yield
    for handler in logger.handlers[:]:
        if handler not in original:
            logger.removeHandler(handler)
    logger.handlers = original


# --- validator unit tests ---------------------------------------------------


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "   \n",
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "hi",
                }
            }
        ),
        json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart"}}),
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "ok",
                }
            }
        ),
        # No hookSpecificOutput — other documented top-level keys are not our concern.
        json.dumps({"continue": True, "systemMessage": "noted"}),
    ],
)
def test_valid_payloads_pass(stdout):
    validate_hook_output(stdout)


def test_missing_hook_event_name_is_rejected():
    """The 0.25.3 regression: a payload with no hookEventName must fail."""
    bad = json.dumps({"hookSpecificOutput": {"additionalContext": "hi"}})
    with pytest.raises(AssertionError, match="hookEventName"):
        validate_hook_output(bad)


def test_wrong_context_key_is_rejected():
    """The other half of the regression: ``context`` instead of ``additionalContext``."""
    bad = json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "context": "hi"}}
    )
    with pytest.raises(AssertionError, match="unexpected field"):
        validate_hook_output(bad)


@pytest.mark.parametrize(
    ("stdout", "match"),
    [
        (
            json.dumps({"hookSpecificOutput": {"hookEventName": "Nope"}}),
            "unknown hookEventName",
        ),
        (json.dumps({"hookSpecificOutput": {"hookEventName": 1}}), "must be a string"),
        (json.dumps({"hookSpecificOutput": []}), "must be an object"),
        (json.dumps([1, 2, 3]), "must be a JSON object"),
        (
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": 3,
                    }
                }
            ),
            "additionalContext must be a string",
        ),
        ("{not json", "not valid JSON"),
    ],
)
def test_invalid_payloads_are_rejected(stdout, match):
    with pytest.raises(AssertionError, match=match):
        validate_hook_output(stdout)


# --- real hooks honour the contract -----------------------------------------


def test_session_start_output_is_valid(monkeypatch, capsys):
    monkeypatch.setattr(session_start_cli, "_check_reminders", lambda: "")
    monkeypatch.setattr(session_start_cli, "_check_tasks", lambda: "")
    monkeypatch.setattr(
        session_start_cli, "_check_board", lambda: "2 refined · 1 blocked"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    session_start_cli.main()

    validate_hook_output(capsys.readouterr().out)


def test_session_start_emits_nothing_when_empty(monkeypatch, capsys):
    """With no sections the hook prints nothing — still contract-valid."""
    monkeypatch.setattr(session_start_cli, "_check_reminders", lambda: "")
    monkeypatch.setattr(session_start_cli, "_check_tasks", lambda: "")
    monkeypatch.setattr(session_start_cli, "_check_board", lambda: "")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    session_start_cli.main()

    out = capsys.readouterr().out
    assert out.strip() == ""
    validate_hook_output(out)


def test_auto_format_output_is_valid(capsys):
    """auto-format injects no context today; guards it if that ever changes."""
    auto_format_cli.main()
    validate_hook_output(capsys.readouterr().out)
