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

import hashlib
import shutil
from pathlib import Path

from mait_code.cli._paths import claude_dir as default_claude_dir
from mait_code.cli._paths import data_dir as default_data_dir
from mait_code.cli._record import InstallRecord, write_record
from mait_code.cli._settings import (
    merge_settings,
    mod_dir,
    mods_enabled,
    sync_mod_dir,
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
    "sync_identity_templates",
    "verify_source",
]

EMBEDDING_PROVIDERS = ("local", "bedrock")
"""The valid values for ``--embedding-provider``."""

_IDENTITY_TEMPLATES = (
    ("soul_document.md", "soul_document.md"),
    ("user_context.md", "user_context.md"),
    ("communication_styles/default.md", "communication_style.md"),
)
"""Identity templates as ``(path under templates/, name in the data dir)``."""

_SUPERSEDED_TEMPLATES: dict[str, frozenset[str]] = {
    "communication_style.md": frozenset(
        {
            # 0.77.0 — attention markers only, no side-effect markers.
            "661b40da6b7d3977a1650e635043d909060a937d213f442062fb6a5c0aa38d50",
            # Side-effect markers with the earlier state-change glyphs.
            "e79ed2302a987317de0b9c98e4b2efe09452169935b5c5967d374049f3892885",
            "654e3f1e478d3194a341f0aeff3c32dcd526bc0f287932885541538b0413f566",
        }
    ),
}
"""SHA-256 digests of earlier shipped versions of each identity template.

A data-dir file whose bytes match one of these is an untouched copy of an
old template, so it is safe to replace with the current one. When a
template changes, add the digest of the version being replaced here.
"""


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
        templates_upgraded: list[str],
        memory_md_created: bool,
        settings_path: Path,
    ) -> None:
        self.record = record
        self.claude_md = claude_md
        self.skills = skills
        self.agents = agents
        self.templates_copied = templates_copied
        self.templates_upgraded = templates_upgraded
        self.memory_md_created = memory_md_created
        self.settings_path = settings_path


MEMORY_MD_STUB = """# Memory

<!-- Curated facts about the user, their projects, and preferences. -->
<!-- Updated by the reflection system and manual editing. -->
<!-- Keep under ~150 lines for context budget. -->
"""


def sync_identity_templates(
    source_dir: Path, ddir: Path
) -> tuple[list[str], list[str]]:
    """Bring the identity files in the data dir up to the shipped templates.

    A missing file is copied from its template. An existing file is
    replaced only when it is byte-identical to an earlier shipped version
    (see ``_SUPERSEDED_TEMPLATES``); anything the user has edited is left
    alone.

    Args:
        source_dir: The mait-code source tree holding ``templates/``.
        ddir: The mait-code data directory.

    Returns:
        ``(copied, upgraded)`` &mdash; the data-dir names of files created
        and of untouched old copies replaced with the current template.
    """
    copied: list[str] = []
    upgraded: list[str] = []
    for template, name in _IDENTITY_TEMPLATES:
        src = source_dir / "templates" / template
        dst = ddir / name
        if not src.is_file():
            continue
        if not dst.exists():
            shutil.copy(src, dst)
            copied.append(name)
            continue
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        if digest in _SUPERSEDED_TEMPLATES.get(name, frozenset()):
            shutil.copy(src, dst)
            upgraded.append(name)
    return copied, upgraded


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

    # 2. Copy templates — never overwrite an edited one.
    templates_copied, templates_upgraded = sync_identity_templates(source_dir, ddir)

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
    merged = sync_mod_dir(merged, mod_dir(source_dir) if mods_enabled() else None)
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
        templates_upgraded=templates_upgraded,
        memory_md_created=memory_md_created,
        settings_path=settings_path,
    )
