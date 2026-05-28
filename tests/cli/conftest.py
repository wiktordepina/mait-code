"""Shared fixtures for CLI tests.

The `fake_home` fixture redirects `$HOME`, `$XDG_DATA_HOME`, and
`$MAIT_CODE_DATA_DIR` into a per-test temporary directory so we can
exercise real filesystem effects (symlinks, JSON files, directory
creation) without polluting the developer's actual home.

The `fake_source` fixture materialises a minimal mait-code-shaped
source tree at a tmp path — enough for `install` to validate against
without copying the full repo.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME / XDG dirs / MAIT_CODE env vars into ``tmp_path``."""
    import mait_code.config as _config

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.delenv("MAIT_CODE_DATA_DIR", raising=False)
    monkeypatch.delenv("MAIT_CODE_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("MAIT_CODE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("MAIT_CODE_LOG_FILE", raising=False)
    monkeypatch.setattr(_config, "_settings_cache", None)
    return home


@pytest.fixture
def fake_source(tmp_path: Path) -> Path:
    """Construct a minimal source tree that ``install`` will accept.

    Includes ``pyproject.toml`` with the right project name, an
    ``src/mait_code/`` directory, ``config/CLAUDE.md`` + ``settings.json``,
    a ``templates/`` dir with the two identity stubs, and empty
    ``skills/`` + ``agents/`` directories.
    """
    src = tmp_path / "mait-code-src"
    src.mkdir()

    (src / "pyproject.toml").write_text(
        '[project]\nname = "mait-code"\nversion = "0.0.0"\n'
    )

    pkg = src / "src" / "mait_code"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "0.0.0"\n')

    config = src / "config"
    config.mkdir()
    (config / "CLAUDE.md").write_text("# fake CLAUDE.md\n")
    (config / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {"type": "command", "command": "mc-hook-session-start"}
                            ]
                        }
                    ]
                },
                "mcpServers": {},
                "env": {},
            },
            indent=2,
        )
    )

    templates = src / "templates"
    templates.mkdir()
    (templates / "soul_document.md").write_text("# soul template\n")
    (templates / "user_context.md").write_text("# user context template\n")

    (src / "skills").mkdir()
    (src / "agents").mkdir()

    return src


@pytest.fixture
def cleanup_state_dir(fake_home: Path):  # noqa: ARG001 — fixture chaining
    """Ensure the state dir is fresh for each test by removing it afterwards."""
    yield
    state = fake_home / ".local" / "share" / "mait-code"
    if state.exists():
        shutil.rmtree(state)
