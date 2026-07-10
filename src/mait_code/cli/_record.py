"""Install record &mdash; what ``mait-code install`` persists for later commands.

The install record is a JSON document at
:func:`~mait_code.cli._paths.install_record_path` that captures enough
state for ``update`` / ``uninstall`` / ``status`` / ``doctor`` to do
their jobs without re-prompting the user. It is created by ``install``,
updated by ``update``, and removed by ``uninstall``.

Schema is versioned via :data:`SCHEMA_VERSION` so we can evolve it
without breaking older binaries reading newer records (or vice versa).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mait_code.cli._paths import install_record_path

__all__ = [
    "SCHEMA_VERSION",
    "InstallRecord",
    "RecordError",
    "read_record",
    "write_record",
]

SCHEMA_VERSION = 2


class RecordError(Exception):
    """Raised when the install record is missing, malformed, or from a
    schema version this binary doesn't understand."""


@dataclass
class InstallRecord:
    """Persisted state about a mait-code install.

    Attributes:
        source_dir: Absolute path to the cloned source tree.
        first_installed_at: ISO 8601 UTC timestamp of the *first* install.
            Frozen at install time and preserved across every ``update``.
        updated_at: ISO 8601 UTC timestamp of the most recent
            install / update. Refreshed on every ``update``.
        schema_version: Format version of this record. See
            :data:`SCHEMA_VERSION`.
    """

    source_dir: str
    first_installed_at: str
    updated_at: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        source_dir: Path | str,
        first_installed_at: str | None = None,
    ) -> InstallRecord:
        """Construct a record stamped with the current UTC time.

        Args:
            source_dir: The cloned source tree.
            first_installed_at: Preserve an earlier first-install
                timestamp (passed by ``update`` to keep the original
                date across reinstalls). When ``None`` (a fresh
                install), it defaults to now, matching ``updated_at``.
        """
        now = datetime.now(UTC).isoformat(timespec="seconds")
        return cls(
            source_dir=str(Path(source_dir).resolve()),
            first_installed_at=first_installed_at or now,
            updated_at=now,
        )


def write_record(record: InstallRecord, *, path: Path | None = None) -> Path:
    """Persist ``record`` to disk, creating parent directories as needed.

    Args:
        record: The :class:`InstallRecord` to write.
        path: Override target path (defaults to
            :func:`~mait_code.cli._paths.install_record_path`).

    Returns:
        The path the record was written to.
    """
    target = path if path is not None else install_record_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(record), indent=2) + "\n", encoding="utf-8")
    return target


def read_record(*, path: Path | None = None) -> InstallRecord:
    """Read the install record from disk.

    Args:
        path: Override source path (defaults to
            :func:`~mait_code.cli._paths.install_record_path`).

    Returns:
        The deserialised :class:`InstallRecord`.

    Raises:
        RecordError: If the file is missing, malformed JSON, missing a
            required field, or has a ``schema_version`` this binary
            doesn't understand.
    """
    target = path if path is not None else install_record_path()
    if not target.exists():
        raise RecordError(
            f"No install record at {target}. Run `mait-code install` first."
        )

    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecordError(
            f"Install record at {target} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise RecordError(f"Install record at {target} is not a JSON object.")

    schema_version = raw.get("schema_version", 1)
    if schema_version > SCHEMA_VERSION:
        raise RecordError(
            f"Install record at {target} has schema_version={schema_version}, "
            f"but this binary only understands up to {SCHEMA_VERSION}. "
            f"Upgrade `mait-code` (`mait-code update`)."
        )

    if schema_version < 2:
        # v1 stored a single ``installed_at`` (really "last touched").
        # The true first-install date is unrecoverable, so seed both
        # timestamps from it; the next ``update`` writes a proper v2
        # record. Upgraded in-memory only — reads stay side-effect free.
        _require(raw, {"source_dir", "installed_at"}, target)
        return InstallRecord(
            source_dir=raw["source_dir"],
            first_installed_at=raw["installed_at"],
            updated_at=raw["installed_at"],
            schema_version=SCHEMA_VERSION,
        )

    _require(raw, {"source_dir", "first_installed_at", "updated_at"}, target)
    return InstallRecord(
        source_dir=raw["source_dir"],
        first_installed_at=raw["first_installed_at"],
        updated_at=raw["updated_at"],
        schema_version=schema_version,
    )


def _require(raw: dict[str, Any], fields: set[str], target: Path) -> None:
    """Raise :class:`RecordError` if any of ``fields`` is absent from ``raw``."""
    missing = fields - set(raw)
    if missing:
        raise RecordError(
            f"Install record at {target} is missing required fields: {sorted(missing)}"
        )
