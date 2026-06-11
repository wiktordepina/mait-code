"""Root test configuration. Fixtures live in tool-specific conftest files."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_mait_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Isolate every test from the developer's real mait-code config, data, and logs.

    First, **every** inherited ``MAIT_CODE_*`` env var is cleared. ``config.resolve``
    checks env before settings file before default, so any knob a developer exports
    in their shell (``MAIT_CODE_THEME``, ``MAIT_CODE_EMBEDDING_PROVIDER``,
    ``MAIT_CODE_LOG_LEVEL``, …) would otherwise bleed straight into the suite —
    a local "red" that's actually green on a clean CI runner. Clearing them up front
    pins every setting to its default regardless of the dev's shell. Tests that need
    a specific value set it via their own ``monkeypatch``, which runs after this
    autouse setup, so clear-all-first is safe.

    Three things are then pointed at throwaway dirs under ``tmp_path``:

    * ``XDG_CONFIG_HOME`` — ``config.resolve`` / ``collect_settings`` read
      ``$XDG_CONFIG_HOME/mait-code/settings.toml`` (cached at module level).
      Without isolation a real settings file on the dev's machine bleeds in, so
      "unset → default" assertions flip to ``source == "settings"``.
    * ``XDG_STATE_HOME`` — where logs land. ``@log_invocation`` calls
      ``setup_logging()``, which adds a ``TimedRotatingFileHandler`` to the
      global ``mait_code`` logger. Without isolation every test that drives a
      decorated ``main()`` writes into the dev's real ``mait-code.log`` (with
      pytest's argv logged as the "command"). ``_setup_done`` is reset and the
      handlers swapped so logging re-initialises against the temp dir per test
      and never leaks a handler pointing at the real log.
    * ``MAIT_CODE_DATA_DIR`` — the data dir (DBs, model cache). Belt-and-braces
      so a test that reaches ``get_data_dir()`` without a tool fixture can't
      touch the real stores. The dev's own ``MAIT_CODE_DATA_DIR`` is otherwise
      inherited by the pytest process.

    Tests that need a real settings file or a specific data dir override these
    afterwards (their ``monkeypatch`` calls run after this autouse setup).
    """
    import mait_code.config as _config
    import mait_code.logging as _logging

    for key in list(os.environ):
        if key.startswith("MAIT_CODE_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(_config, "_settings_cache", None)
    monkeypatch.setattr(_config, "_injected_env", set())

    logger = logging.getLogger("mait_code")
    saved_handlers = logger.handlers[:]
    logger.handlers = []
    _logging._setup_done = False
    yield
    for handler in logger.handlers[:]:
        handler.close()
    logger.handlers = saved_handlers
    _logging._setup_done = False
