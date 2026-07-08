"""Bridge configuration and per-machine state.

Two small JSON files under the data dir, kept separate on purpose:

* ``bridge.json`` — the *user's* channel config (server, topics, token), keyed
  per channel type so divergent schemas coexist. This is the tier that could
  one day sync between machines.
* ``bridge-state.json`` — the *machine's* drain watermark. Per-machine and
  never synced: two laptops draining the same topic each track their own
  position.

The enable gate (``bridge``) and channel selector (``bridge-type``) are
first-class settings in :mod:`mait_code.config`, so they resolve env → file →
default and are visible to ``doctor`` like every other knob.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mait_code import config as _config
from mait_code.bridge.base import BridgeChannel
from mait_code.bridge.registry import get_channel_class

logger = logging.getLogger(__name__)

__all__ = [
    # Gate & selection
    "bridge_enabled",
    "active_type",
    # Config I/O
    "load_channel_config",
    "save_channel_config",
    # Watermark
    "get_watermark",
    "set_watermark",
    # Channel construction
    "build_channel",
    "active_channel",
    # Health
    "missing_required",
    "config_problems",
]

_CONFIG_FILE = "bridge.json"
_STATE_FILE = "bridge-state.json"


# ---------------------------------------------------------------------------
# Gate & selection (delegated to the settings registry)
# ---------------------------------------------------------------------------


def bridge_enabled() -> bool:
    """Whether the Bridge is switched on. Off by default — the safety spine."""
    return _config.get_bool("bridge")


def active_type() -> str:
    """The selected channel type id (``bridge-type``)."""
    return _config.get("bridge-type").strip()


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _read_json(name: str) -> dict:
    path = _config.data_dir() / name
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("bridge: %s is unreadable; treating as empty", name)
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(name: str, data: dict) -> Path:
    path = _config.data_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------------------
# Channel config
# ---------------------------------------------------------------------------


def load_channel_config(type_id: str) -> dict[str, str]:
    """Return the stored config for one channel type (``{}`` if none)."""
    section = _read_json(_CONFIG_FILE).get(type_id, {})
    if not isinstance(section, dict):
        return {}
    return {k: str(v) for k, v in section.items() if isinstance(v, str)}


def save_channel_config(type_id: str, values: dict[str, str]) -> None:
    """Persist config for one channel type, leaving other channels untouched."""
    data = _read_json(_CONFIG_FILE)
    data[type_id] = {k: v for k, v in values.items() if v != ""}
    _write_json(_CONFIG_FILE, data)


# ---------------------------------------------------------------------------
# Per-machine watermark
# ---------------------------------------------------------------------------


def get_watermark(type_id: str) -> str | None:
    """Return the last drain watermark for a channel on this machine."""
    section = _read_json(_STATE_FILE).get(type_id, {})
    if isinstance(section, dict):
        wm = section.get("watermark")
        return wm if isinstance(wm, str) else None
    return None


def set_watermark(type_id: str, watermark: str) -> None:
    """Record the drain watermark for a channel on this machine."""
    data = _read_json(_STATE_FILE)
    section = data.get(type_id)
    if not isinstance(section, dict):
        section = {}
    section["watermark"] = watermark
    data[type_id] = section
    _write_json(_STATE_FILE, data)


# ---------------------------------------------------------------------------
# Channel construction & health
# ---------------------------------------------------------------------------


def build_channel(type_id: str, values: dict[str, str]) -> BridgeChannel:
    """Construct a channel from *values*.

    Raises:
        ValueError: If *type_id* is unregistered or the config is incomplete.
    """
    cls = get_channel_class(type_id)
    if cls is None:
        raise ValueError(f"unknown bridge channel type: {type_id!r}")
    return cls.from_config(values)


def active_channel() -> BridgeChannel:
    """Build the currently-selected channel from its stored config.

    Raises:
        ValueError: If the type is unknown or its config is incomplete.
    """
    type_id = active_type()
    return build_channel(type_id, load_channel_config(type_id))


def missing_required(type_id: str, values: dict[str, str]) -> list[str]:
    """Return the labels of required config fields left blank."""
    cls = get_channel_class(type_id)
    if cls is None:
        return []
    return [
        f.label
        for f in cls.config_schema()
        if f.required and not (values.get(f.key) or "").strip()
    ]


def config_problems() -> list[str]:
    """Human-readable configuration problems for ``doctor`` (empty when healthy).

    Only meaningful when the gate is on: a disabled Bridge needs no config.
    """
    if not bridge_enabled():
        return []
    type_id = active_type()
    cls = get_channel_class(type_id)
    if cls is None:
        return [f"bridge-type {type_id!r} is not a known channel"]
    missing = missing_required(type_id, load_channel_config(type_id))
    if missing:
        return [
            f"bridge is enabled but {cls.display_name} config is incomplete: "
            f"missing {', '.join(missing)}"
        ]
    return []
