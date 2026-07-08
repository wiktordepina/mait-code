"""ntfy channel — the first concrete Bridge transport.

`ntfy <https://ntfy.sh>`_ is plain HTTP pub/sub: publishing is a POST, draining
is a polled GET of a topic's cached NDJSON stream. Because the server caches
messages, mait-code stays daemon-free — the drain reads what accumulated since
the last watermark and stops. Self-hostable as a single container, which is the
intended deployment (a private topic on the home server).

HTTP is stdlib ``urllib`` with the OS trust store injected via
:func:`mait_code.ssl.setup_ssl` (corporate-proxy friendly, no extra deps),
mirroring :mod:`mait_code.tools.web_fetch`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence

from mait_code.bridge.base import (
    BridgeChannel,
    Capture,
    ConfigField,
    DrainResult,
    OutboundMessage,
    TestResult,
)

__all__ = ["NtfyChannel"]

_TIMEOUT = 15  # seconds; a poll should be quick or not block a session


class NtfyChannel(BridgeChannel):
    """Publish/drain a private ntfy topic over HTTP."""

    type_id = "ntfy"
    display_name = "ntfy"

    def __init__(self, *, server: str, capture_topic: str, token: str = "") -> None:
        self.server = server.rstrip("/")
        self.capture_topic = capture_topic
        self.token = token

    # -- Identity & config -------------------------------------------------

    @classmethod
    def config_schema(cls) -> Sequence[ConfigField]:
        return (
            ConfigField(
                "server",
                "Server URL",
                help="Base URL of the ntfy server, e.g. https://ntfy.example.org",
                placeholder="https://ntfy.example.org",
            ),
            ConfigField(
                "capture_topic",
                "Capture topic",
                help="The private topic captures are published to and drained from.",
                placeholder="mait-capture",
            ),
            ConfigField(
                "token",
                "Access token",
                help="Bearer token for a protected topic. Leave blank if open.",
                secret=True,
                required=False,
                placeholder="tk_…",
            ),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, str]) -> NtfyChannel:
        server = (config.get("server") or "").strip()
        capture_topic = (config.get("capture_topic") or "").strip()
        if not server:
            raise ValueError("ntfy: server URL is required")
        if not capture_topic:
            raise ValueError("ntfy: capture topic is required")
        return cls(
            server=server,
            capture_topic=capture_topic,
            token=(config.get("token") or "").strip(),
        )

    # -- HTTP helpers ------------------------------------------------------

    def _request(self, req: urllib.request.Request) -> bytes:
        """Perform a request with SSL set up and auth applied; return the body."""
        from mait_code.ssl import setup_ssl

        setup_ssl()
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()

    # -- Verbs -------------------------------------------------------------

    def test_connection(self) -> TestResult:
        """Poll the topic with a tiny window to prove reachability + auth."""
        url = f"{self.server}/{self.capture_topic}/json?poll=1&since=10s"
        try:
            self._request(urllib.request.Request(url, method="GET"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return TestResult(False, f"authentication failed (HTTP {exc.code})")
            return TestResult(False, f"server returned HTTP {exc.code}")
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return TestResult(False, f"cannot reach {self.server}: {reason}")
        except Exception as exc:  # defensive: test must never raise
            return TestResult(False, f"unexpected error: {exc}")
        return TestResult(True, f"connected to {self.server}/{self.capture_topic}")

    def drain(self, since: str | None) -> DrainResult:
        """Poll messages published since the watermark (a message id, or 'all')."""
        marker = since or "all"
        url = f"{self.server}/{self.capture_topic}/json?poll=1&since={marker}"
        body = self._request(urllib.request.Request(url, method="GET"))

        captures: list[Capture] = []
        last_id: str | None = None
        for line in body.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            msg_id = str(event.get("id", ""))
            # ntfy's `since=<id>` is inclusive of the marker message — skip it
            # so a re-drain from the same watermark yields nothing.
            if since and msg_id == since:
                continue
            if event.get("event") != "message":
                last_id = msg_id or last_id
                continue
            text = event.get("message", "")
            if text:
                captures.append(Capture(body=text, external_id=msg_id))
            last_id = msg_id or last_id
        return DrainResult(captures=captures, watermark=last_id or since)

    def publish(self, message: OutboundMessage) -> None:
        """POST a notification to the topic. (Reminders half — #78.)"""
        url = f"{self.server}/{self.capture_topic}"
        req = urllib.request.Request(
            url, data=message.body.encode("utf-8"), method="POST"
        )
        if message.title:
            req.add_header("Title", message.title)
        self._request(req)
