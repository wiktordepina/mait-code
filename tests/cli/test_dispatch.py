"""Tests for the top-level ``mait-code`` dispatcher's routing branches.

The subcommand *implementations* (install/update/uninstall/status/doctor/
settings) are exercised by their own focused test modules. This module fills
the gaps in :mod:`mait_code.cli` itself — the thin dispatch layer that decides,
per command, whether to launch a Textual TUI (on a TTY) or fall back to text.

Every TUI launcher is patched so nothing interactive ever runs: the tests
assert the *routing* (which launcher was invoked, with what), keeping the suite
fast and hermetic. TTY detection is forced with ``monkeypatch`` on
``sys.stdin``/``sys.stdout``'s ``isatty`` rather than a real terminal.
"""

from __future__ import annotations

import importlib.metadata

import pytest
import typer
from typer.testing import CliRunner

import mait_code.cli as cli
from mait_code.cli import app
from mait_code.cli._home_tui import HomeTarget

runner = CliRunner()


class _FakeTTY:
    """A stand-in stream whose ``isatty()`` reports a terminal."""

    def isatty(self) -> bool:
        return True


class _BareCtx:
    """A minimal Typer context for the bare-invocation path (no subcommand)."""

    invoked_subcommand = None

    def get_help(self) -> str:  # pragma: no cover - only the TTY branch is hit
        return "help"


def _bare_context() -> _BareCtx:
    return _BareCtx()


class _FakeSys:
    """A ``sys`` proxy with TTY ``stdin``/``stdout``, delegating the rest.

    pytest's capture plugin owns the real ``sys.stdout``, so patching its
    ``isatty`` in place is brittle. Instead we replace the ``sys`` reference the
    dispatcher reads through with this proxy: the two stream attributes report a
    terminal, and every other attribute falls through to the real module.
    """

    def __init__(self, real: object) -> None:
        self._real = real
        self.stdin = _FakeTTY()
        self.stdout = _FakeTTY()

    def __getattr__(self, name: str) -> object:
        # Stored in __dict__, so ``_real`` itself never recurses here.
        return getattr(self._real, name)


@pytest.fixture
def force_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make both stdin and stdout report as a TTY for the dispatcher.

    The dispatch branches gate the interactive TUIs on
    ``sys.stdin.isatty() and sys.stdout.isatty()``. We swap the dispatcher's
    ``sys`` reference for a proxy so the predicate is True. These tests call the
    command callables directly rather than through ``CliRunner`` (which would
    re-substitute its own non-TTY streams during ``invoke``).
    """
    monkeypatch.setattr(cli, "sys", _FakeSys(cli.sys))


# ---------------------------------------------------------------------------
# version — fallbacks when the package metadata is unavailable
# ---------------------------------------------------------------------------


class TestVersionFallback:
    def test_falls_back_to_in_tree_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A checkout without ``uv tool install`` has no dist metadata, so the
        command reads the importable ``__version__`` instead."""

        def _missing(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError

        monkeypatch.setattr(importlib.metadata, "version", _missing)

        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        import mait_code

        assert result.output.strip() == mait_code.__version__

    def test_prints_unknown_and_exits_1_without_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If neither dist metadata nor an importable ``__version__`` exists,
        the command says so and exits non-zero rather than crashing."""
        import builtins

        def _missing(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError

        monkeypatch.setattr(importlib.metadata, "version", _missing)

        real_import = builtins.__import__

        def _blocked_import(name: str, *args: object, **kwargs: object):
            # Only the in-tree __version__ lookup should fail; everything else
            # (typer internals etc.) must still import normally.
            if name == "mait_code" and "__version__" in (args[2] or ()):  # fromlist
                raise ImportError("no __version__")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", _blocked_import)

        result = runner.invoke(app, ["version"])
        assert result.exit_code == 1
        assert result.output.strip() == "unknown"


# ---------------------------------------------------------------------------
# --no-color — root callback toggles the shared consoles
# ---------------------------------------------------------------------------


class TestNoColor:
    def test_no_color_flag_disables_colour_on_both_consoles(self) -> None:
        """``--no-color`` propagates to stdout *and* the stderr twin, so
        warnings/errors are decoloured too."""
        from mait_code.console import console, err_console

        # ``home`` off a TTY prints text and exits 0 — a cheap subcommand to
        # carry the root flag through the callback.
        result = runner.invoke(app, ["--no-color", "home"])
        assert result.exit_code == 0
        assert console.no_color is True
        assert err_console.no_color is True


# ---------------------------------------------------------------------------
# Bare invocation on a TTY opens the home hub
# ---------------------------------------------------------------------------


def test_bare_invocation_on_tty_opens_home_loop(
    monkeypatch: pytest.MonkeyPatch, force_tty: None
) -> None:
    """With no subcommand and a real terminal, ``mait-code`` is the front
    door — it runs the home loop instead of printing help.

    The root callback is invoked directly with a context whose
    ``invoked_subcommand`` is ``None`` (the bare-invocation case).
    """
    called: list[str] = []
    monkeypatch.setattr(cli, "_run_home_loop", lambda: called.append("home"))

    ctx = _bare_context()
    cli._root(ctx, no_color=False)
    assert called == ["home"]


# ---------------------------------------------------------------------------
# Per-command TUI launch (the TTY branch of each browse command)
# ---------------------------------------------------------------------------


class TestTuiLaunchRouting:
    """Each browse command launches its own TUI when on a TTY.

    We patch the launcher at its source module (the command imports it lazily
    inside the function body, so patching the origin is what takes effect).
    """

    def test_home_command_runs_home_loop(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None
    ) -> None:
        called: list[str] = []
        monkeypatch.setattr(cli, "_run_home_loop", lambda: called.append("home"))
        cli.home()
        assert called == ["home"]

    def test_board_command_launches_board_tui(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None
    ) -> None:
        called: list[str] = []
        monkeypatch.setattr(
            "mait_code.cli._board_tui.run_board_tui",
            lambda: called.append("board"),
        )
        cli.board()
        assert called == ["board"]

    def test_memory_command_launches_memory_tui(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None
    ) -> None:
        called: list[str] = []
        monkeypatch.setattr(
            "mait_code.cli._memory_tui.run_memory_tui",
            lambda: called.append("memory"),
        )
        cli.memory()
        assert called == ["memory"]

    def test_graph_command_launches_graph_tui(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None
    ) -> None:
        called: list[str] = []
        monkeypatch.setattr(
            "mait_code.cli._graph_tui.run_graph_tui",
            lambda: called.append("graph"),
        )
        cli.graph()
        assert called == ["graph"]

    def test_observations_command_launches_observations_tui(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None
    ) -> None:
        called: list[str] = []
        monkeypatch.setattr(
            "mait_code.cli._observations_tui.run_observations_tui",
            lambda: called.append("observations"),
        )
        cli.observations()
        assert called == ["observations"]

    def test_logs_command_launches_logs_tui(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None
    ) -> None:
        called: list[str] = []
        monkeypatch.setattr(
            "mait_code.cli._logs_tui.run_logs_tui",
            lambda: called.append("logs"),
        )
        cli.logs()
        assert called == ["logs"]


# ---------------------------------------------------------------------------
# settings — TTY branch opens the interactive editor
# ---------------------------------------------------------------------------


class TestSettingsTuiRouting:
    def test_settings_on_tty_opens_interactive_editor(
        self, monkeypatch: pytest.MonkeyPatch, force_tty: None, fake_home
    ) -> None:
        """``settings`` with no subcommand on a TTY launches the editor (after
        the settings-file guard passes)."""
        from mait_code import config

        config.write_settings_file({"embedding-provider": "local"})
        called: list[str] = []
        monkeypatch.setattr(
            "mait_code.cli._settings_tui.run_interactive_editor",
            lambda: called.append("editor"),
        )
        cli.settings_root(_bare_context())
        assert called == ["editor"]

    def test_settings_on_tty_still_guards_missing_file(
        self, force_tty: None, fake_home
    ) -> None:
        """The settings-file guard fires before the TTY check, so a missing
        file aborts even on a terminal rather than opening an empty editor."""
        with pytest.raises(typer.Exit) as excinfo:
            cli.settings_root(_bare_context())
        assert excinfo.value.exit_code == 1


# ---------------------------------------------------------------------------
# _run_home_loop — every HomeTarget routes to its TUI launcher
# ---------------------------------------------------------------------------


class TestHomeLoopTargets:
    """The home loop hands off to the TUI for whichever target home returns,
    then re-enters home; ``None`` ends the loop. ``test_home_cmd`` covers the
    BOARD/SETTINGS pair, so here we exercise the remaining targets and the
    full mapping in one sweep."""

    def test_each_target_routes_to_its_launcher(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Home returns each target once, in order, then quits.
        targets = iter(
            [
                HomeTarget.MEMORY,
                HomeTarget.OBSERVATIONS,
                HomeTarget.GRAPH,
                HomeTarget.LOGS,
                None,
            ]
        )
        launched: list[str] = []

        monkeypatch.setattr(
            "mait_code.cli._home_tui.run_home_tui", lambda: next(targets)
        )
        monkeypatch.setattr(
            "mait_code.cli._memory_tui.run_memory_tui",
            lambda: launched.append("memory"),
        )
        monkeypatch.setattr(
            "mait_code.cli._observations_tui.run_observations_tui",
            lambda: launched.append("observations"),
        )
        monkeypatch.setattr(
            "mait_code.cli._graph_tui.run_graph_tui",
            lambda: launched.append("graph"),
        )
        monkeypatch.setattr(
            "mait_code.cli._logs_tui.run_logs_tui",
            lambda: launched.append("logs"),
        )

        cli._run_home_loop()

        assert launched == ["memory", "observations", "graph", "logs"]

    def test_quits_immediately_when_home_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the user quits home straight away, no sibling TUI is launched."""
        monkeypatch.setattr("mait_code.cli._home_tui.run_home_tui", lambda: None)
        # No launcher patched: any launch attempt would raise on the real TUI.
        cli._run_home_loop()  # must simply return


# ---------------------------------------------------------------------------
# settings set — followup-message branches
# ---------------------------------------------------------------------------


class TestSettingsSetFollowups:
    """``settings set`` prints distinct follow-up lines depending on the
    outcome's ``followup``/``followup_done`` fields. We drive these via a
    stubbed ``apply_setting`` so we exercise the dispatcher's messaging without
    depending on a real migration."""

    def _stub_outcome(self, **kw: object):
        from mait_code.cli._settings_edit import ApplyOutcome

        defaults: dict[str, object] = {
            "key": "data-dir",
            "old_value": "/old",
            "new_value": "/new",
            "warnings": [],
            "followup": None,
            "followup_done": False,
        }
        defaults.update(kw)
        return ApplyOutcome(**defaults)  # type: ignore[arg-type]

    def test_reindex_done_message(
        self, monkeypatch: pytest.MonkeyPatch, fake_home
    ) -> None:
        from mait_code import config

        config.write_settings_file({"embedding-provider": "local"})
        outcome = self._stub_outcome(followup="reindex", followup_done=True)
        monkeypatch.setattr(cli, "apply_setting", lambda *a, **k: outcome)

        result = runner.invoke(app, ["settings", "set", "data-dir", "/new"])
        assert result.exit_code == 0, result.output
        assert "re-embedded stored memories" in result.output

    def test_reindex_deferred_message(
        self, monkeypatch: pytest.MonkeyPatch, fake_home
    ) -> None:
        from mait_code import config

        config.write_settings_file({"embedding-provider": "local"})
        outcome = self._stub_outcome(followup="reindex", followup_done=False)
        monkeypatch.setattr(cli, "apply_setting", lambda *a, **k: outcome)

        result = runner.invoke(app, ["settings", "set", "data-dir", "/new"])
        assert result.exit_code == 0, result.output
        assert "deferred re-embed" in result.output

    def test_move_data_done_message(
        self, monkeypatch: pytest.MonkeyPatch, fake_home
    ) -> None:
        from mait_code import config

        config.write_settings_file({"embedding-provider": "local"})
        outcome = self._stub_outcome(
            followup="move-data", followup_done=True, warnings=["heads up"]
        )
        monkeypatch.setattr(cli, "apply_setting", lambda *a, **k: outcome)

        result = runner.invoke(app, ["settings", "set", "data-dir", "/new"])
        assert result.exit_code == 0, result.output
        assert "moved existing data" in result.output
        # The warnings loop is reached too.
        assert "heads up" in result.output

    def test_move_data_left_message(
        self, monkeypatch: pytest.MonkeyPatch, fake_home
    ) -> None:
        from mait_code import config

        config.write_settings_file({"embedding-provider": "local"})
        outcome = self._stub_outcome(followup="move-data", followup_done=False)
        monkeypatch.setattr(cli, "apply_setting", lambda *a, **k: outcome)

        result = runner.invoke(app, ["settings", "set", "data-dir", "/new"])
        assert result.exit_code == 0, result.output
        assert "left existing data" in result.output


# ---------------------------------------------------------------------------
# settings set env.<NAME> — warnings loop after a successful env write
# ---------------------------------------------------------------------------


def test_settings_set_env_emits_warnings(
    monkeypatch: pytest.MonkeyPatch, fake_home
) -> None:
    """A successful ``env.<NAME>`` write surfaces any warnings from the
    outcome (e.g. a shadowing shell export)."""
    from mait_code import config
    from mait_code.cli._settings_edit import EnvOutcome

    config.write_settings_file({"embedding-provider": "local"})
    outcome = EnvOutcome(
        name="AWS_PROFILE",
        old_value=None,
        new_value="dev",
        warnings=["a real shell export still shadows this"],
    )
    monkeypatch.setattr(cli, "_set_env_var", lambda *a, **k: outcome)

    result = runner.invoke(app, ["settings", "set", "env.AWS_PROFILE", "dev"])
    assert result.exit_code == 0, result.output
    assert "env.AWS_PROFILE" in result.output
    assert "shadows this" in result.output


# ---------------------------------------------------------------------------
# main — exception passthrough (pretty exceptions disabled)
# ---------------------------------------------------------------------------


def test_unknown_subcommand_exits_nonzero() -> None:
    """An unrecognised subcommand is a usage error (exit 2), not a launch."""
    result = runner.invoke(app, ["definitely-not-a-command"])
    assert result.exit_code != 0


def test_settings_get_env_resolves_after_set(fake_home) -> None:
    """Sanity check that a typer.Exit from the get guard maps to a clean exit
    rather than a traceback (pretty exceptions are disabled on the app)."""
    from mait_code import config

    config.write_settings_file({"embedding-provider": "local"})
    result = runner.invoke(app, ["settings", "get", "env.NOPE"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit) or result.exception is None


# ---------------------------------------------------------------------------
# board / graph — non-TTY text fallbacks
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the data dir at the test tmp path, bypassing the settings cache."""
    import mait_code.config as config

    monkeypatch.setenv("MAIT_CODE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "_settings_cache", None)


class TestBoardFallback:
    """``board`` off a TTY prints the grouped text render (CliRunner streams are
    never TTYs, so this is the branch it takes)."""

    def test_empty_board(self, isolated_data_dir: None) -> None:
        result = runner.invoke(app, ["board"])
        assert result.exit_code == 0
        assert "No cards on the board." in result.output

    def test_grouped_render(self, isolated_data_dir: None) -> None:
        from mait_code.tools.board import service
        from mait_code.tools.board.db import get_connection

        conn = get_connection()
        try:
            service.add_card(conn, project="demo", title="A card", priority="high")
        finally:
            conn.close()

        result = runner.invoke(app, ["board"])
        assert result.exit_code == 0
        assert "A card" in result.output
        assert "[demo]" in result.output
        # Grouped under a column label with a per-column count.
        assert "(1):" in result.output


class TestGraphFallback:
    def test_empty_graph(self, isolated_data_dir: None) -> None:
        """An empty store reports that the graph grows as sessions run."""
        result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "No connected entities yet" in result.output

    def test_connected_entities_render(self, isolated_data_dir: None, tmp_path) -> None:
        """Two entities with a relationship and enough mentions surface in the
        text summary with their type, mention count, and link tally."""
        from mait_code.tools.memory.db import get_connection

        conn = get_connection(tmp_path / "memory.db")
        try:
            conn.execute(
                "INSERT INTO memory_entities (name, entity_type, mention_count) "
                "VALUES ('Cody', 'person', 3)"
            )
            conn.execute(
                "INSERT INTO memory_entities (name, entity_type, mention_count) "
                "VALUES ('Whippet', 'concept', 2)"
            )
            conn.execute(
                "INSERT INTO memory_relationships "
                "(source_entity_id, target_entity_id, relationship_type) "
                "VALUES (1, 2, 'is_a')"
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["graph"])
        assert result.exit_code == 0
        assert "Knowledge graph: 2 connected entities" in result.output
        assert "Cody" in result.output
        # Singular "link" when degree is 1.
        assert "1 link" in result.output


def test_observations_truncates_long_day(isolated_data_dir: None, tmp_path) -> None:
    """A day with more than five observations prints the first five and an
    ``… and N more`` line — the truncation branch."""
    from mait_code.tools.memory.db import get_connection

    conn = get_connection(tmp_path / "memory.db")
    try:
        for i in range(7):
            conn.execute(
                """INSERT INTO memory_entries
                   (content, entry_type, importance, memory_class, created_at)
                   VALUES (?, 'decision', 5, 'episodic', '2026-06-02 10:00:00')""",
                (f"decision number {i}",),
            )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(app, ["observations"])
    assert result.exit_code == 0
    assert "… and 2 more" in result.output
