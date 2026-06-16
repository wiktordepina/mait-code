"""``mait-code update`` &mdash; fetch the latest source and reinstall.

Reads the install record to find the source tree, advances it to the
right ref, and &mdash; **only if the source actually moved** &mdash; runs
``uv tool install`` against the source dir with the configured embedding
extra. It then re-runs the symlink and settings-merge steps in case the
new source ships changes (new skills, updated settings.json) and bumps
the install record's ``installed_at``.

How the source is advanced depends on its current state, because a
bootstrap install pins to a release **tag** (detached HEAD) while a
local-clone dev install sits on a **branch**:

* ``--ref <X>`` given &rarr; checkout ``X`` (after a fetch).
* On a branch &rarr; fast-forward it (``git merge --ff-only``).
* Detached HEAD (typical post-bootstrap) &rarr; **force**-checkout the
  latest ``v*`` tag.

The detached-HEAD checkout is forced (``git checkout --force``) because
the bootstrap clone is tool-managed and its skills are symlinked into
``~/.claude`` &mdash; editing a skill in place writes *through* the
symlink into this working tree, leaving tracked files modified. A plain
checkout would then abort with "local changes would be overwritten",
wedging every subsequent update. Those write-through edits are not user
work (the committed release is authoritative), so they are discarded. The
branch (dev) path is *not* forced: local edits there are intentional.

This is the fix for the bug where ``git pull`` was run unconditionally
and failed on a tag-pinned (detached HEAD) install with "You are not
currently on a branch".

Idempotency: the reinstall is the expensive part, so it is skipped when
the advance step left ``HEAD`` on the same commit it started on. A
repeated ``mait-code update`` with nothing new upstream is therefore a
cheap no-op rather than a full rebuild of every package. ``--force``
reinstalls regardless (e.g. to pick up uncommitted working-tree edits on
a dev checkout). When a reinstall *does* run, it uses
``--reinstall-package mait-code`` so only the local source package is
rebuilt; unchanged third-party dependencies are left in place.

The subprocess calls are kept narrow and explicit so tests can replace
them with stubs without having to patch the heavier orchestrator.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from mait_code.cli._install import EMBEDDING_PROVIDERS, verify_source
from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.console import console
from mait_code.cli._record import InstallRecord, read_record, write_record
from mait_code.cli._settings import (
    merge_settings,
    read_settings_file as read_claude_settings,
    write_settings_file as write_claude_settings,
)
from mait_code.config import read_settings_file as read_mait_settings
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


def _head(capture: Capture, source_dir: Path) -> str:
    """Return the current ``HEAD`` commit sha, used to detect whether an
    advance actually moved the source tree."""
    return capture(["git", "rev-parse", "HEAD"], cwd=source_dir).strip()


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
        reinstalled: bool,
        claude_md: SymlinkResult,
        skills: SymlinkResult,
        agents: SymlinkResult,
        settings_path: Path,
    ) -> None:
        self.record = record
        self.fetched = fetched
        self.landed_on = landed_on
        self.reinstalled = reinstalled
        self.claude_md = claude_md
        self.skills = skills
        self.agents = agents
        self.settings_path = settings_path


def update(
    *,
    no_pull: bool = False,
    ref: str | None = None,
    force: bool = False,
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
        force: Reinstall even when the source ``HEAD`` did not move.
            Useful to rebuild from uncommitted working-tree edits on a
            dev checkout, where the commit is unchanged but files differ.
        claude_dir: Override the Claude Code config dir (defaults to
            :func:`~mait_code.cli._paths.claude_dir`).
        runner: Mutating subprocess runner for tests to stub out.
        capture: Read-only command runner for tests to stub out.

    Returns:
        An :class:`UpdateSummary`.

    Raises:
        ValueError: If the install record's source directory no longer
            exists, doesn't look like a mait-code clone, is in detached
            HEAD with no ``v*`` tag to advance to, or the settings file
            has no ``embedding-provider`` (run ``mait-code install``).
    """
    # Lazy resolution so tests can monkeypatch the module attributes.
    if runner is None:
        runner = default_runner
    if capture is None:
        capture = default_capture

    record = read_record()
    source_dir = Path(record.source_dir)
    verify_source(source_dir)

    # The embedding provider is read from the centralised settings file,
    # which `mait-code install` writes on every install (0.19.0+). A missing
    # provider means the install predates centralised settings — fail with a
    # pointer to `install` rather than silently defaulting, which would drop
    # the bedrock extra from the reinstall below.
    user_settings = read_mait_settings()
    embedding_provider = user_settings.get("embedding-provider")
    if embedding_provider is None:
        raise ValueError(
            "no embedding-provider in the mait-code settings file; "
            "run `mait-code install` to create it."
        )
    if embedding_provider not in EMBEDDING_PROVIDERS:
        raise ValueError(
            f"embedding-provider is {embedding_provider!r}; "
            f"expected one of {EMBEDDING_PROVIDERS}"
        )

    # 1. Advance the source tree to the right ref, tracking whether HEAD
    #    actually moved so we can skip a needless reinstall below.
    #
    #    Every git invocation is `--quiet`: the fetch progress, the
    #    "Previous HEAD position was…/HEAD is now at…" checkout chatter and
    #    the fast-forward summary are all noise the user can't act on, and
    #    the `UpdateSummary` reports the meaningful outcome afterwards. A
    #    `console.status` spinner covers the network round-trip so the now-
    #    silent stretch doesn't read as a hang. Errors still reach stderr —
    #    `--quiet` suppresses progress, not failures.
    head_before = _head(capture, source_dir)
    fetched = False
    with console.status("Fetching latest source…"):
        if not no_pull:
            runner(
                ["git", "fetch", "origin", "--tags", "--prune", "--quiet"],
                cwd=source_dir,
            )
            fetched = True

        if ref is not None:
            runner(["git", "checkout", "--quiet", ref], cwd=source_dir)
            landed_on = ref
        else:
            branch = _current_branch(capture, source_dir)
            if branch:
                if not no_pull:
                    runner(["git", "merge", "--ff-only", "--quiet"], cwd=source_dir)
                landed_on = f"branch {branch}"
            else:
                latest = _latest_tag(capture, source_dir)
                if latest is None:
                    raise ValueError(
                        f"{source_dir} is in detached HEAD and has no v* tags to "
                        f"update to. Check out a branch, or pass --ref."
                    )
                # `--force` so the checkout succeeds even when the working tree
                # has locally-modified tracked files. This is the tool-managed
                # bootstrap clone, and its skills are symlinked into ~/.claude
                # (e.g. ~/.claude/skills/board -> source/skills/board), so editing
                # a skill in place writes *through* the symlink into this working
                # tree. Those write-through edits are not user work — the committed
                # release is authoritative — so discard them rather than letting
                # git abort with "local changes would be overwritten by checkout".
                runner(
                    ["git", "checkout", "--force", "--quiet", latest],
                    cwd=source_dir,
                )
                landed_on = latest

    head_after = _head(capture, source_dir)

    # 2. uv tool install &mdash; only when the source actually changed (or
    #    --force). uv keys its build cache on the package version, which does
    #    not bump between commits, so `--reinstall-package mait-code` forces a
    #    rebuild of just the local source; unchanged deps stay put. Skipping
    #    this entirely on a no-op is what makes a repeated update cheap.
    reinstalled = force or head_after != head_before
    if reinstalled:
        extra = "[bedrock]" if embedding_provider == "bedrock" else ""
        # `--quiet` drops uv's "Resolved N packages" line and the full
        # `+ package==version` install listing — dozens of lines the user
        # didn't ask for. The spinner stands in for the (often multi-second)
        # rebuild so the wait is legible.
        with console.status("Reinstalling mait-code…"):
            runner(
                [
                    "uv",
                    "tool",
                    "install",
                    f"{source_dir}{extra}",
                    "--force",
                    "--reinstall-package",
                    "mait-code",
                    "--python",
                    "3.13",
                    "--quiet",
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
        reinstalled=reinstalled,
        claude_md=claude_md_result,
        skills=skills_result,
        agents=agents_result,
        settings_path=settings_path,
    )
