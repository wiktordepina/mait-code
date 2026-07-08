"""Tests for the outbound half: publish due reminders + the dismiss round-trip."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mait_code.bridge import control
from mait_code.bridge import service
from mait_code.bridge.loopback import LoopbackChannel
from mait_code.tools.reminders.db import connection as reminders_connection


def _add_reminder(what: str, *, overdue: bool = True) -> int:
    when = datetime.now(timezone.utc) + timedelta(hours=-1 if overdue else 1)
    with reminders_connection() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (what, due, created_at) VALUES (?, ?, ?)",
            (what, when.isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def _is_dismissed(reminder_id: int) -> bool:
    with reminders_connection() as conn:
        row = conn.execute(
            "SELECT dismissed FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    return bool(row and row[0])


# --- Gate ------------------------------------------------------------------


def test_publish_disabled_makes_no_channel_call():
    _add_reminder("vet")
    outcome = service.publish_due_reminders()
    assert outcome.status == "disabled"
    assert LoopbackChannel.loop().published == []


# --- Publishing ------------------------------------------------------------


def test_publishes_overdue_reminders_once(bridge_on):
    rid = _add_reminder("ring the vet")
    _add_reminder("future thing", overdue=False)  # not yet due — skipped

    outcome = service.publish_due_reminders()
    assert outcome.status == "ok"
    assert outcome.count == 1
    published = LoopbackChannel.loop().published
    assert len(published) == 1
    assert published[0].body == "ring the vet"
    # Carries a Done action that round-trips a dismiss for this reminder.
    action = published[0].actions[0]
    assert action["label"] == "Done"
    assert action["control"] == control.dismiss_command(rid)

    # Publishing again re-sends nothing (notified_at was stamped).
    assert service.publish_due_reminders().count == 0
    assert len(LoopbackChannel.loop().published) == 1


def test_publish_unconfigured_channel(monkeypatch):
    monkeypatch.setenv("MAIT_CODE_BRIDGE", "enabled")
    monkeypatch.setenv("MAIT_CODE_BRIDGE_TYPE", "ntfy")  # no config saved
    _add_reminder("vet")
    outcome = service.publish_due_reminders()
    assert outcome.status == "unconfigured"


def test_publish_missing_notify_topic_is_unconfigured(monkeypatch, bridge_on):
    # A channel that raises ValueError on publish (like ntfy with no notify
    # topic) is a config problem, not an error.
    class _NoNotify(LoopbackChannel):
        def publish(self, message):
            raise ValueError("ntfy: notify topic is not configured")

    from mait_code.bridge import config as bc

    monkeypatch.setattr(bc, "active_channel", lambda: _NoNotify())
    _add_reminder("vet")
    outcome = service.publish_due_reminders()
    assert outcome.status == "unconfigured"


def test_publish_swallows_transport_error(monkeypatch, bridge_on):
    class _Boom(LoopbackChannel):
        def publish(self, message):
            raise RuntimeError("network fell over")

    from mait_code.bridge import config as bc

    monkeypatch.setattr(bc, "active_channel", lambda: _Boom())
    _add_reminder("vet")
    outcome = service.publish_due_reminders()
    assert outcome.status == "error"
    assert "network fell over" in outcome.detail


# --- The full round-trip ---------------------------------------------------


def test_done_control_message_dismisses_via_drain(bridge_on):
    rid = _add_reminder("ring the vet")
    service.publish_due_reminders()
    assert not _is_dismissed(rid)

    # Simulate the phone's "Done" button: the control message lands on the
    # capture topic and the next drain acts on it instead of filing it.
    LoopbackChannel.seed(control.dismiss_command(rid))
    outcome = service.run_drain()

    assert outcome.dismissed == 1
    assert outcome.count == 0  # not filed as an inbox item
    assert _is_dismissed(rid)


def test_dismiss_control_is_idempotent_and_safe(bridge_on):
    rid = _add_reminder("thing")
    # A duplicate dismiss and an unknown id both no-op without error.
    LoopbackChannel.seed(control.dismiss_command(rid), control.dismiss_command(9999))
    service.run_drain()
    LoopbackChannel.seed(control.dismiss_command(rid))  # again
    outcome = service.run_drain()
    assert outcome.status == "ok"
    assert _is_dismissed(rid)


def test_captures_and_controls_are_separated_in_one_drain(bridge_on):
    rid = _add_reminder("thing")
    LoopbackChannel.seed("a real capture", control.dismiss_command(rid), "another")
    outcome = service.run_drain()
    assert outcome.count == 2  # two captures filed
    assert outcome.dismissed == 1  # one reminder dismissed
    assert _is_dismissed(rid)
