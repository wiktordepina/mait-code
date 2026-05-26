"""``mait-code update`` &mdash; pull the latest source and reinstall.

Reads the install record to find the source tree, optionally runs
``git pull`` (and optionally checks out a specific ref), runs
``uv tool install --force --reinstall`` against the source dir with the
recorded embedding extra, then re-runs the symlink and settings-merge
steps in case the new source ships changes (new skills, updated
settings.json). Bumps the install record's ``version`` and
``installed_at``.

The subprocess calls are kept narrow and explicit so tests can replace
them with stubs without having to patch the heavier orchestrator.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

import mait_code
from mait_code.cli._install import EMBEDDING_PROVIDERS, verify_source
from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._record import InstallRecord, read_record, write_record
from mait_code.cli._settings import (
    merge_settings,
    read_settings_file,
    write_settings_file,
)
from mait_code.cli._symlinks import (
    SymlinkResult,
    symlink_agents,
    symlink_claude_md,
    symlink_skills,
)

__all__ = [
    "Runner",
    "UpdateSummary",
    "default_runner",
    "update",
]


class Runner(Protocol):
    """Protocol for a function that runs a subprocess and raises on failure.

    The default implementation calls ``subprocess.run(..., check=True)``;
    tests replace this with a recording stub so they can exercise
    :func:`update` without invoking actual ``git`` or ``uv``.
    """

    def __call__(self, cmd: list[str], *, cwd: Path | None = None) -> None: ...


def default_runner(cmd: list[str], *, cwd: Path | None = None) -> None:
    """Default :class:`Runner` &mdash; ``subprocess.run`` with ``check=True``."""
    subprocess.run(cmd, cwd=cwd, check=True)


class UpdateSummary:
    """What :func:`update` produces &mdash; used by the CLI for output."""

    def __init__(
        self,
        *,
        record: InstallRecord,
        pulled: bool,
        ref: str | None,
        claude_md: SymlinkResult,
        skills: SymlinkResult,
        agents: SymlinkResult,
        settings_path: Path,
    ) -> None:
        self.record = record
        self.pulled = pulled
        self.ref = ref
        self.claude_md = claude_md
        self.skills = skills
        self.agents = agents
        self.settings_path = settings_path


def update(
    *,
    no_pull: bool = False,
    ref: str | None = None,
    claude_dir: Path | None = None,
    runner: Runner | None = None,
) -> UpdateSummary:
    """Run the update flow.

    Args:
        no_pull: Skip ``git pull`` (useful if the user pulls manually).
        ref: If set, ``git checkout <ref>`` before reinstall.
        claude_dir: Override the Claude Code config dir (defaults to
            :func:`~mait_code.cli._paths.claude_dir`).
        runner: Subprocess runner for tests to stub out.

    Returns:
        An :class:`UpdateSummary`.

    Raises:
        ValueError: If the install record's source directory no longer
            exists or doesn't look like a mait-code clone.
    """
    # Lazy resolution so tests can monkeypatch `default_runner` on the
    # module after import.
    if runner is None:
        runner = default_runner

    record = read_record()
    source_dir = Path(record.source_dir)
    verify_source(source_dir)

    if record.embedding_provider not in EMBEDDING_PROVIDERS:
        raise ValueError(
            f"Install record's embedding_provider is {record.embedding_provider!r}; "
            f"expected one of {EMBEDDING_PROVIDERS}"
        )

    # 1. git pull (and optional checkout).
    pulled = False
    if ref is not None:
        runner(["git", "checkout", ref], cwd=source_dir)
    if not no_pull:
        runner(["git", "pull"], cwd=source_dir)
        pulled = True

    # 2. uv tool install --force --reinstall.
    extra = "[bedrock]" if record.embedding_provider == "bedrock" else ""
    runner(
        [
            "uv",
            "tool",
            "install",
            f"{source_dir}{extra}",
            "--force",
            "--reinstall",
            "--python",
            "3.13",
        ],
    )

    # 3. Refresh symlinks + settings.
    cdir = (claude_dir if claude_dir is not None else default_claude_dir()).resolve()
    claude_md_result = symlink_claude_md(source_dir, cdir)
    skills_result = symlink_skills(source_dir, cdir)
    agents_result = symlink_agents(source_dir, cdir)

    settings_path = cdir / "settings.json"
    src_settings = read_settings_file(source_dir / "config" / "settings.json")
    dst_settings = read_settings_file(settings_path)
    merged = merge_settings(
        src_settings,
        dst_settings,
        embedding_provider=record.embedding_provider,
    )
    write_settings_file(settings_path, merged)

    # 4. Bump the install record.
    refreshed = InstallRecord.new(
        source_dir=source_dir,
        version=mait_code.__version__,
        embedding_provider=record.embedding_provider,
    )
    write_record(refreshed)

    return UpdateSummary(
        record=refreshed,
        pulled=pulled,
        ref=ref,
        claude_md=claude_md_result,
        skills=skills_result,
        agents=agents_result,
        settings_path=settings_path,
    )
