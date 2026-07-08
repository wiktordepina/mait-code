"""Tests for the boolean gate accessor, its validators, and the doctor check."""

from __future__ import annotations

import pytest

from mait_code import config
from mait_code.cli._doctor import _check_bridge


# --- get_bool ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("enabled", True),
        ("disabled", False),
        ("true", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("on", True),
        ("off", False),
        ("ENABLED", True),
    ],
)
def test_get_bool_coercions(monkeypatch, value, expected):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", value)
    assert config.get_bool("bridge") is expected


def test_get_bool_default_is_false():
    assert config.get_bool("bridge") is False


def test_get_bool_garbage_falls_back_to_default(monkeypatch, caplog):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "maybe")
    assert config.get_bool("bridge") is False  # default 'disabled'
    assert "not a boolean" in caplog.text


# --- Validators (run by doctor via validate_settings) -----------------------


def test_valid_defaults_pass_validation():
    errors = config.validate_settings()
    assert not [e for e in errors if e.startswith("bridge")]


def test_bad_gate_value_flagged(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "sometimes")
    errors = config.validate_settings()
    assert any(e.startswith("bridge:") for e in errors)


def test_unknown_channel_type_flagged(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "smoke-signals")
    errors = config.validate_settings()
    assert any("bridge-type" in e for e in errors)


# --- Doctor check -----------------------------------------------------------


def test_doctor_ok_when_disabled():
    check = _check_bridge()
    assert check.level == "ok"
    assert "disabled" in check.message


def test_doctor_warns_when_enabled_but_incomplete(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")
    check = _check_bridge()
    assert check.level == "warn"
    assert "incomplete" in check.message
    assert check.fix_hint


def test_doctor_ok_when_enabled_and_configured(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")
    from mait_code.bridge import config as bc

    bc.save_channel_config("ntfy", {"server": "https://x", "capture_topic": "cap"})
    check = _check_bridge()
    assert check.level == "ok"
    assert "enabled" in check.message
