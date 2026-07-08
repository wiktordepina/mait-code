"""Tests for the Bridge control-message protocol."""

from __future__ import annotations

import pytest

from mait_code.bridge import control


def test_dismiss_command_round_trips():
    body = control.dismiss_command(42)
    cmd = control.parse(body)
    assert cmd is not None
    assert cmd.action == "dismiss"
    assert cmd.reminder_id == 42


@pytest.mark.parametrize(
    "body",
    [
        "ring the vet",  # ordinary capture
        "",  # empty
        "mait-ctl:dismiss:",  # missing id
        "mait-ctl:dismiss:abc",  # non-numeric id
        "mait-ctl:snooze:5",  # unknown verb
        "mait-ctl:dismiss:5:6",  # too many parts
        "dismiss:5",  # missing prefix
    ],
)
def test_parse_returns_none_for_non_control(body):
    assert control.parse(body) is None
