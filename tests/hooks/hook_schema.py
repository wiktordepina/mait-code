"""Shared validator for Claude Code hook stdout payloads.

Hooks may print a JSON object to stdout to feed structured output back into the
session. The part most prone to drift is ``hookSpecificOutput``: Claude Code
rejects the whole payload if it omits ``hookEventName`` or carries fields that
don't belong to the named event. A 0.25.3 regression shipped a session-start
hook that emitted ``{"context": ...}`` with no ``hookEventName`` — the payload
was silently rejected and the companion context never reached the session.

``validate_hook_output`` encodes that contract once so every hook can be checked
against it (see ``test_output_schema.py``), rather than each hook test asserting
its own ad-hoc shape — which is precisely how the regression slipped through CI.
"""

import json

# Event names a hook may declare, mapped to the fields each event permits
# alongside the required ``hookEventName``. Sourced from the Claude Code hooks
# reference. Extend this table when adopting a new hook event rather than
# loosening the validator.
_ALLOWED_FIELDS: dict[str, set[str]] = {
    "SessionStart": {"additionalContext"},
    "UserPromptSubmit": {"additionalContext"},
    "PostToolUse": {"additionalContext"},
    "PreToolUse": {"permissionDecision", "permissionDecisionReason"},
}

# Fields whose value must be a string when present.
_STRING_FIELDS = {
    "additionalContext",
    "permissionDecision",
    "permissionDecisionReason",
}


def validate_hook_output(stdout: str) -> None:
    """Assert that a hook's stdout conforms to the Claude Code output contract.

    Empty or whitespace-only output is valid — a hook that injects nothing is
    free to print nothing. Any non-empty output must be a single JSON object,
    and if it carries ``hookSpecificOutput`` that object must name a known event
    via ``hookEventName`` and carry only fields permitted for that event.

    Args:
        stdout: The raw text a hook wrote to stdout.

    Raises:
        AssertionError: If the payload violates the contract.
    """
    if not stdout.strip():
        return

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - message clarity
        raise AssertionError(
            f"hook stdout is not valid JSON: {exc}\n{stdout!r}"
        ) from exc

    assert isinstance(payload, dict), (
        f"hook output must be a JSON object, got {type(payload).__name__}"
    )

    if "hookSpecificOutput" not in payload:
        return

    hso = payload["hookSpecificOutput"]
    assert isinstance(hso, dict), (
        f"hookSpecificOutput must be an object, got {type(hso).__name__}"
    )

    assert "hookEventName" in hso, (
        'hookSpecificOutput is missing required field "hookEventName"'
    )

    event = hso["hookEventName"]
    assert isinstance(event, str), (
        f"hookEventName must be a string, got {type(event).__name__}"
    )
    assert event in _ALLOWED_FIELDS, (
        f"unknown hookEventName {event!r}; expected one of {sorted(_ALLOWED_FIELDS)}"
    )

    permitted = _ALLOWED_FIELDS[event] | {"hookEventName"}
    extra = set(hso) - permitted
    assert not extra, (
        f"hookSpecificOutput for {event} has unexpected field(s) {sorted(extra)}; "
        f"permitted: {sorted(permitted)}"
    )

    for field in _STRING_FIELDS & set(hso):
        assert isinstance(hso[field], str), (
            f"hookSpecificOutput.{field} must be a string, got {type(hso[field]).__name__}"
        )
