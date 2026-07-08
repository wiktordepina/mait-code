"""Tests for Bridge config, watermark state, and channel construction."""

from __future__ import annotations

import pytest

from mait_code.bridge import config as bc


# --- Gate & selection -------------------------------------------------------


def test_gate_off_by_default():
    assert bc.bridge_enabled() is False


def test_gate_and_type_from_env(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "loopback")
    assert bc.bridge_enabled() is True
    assert bc.active_type() == "loopback"


# --- Channel config I/O -----------------------------------------------------


def test_channel_config_round_trips():
    bc.save_channel_config("ntfy", {"server": "https://x", "capture_topic": "cap"})
    assert bc.load_channel_config("ntfy") == {
        "server": "https://x",
        "capture_topic": "cap",
    }


def test_save_strips_empty_values():
    bc.save_channel_config("ntfy", {"server": "https://x", "token": ""})
    assert bc.load_channel_config("ntfy") == {"server": "https://x"}


def test_save_leaves_other_channels_untouched():
    bc.save_channel_config("ntfy", {"server": "https://x"})
    bc.save_channel_config("loopback", {"name": "q"})
    assert bc.load_channel_config("ntfy") == {"server": "https://x"}
    assert bc.load_channel_config("loopback") == {"name": "q"}


def test_load_missing_channel_is_empty():
    assert bc.load_channel_config("ntfy") == {}


def test_malformed_config_file_treated_as_empty(monkeypatch):
    from mait_code import config as core

    (core.data_dir() / "bridge.json").parent.mkdir(parents=True, exist_ok=True)
    (core.data_dir() / "bridge.json").write_text("{ not json", encoding="utf-8")
    assert bc.load_channel_config("ntfy") == {}


# --- Watermark --------------------------------------------------------------


def test_watermark_round_trips():
    assert bc.get_watermark("ntfy") is None
    bc.set_watermark("ntfy", "a7")
    assert bc.get_watermark("ntfy") == "a7"
    bc.set_watermark("ntfy", "a8")
    assert bc.get_watermark("ntfy") == "a8"


def test_watermark_is_per_channel():
    bc.set_watermark("ntfy", "n1")
    bc.set_watermark("loopback", "l1")
    assert bc.get_watermark("ntfy") == "n1"
    assert bc.get_watermark("loopback") == "l1"


# --- Channel construction ---------------------------------------------------


def test_build_channel_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown bridge channel"):
        bc.build_channel("nope", {})


def test_active_channel_builds_from_stored_config(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")
    bc.save_channel_config("ntfy", {"server": "https://x", "capture_topic": "cap"})
    chan = bc.active_channel()
    assert chan.server == "https://x"  # type: ignore[attr-defined]


def test_active_channel_incomplete_raises(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")
    with pytest.raises(ValueError):
        bc.active_channel()


# --- Health -----------------------------------------------------------------


def test_missing_required_reports_blank_fields():
    missing = bc.missing_required("ntfy", {"token": "x"})
    assert missing == ["Server URL", "Capture topic"]
    assert bc.missing_required("nope", {}) == []


def test_config_problems_silent_when_disabled():
    assert bc.config_problems() == []


def test_config_problems_flags_incomplete_when_enabled(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")
    problems = bc.config_problems()
    assert problems and "incomplete" in problems[0]


def test_config_problems_flags_unknown_type(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "nope")
    assert bc.config_problems() == ["bridge-type 'nope' is not a known channel"]


def test_config_problems_clean_when_configured(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")
    bc.save_channel_config("ntfy", {"server": "https://x", "capture_topic": "cap"})
    assert bc.config_problems() == []
