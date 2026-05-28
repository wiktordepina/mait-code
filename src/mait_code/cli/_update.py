"""``mait-code update`` &mdash; fetch the latest source and reinstall.

Reads the install record to find the source tree, advances it to the
right ref, runs ``uv tool install --force --reinstall`` against the
source dir with the recorded embedding extra, then re-runs the symlink
and settings-merge steps in case the new source ships changes (new
skills, updated settings.json). Bumps the install record's ``version``
and ``installed_at``.

How the source is advanced depends on its current state, because a
bootstrap install pins to a release **tag** (detached HEAD) while a
local-clone dev install sits on a **branch**:

* ``--ref <X>`` given &rarr; checkout ``X`` (after a fetch).
* On a branch &rarr; fast-forward it (``git merge --ff-only``).
* Detached HEAD (typical post-bootstrap) &rarr; checkout the latest
  ``v*`` tag.

This is the fix for the bug where ``git pull`` was run unconditionally
and failed on a tag-pinned (detached HEAD) install with "You are not
currently on a branch".

The subprocess calls are kept narrow and explicit so tests can replace
them with stubs without having to patch the heavier orchestrator.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from mait_code.cli._install import EMBEDDING_PROVIDERS, verify_source
from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import install_record_path
from mait_code.cli._record import InstallRecord, read_record, write_record
from mait_code.cli._settings import (
    merge_settings,
    read_settings_file as read_claude_settings,
    write_settings_file as write_claude_settings,
)
from mait_code.config import (
    read_settings_file as read_mait_settings,
    write_settings_file as write_mait_settings,
)
from mait_code.cli._symlinks import (
    SymlinkResult,
    symlink_agents,
    symlink_claude_md,
    symlink_skills,
)

__all__ = [
    "Capture",
    "Runner",
    "UpdateSummary",
    "default_capture",
    "default_runner",
    "update",
]


class Runner(Protocol):
    """Protocol for a function that runs a mutating subprocess and raises on failure.

    The default implementation calls ``subprocess.run(..., check=True)``;
    tests replace this with a recording stub so they can exercise
    :func:`update` without invoking actual ``git`` or ``uv``.
    """

    def __call__(self, cmd: list[str], *, cwd: Path | None = None) -> None: ...


class Capture(Protocol):
    """Protocol for a function that runs a read-only command and returns stdout.

    Used for the git queries (current branch, latest tag) that
    :func:`update` needs to decide how to advance the source tree.
    Tests replace this with a stub returning canned output.
    """

    def __call__(self, cmd: list[str], *, cwd: Path | None = None) -> str: ...


def default_runner(cmd: list[str], *, cwd: Path | None = None) -> None:
    """Default :class:`Runner` &mdash; ``subprocess.run`` with ``check=True``."""
    subprocess.run(cmd, cwd=cwd, check=True)


def default_capture(cmd: list[str], *, cwd: Path | None = None) -> str:
    """Default :class:`Capture` &mdash; return stripped stdout, raise on failure."""
    result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _current_branch(capture: Capture, source_dir: Path) -> str:
    """Return the current branch name, or ``""`` if in detached HEAD.

    ``git branch --show-current`` prints the branch name on a normal
    checkout and an empty string (exit 0) when HEAD is detached, so it
    doubles as a detached-HEAD probe.
    """
    return capture(["git", "branch", "--show-current"], cwd=source_dir).strip()


def _latest_tag(capture: Capture, source_dir: Path) -> str | None:
    """Return the highest ``v*`` tag by version sort, or ``None`` if none exist."""
    out = capture(
        ["git", "tag", "--list", "--sort=-v:refname", "v*"],
        cwd=source_dir,
    )
    tags = [line.strip() for line in out.splitlines() if line.strip()]
    return tags[0] if tags else None


class UpdateSummary:
    """What :func:`update` produces &mdash; used by the CLI for output."""

    def __init__(
        self,
        *,
        record: InstallRecord,
        fetched: bool,
        landed_on: str,
        claude_md: SymlinkResult,
        skills: SymlinkResult,
        agents: SymlinkResult,
        settings_path: Path,
    ) -> None:
        self.record = record
        self.fetched = fetched
        self.landed_on = landed_on
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
    capture: Capture | None = None,
) -> UpdateSummary:
    """Run the update flow.

    Args:
        no_pull: Skip the network fetch and any branch fast-forward;
            reinstall from whatever is currently checked out. ``--ref``
            still checks out (a local) ref.
        ref: If set, ``git checkout <ref>`` (after a fetch unless
            ``no_pull``). Pins to a tag/branch/sha.
        claude_dir: Override the Claude Code config dir (defaults to
            :func:`~mait_code.cli._paths.claude_dir`).
        runner: Mutating subprocess runner for tests to stub out.
        capture: Read-only command runner for tests to stub out.

    Returns:
        An :class:`UpdateSummary`.

    Raises:
        ValueError: If the install record's source directory no longer
            exists, doesn't look like a mait-code clone, or is in
            detached HEAD with no ``v*`` tag to advance to.
    """
    # Lazy resolution so tests can monkeypatch the module attributes.
    if runner is None:
        runner = default_runner
    if capture is None:
        capture = default_capture

    record = read_record()
    source_dir = Path(record.source_dir)
    verify_source(source_dir)

    # Read the centralised settings file; migrate from install record
    # if no settings file exists yet (pre-0.19.0 install).
    user_settings = read_mait_settings()
    if not user_settings:
        import json

        raw = json.loads(install_record_path().read_text(encoding="utf-8"))
        provider = raw.get("embedding_provider")
        if provider and provider in EMBEDDING_PROVIDERS:
            user_settings = {"embedding-provider": provider}
            write_mait_settings(user_settings)

    embedding_provider = user_settings.get("embedding-provider", "local")
    if embedding_provider not in EMBEDDING_PROVIDERS:
        raise ValueError(
            f"embedding-provider is {embedding_provider!r}; "
            f"expected one of {EMBEDDING_PROVIDERS}"
        )

    # 1. Advance the source tree to the right ref.
    fetched = False
    if not no_pull:
        runner(["git", "fetch", "origin", "--tags", "--prune"], cwd=source_dir)
        fetched = True

    if ref is not None:
        runner(["git", "checkout", ref], cwd=source_dir)
        landed_on = ref
    else:
        branch = _current_branch(capture, source_dir)
        if branch:
            if not no_pull:
                runner(["git", "merge", "--ff-only"], cwd=source_dir)
            landed_on = f"branch {branch}"
        else:
            latest = _latest_tag(capture, source_dir)
            if latest is None:
                raise ValueError(
                    f"{source_dir} is in detached HEAD and has no v* tags to "
                    f"update to. Check out a branch, or pass --ref."
                )
            runner(["git", "checkout", latest], cwd=source_dir)
            landed_on = latest

    # 2. uv tool install --force --reinstall.
    extra = "[bedrock]" if embedding_provider == "bedrock" else ""
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
    src_settings = read_claude_settings(source_dir / "config" / "settings.json")
    dst_settings = read_claude_settings(settings_path)
    merged = merge_settings(
        src_settings,
        dst_settings,
        user_settings=user_settings,
    )
    write_claude_settings(settings_path, merged)

    # 4. Bump the install record.
    refreshed = InstallRecord.new(source_dir=source_dir)
    write_record(refreshed)

    return UpdateSummary(
        record=refreshed,
        fetched=fetched,
        landed_on=landed_on,
        claude_md=claude_md_result,
        skills=skills_result,
        agents=agents_result,
        settings_path=settings_path,
    )
