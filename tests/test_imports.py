"""Smoke test: every reference-surface module imports cleanly and declares ``__all__``.

This is the only test file in the repo right now. Its job is to give CI's
``pytest`` job something to run (so the suite has a passing baseline) and to
catch the obvious failure modes — a surface module that no longer imports, or
one that has been refactored such that ``__all__`` was lost.

Future bricks can grow real test coverage on top of this; for now, the
contract is narrow and explicit.
"""

from __future__ import annotations

import importlib

import pytest

REFERENCE_MODULES = [
    # Core
    "mait_code.context",
    "mait_code.llm",
    "mait_code.logging",
    "mait_code.ssl",
    # Tools
    "mait_code.tools.memory",
    "mait_code.tools.reminders",
    "mait_code.tools.tasks",
    "mait_code.tools.board",
    "mait_code.tools.decisions",
    "mait_code.tools.web_fetch",
    # TUI
    "mait_code.tui",
    # Hooks
    "mait_code.hooks.observe",
    "mait_code.hooks.session_start",
    "mait_code.hooks.auto_format",
]


@pytest.mark.parametrize("module_name", REFERENCE_MODULES)
def test_module_imports_and_has_all(module_name: str) -> None:
    """Import the module and assert ``__all__`` is declared and non-empty."""
    module = importlib.import_module(module_name)
    assert hasattr(module, "__all__"), f"{module_name} missing __all__"
    assert isinstance(module.__all__, list), f"{module_name}.__all__ is not a list"
    assert len(module.__all__) > 0, f"{module_name} has empty __all__"
