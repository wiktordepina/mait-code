"""Tests for the channel interface and its concrete implementations."""

from __future__ import annotations

import json
import urllib.error

import pytest

from mait_code.bridge.base import BridgeChannel, OutboundMessage
from mait_code.bridge.loopback import LoopbackChannel
from mait_code.bridge.ntfy import NtfyChannel
from mait_code.bridge.registry import (
    CHANNELS,
    get_channel_class,
    selectable_channels,
)


# --- Registry ---------------------------------------------------------------


def test_registry_lists_both_channels():
    assert get_channel_class("ntfy") is NtfyChannel
    assert get_channel_class("loopback") is LoopbackChannel
    assert get_channel_class("nope") is None


def test_selectable_excludes_hidden_loopback():
    selectable = selectable_channels()
    assert NtfyChannel in selectable
    assert LoopbackChannel not in selectable  # hidden test double
    assert all(cls in CHANNELS.values() for cls in selectable)


def test_channel_is_abstract():
    with pytest.raises(TypeError):
        BridgeChannel()  # type: ignore[abstract]


# --- Loopback ---------------------------------------------------------------


def test_loopback_seed_drain_and_watermark():
    LoopbackChannel.seed("a", "b")
    chan = LoopbackChannel.from_config({})
    result = chan.drain(None)
    assert [c.body for c in result.captures] == ["a", "b"]
    assert result.watermark == "2"
    # Re-drain from the watermark yields nothing new (idempotent).
    assert chan.drain(result.watermark).captures == []


def test_loopback_named_queues_are_isolated():
    LoopbackChannel.seed("x", name="one")
    LoopbackChannel.seed("y", name="two")
    assert [c.body for c in LoopbackChannel(name="one").drain(None).captures] == ["x"]
    assert [c.body for c in LoopbackChannel(name="two").drain(None).captures] == ["y"]


def test_loopback_test_connection_reflects_health():
    chan = LoopbackChannel()
    assert chan.test_connection().ok is True
    LoopbackChannel.loop().healthy = False
    assert LoopbackChannel().test_connection().ok is False


def test_loopback_publish_records_messages():
    chan = LoopbackChannel()
    chan.publish(OutboundMessage(body="hi", title="t"))
    assert LoopbackChannel.loop().published[0].body == "hi"


def test_loopback_counts_drain_calls():
    chan = LoopbackChannel()
    chan.drain(None)
    chan.drain("0")
    assert LoopbackChannel.loop().drain_calls == 2


# --- ntfy: config -----------------------------------------------------------


def test_ntfy_config_schema_shape():
    keys = {f.key: f for f in NtfyChannel.config_schema()}
    assert set(keys) == {"server", "capture_topic", "token"}
    assert keys["token"].secret is True
    assert keys["token"].required is False
    assert keys["server"].required is True


def test_ntfy_from_config_requires_server_and_topic():
    with pytest.raises(ValueError, match="server"):
        NtfyChannel.from_config({"capture_topic": "t"})
    with pytest.raises(ValueError, match="capture topic"):
        NtfyChannel.from_config({"server": "https://x"})


def test_ntfy_from_config_strips_and_trims_slash():
    chan = NtfyChannel.from_config(
        {"server": "https://x/ ".strip(), "capture_topic": " cap ", "token": " tk "}
    )
    assert chan.server == "https://x"
    assert chan.capture_topic == "cap"
    assert chan.token == "tk"


# --- ntfy: HTTP paths (mocked urlopen) --------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _patch_urlopen(monkeypatch, handler):
    monkeypatch.setattr("urllib.request.urlopen", handler)


def test_ntfy_test_connection_ok(monkeypatch):
    _patch_urlopen(monkeypatch, lambda req, timeout=0: _FakeResponse(b""))
    chan = NtfyChannel(server="https://x", capture_topic="cap")
    result = chan.test_connection()
    assert result.ok is True
    assert "cap" in result.message


def test_ntfy_test_connection_auth_failure(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None)

    _patch_urlopen(monkeypatch, boom)
    result = NtfyChannel(server="https://x", capture_topic="cap").test_connection()
    assert result.ok is False
    assert "authentication" in result.message


def test_ntfy_test_connection_server_error(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError("https://x", 500, "Boom", {}, None)

    _patch_urlopen(monkeypatch, boom)
    result = NtfyChannel(server="https://x", capture_topic="cap").test_connection()
    assert result.ok is False
    assert "500" in result.message


def test_ntfy_test_connection_unreachable(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.URLError("name resolution failed")

    _patch_urlopen(monkeypatch, boom)
    result = NtfyChannel(server="https://x", capture_topic="cap").test_connection()
    assert result.ok is False
    assert "cannot reach" in result.message


def _ndjson(*events: dict) -> bytes:
    return "\n".join(json.dumps(e) for e in events).encode("utf-8")


def test_ntfy_drain_parses_messages_and_watermark(monkeypatch):
    body = _ndjson(
        {"id": "a1", "event": "open"},
        {"id": "a2", "event": "message", "message": "hello"},
        {"id": "a3", "event": "message", "message": "world"},
        {"id": "a4", "event": "keepalive"},
    )
    _patch_urlopen(monkeypatch, lambda req, timeout=0: _FakeResponse(body))
    result = NtfyChannel(server="https://x", capture_topic="cap").drain(None)
    assert [c.body for c in result.captures] == ["hello", "world"]
    assert result.watermark == "a4"


def test_ntfy_drain_skips_inclusive_since_marker(monkeypatch):
    body = _ndjson(
        {"id": "a2", "event": "message", "message": "old"},
        {"id": "a3", "event": "message", "message": "new"},
    )
    _patch_urlopen(monkeypatch, lambda req, timeout=0: _FakeResponse(body))
    result = NtfyChannel(server="https://x", capture_topic="cap").drain("a2")
    assert [c.body for c in result.captures] == ["new"]


def test_ntfy_publish_posts_with_headers(monkeypatch):
    captured = {}

    def handler(req, timeout=0):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["data"] = req.data
        captured["title"] = req.get_header("Title")
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(b"")

    _patch_urlopen(monkeypatch, handler)
    chan = NtfyChannel(server="https://x", capture_topic="cap", token="tk")
    chan.publish(OutboundMessage(body="ping", title="Reminder"))
    assert captured["url"] == "https://x/cap"
    assert captured["method"] == "POST"
    assert captured["data"] == b"ping"
    assert captured["title"] == "Reminder"
    assert captured["auth"] == "Bearer tk"
