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

SCHEMA_VERSION = 1


class RecordError(Exception):
    """Raised when the install record is missing, malformed, or from a
    schema version this binary doesn't understand."""


@dataclass
class InstallRecord:
    """Persisted state about a mait-code install.

    Attributes:
        source_dir: Absolute path to the cloned source tree.
        version: The ``mait-code`` package version recorded at install time.
        embedding_provider: ``"local"`` or ``"bedrock"``.
        installed_at: ISO 8601 UTC timestamp of the most recent
            install / update.
        schema_version: Format version of this record. See
            :data:`SCHEMA_VERSION`.
    """

    source_dir: str
    version: str
    embedding_provider: str
    installed_at: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        source_dir: Path | str,
        version: str,
        embedding_provider: str,
    ) -> InstallRecord:
        """Construct a fresh record stamped with the current UTC time."""
        return cls(
            source_dir=str(Path(source_dir).resolve()),
            version=version,
            embedding_provider=embedding_provider,
            installed_at=datetime.now(UTC).isoformat(timespec="seconds"),
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

    required = {"source_dir", "version", "embedding_provider", "installed_at"}
    missing = required - set(raw)
    if missing:
        raise RecordError(
            f"Install record at {target} is missing required fields: {sorted(missing)}"
        )

    return InstallRecord(
        source_dir=raw["source_dir"],
        version=raw["version"],
        embedding_provider=raw["embedding_provider"],
        installed_at=raw["installed_at"],
        schema_version=schema_version,
    )
