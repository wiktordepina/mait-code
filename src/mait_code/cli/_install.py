"""``mait-code install`` &mdash; the first-time-install orchestrator.

The Typer command wrapper in :mod:`mait_code.cli` parses the flags and
calls into :func:`install`, which does all the real work. Keeping the
business logic separate makes it directly testable without
``CliRunner``.

The flow mirrors the legacy ``scripts/install.sh`` but is non-interactive:
every choice the bash script prompted for is a flag with a sensible
default. By the time this command runs, the ``mait-code`` binary is
already installed via ``uv tool install`` &mdash; that's the bash shim's
(or Brick E one-liner's) responsibility.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._record import InstallRecord, write_record
from mait_code.cli._settings import (
    merge_settings,
    read_settings_file as read_claude_settings,
    write_settings_file as write_claude_settings,
)
from mait_code.config import write_settings_file as write_mait_settings
from mait_code.cli._symlinks import (
    SymlinkResult,
    symlink_agents,
    symlink_claude_md,
    symlink_skills,
)

__all__ = [
    "EMBEDDING_PROVIDERS",
    "InstallSummary",
    "install",
    "verify_source",
]

EMBEDDING_PROVIDERS = ("local", "bedrock")
"""The valid values for ``--embedding-provider``."""


class InstallSummary:
    """What :func:`install` produces &mdash; used by the CLI to render output."""

    def __init__(
        self,
        *,
        record: InstallRecord,
        claude_md: SymlinkResult,
        skills: SymlinkResult,
        agents: SymlinkResult,
        templates_copied: list[str],
        memory_md_created: bool,
        settings_path: Path,
    ) -> None:
        self.record = record
        self.claude_md = claude_md
        self.skills = skills
        self.agents = agents
        self.templates_copied = templates_copied
        self.memory_md_created = memory_md_created
        self.settings_path = settings_path


MEMORY_MD_STUB = """# Memory

<!-- Curated facts about the user, their projects, and preferences. -->
<!-- Updated by the reflection system and manual editing. -->
<!-- Keep under ~150 lines for context budget. -->
"""


def verify_source(source_dir: Path) -> None:
    """Validate that ``source_dir`` looks like a mait-code clone.

    Checks for ``pyproject.toml`` declaring ``name = "mait-code"`` and a
    ``src/mait_code/`` directory. Raises :class:`ValueError` with an
    actionable message if either check fails.
    """
    if not source_dir.is_dir():
        raise ValueError(f"--from {source_dir} is not a directory")
    pyproject = source_dir / "pyproject.toml"
    if not pyproject.is_file():
        raise ValueError(
            f"--from {source_dir} has no pyproject.toml; not a mait-code clone"
        )
    text = pyproject.read_text(encoding="utf-8")
    if 'name = "mait-code"' not in text:
        raise ValueError(
            f"--from {source_dir}/pyproject.toml is not the mait-code project"
        )
    if not (source_dir / "src" / "mait_code").is_dir():
        raise ValueError(
            f"--from {source_dir}/src/mait_code is missing; not a mait-code clone"
        )


def install(
    *,
    source_dir: Path,
    embedding_provider: str = "local",
    data_dir: Path | None = None,
    claude_dir: Path | None = None,
) -> InstallSummary:
    """Run the install flow.

    Args:
        source_dir: Absolute path to the cloned mait-code source.
        embedding_provider: ``"local"`` or ``"bedrock"``.
        data_dir: Override the mait-code data directory (defaults to
            :func:`~mait_code.cli._paths.data_dir`).
        claude_dir: Override the Claude Code config directory (defaults
            to :func:`~mait_code.cli._paths.claude_dir`).

    Returns:
        An :class:`InstallSummary` describing what was created.

    Raises:
        ValueError: If ``source_dir`` doesn't look like a mait-code clone,
            or if ``embedding_provider`` isn't a known value.
    """
    if embedding_provider not in EMBEDDING_PROVIDERS:
        raise ValueError(
            f"--embedding-provider must be one of {EMBEDDING_PROVIDERS}, "
            f"got {embedding_provider!r}"
        )

    source_dir = source_dir.resolve()
    verify_source(source_dir)

    cdir = (claude_dir if claude_dir is not None else default_claude_dir()).resolve()
    ddir = (data_dir if data_dir is not None else default_data_dir()).resolve()

    # 1. Data directory layout (memory/graph is deliberately not created —
    # it's dead code per the docs audit).
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "memory" / "observations").mkdir(parents=True, exist_ok=True)
    (ddir / "memory" / "reflections").mkdir(parents=True, exist_ok=True)

    # 2. Copy templates — never overwrite.
    templates_copied: list[str] = []
    for name in ("soul_document.md", "user_context.md"):
        src = source_dir / "templates" / name
        dst = ddir / name
        if src.is_file() and not dst.exists():
            shutil.copy(src, dst)
            templates_copied.append(name)

    # 3. MEMORY.md stub if missing.
    memory_md = ddir / "memory" / "MEMORY.md"
    memory_md_created = False
    if not memory_md.exists():
        memory_md.write_text(MEMORY_MD_STUB, encoding="utf-8")
        memory_md_created = True

    # 4-6. Symlinks.
    claude_md_result = symlink_claude_md(source_dir, cdir)
    skills_result = symlink_skills(source_dir, cdir)
    agents_result = symlink_agents(source_dir, cdir)

    # 7. Write centralised settings file.
    user_settings = {"embedding-provider": embedding_provider}
    write_mait_settings(user_settings)

    # 8. Propagate settings into ~/.claude/settings.json for Claude Code.
    settings_path = cdir / "settings.json"
    src_settings = read_claude_settings(source_dir / "config" / "settings.json")
    dst_settings = read_claude_settings(settings_path)
    merged = merge_settings(
        src_settings,
        dst_settings,
        user_settings=user_settings,
    )
    write_claude_settings(settings_path, merged)

    # 9. Install record.
    record = InstallRecord.new(source_dir=source_dir)
    write_record(record)

    return InstallSummary(
        record=record,
        claude_md=claude_md_result,
        skills=skills_result,
        agents=agents_result,
        templates_copied=templates_copied,
        memory_md_created=memory_md_created,
        settings_path=settings_path,
    )
