"""Tests for the shared rich console substrate.

These pin the two guarantees the rest of the CLI relies on: the theme
actually styles when colour is on, and colour is suppressed both by the
``--no-color`` mechanism (``console.no_color``) and by the ``NO_COLOR``
environment variable (the clig.dev / no-color.org contract).
"""

from __future__ import annotations

import pytest
from rich.console import Console

from mait_code.console import GLYPH, THEME, console, err_console, print_error


def _render(c: Console, markup: str) -> str:
    """Capture what ``c`` would write for ``markup``, ANSI and all."""
    with c.capture() as cap:
        c.print(markup)
    return cap.get()


def test_glyphs_cover_all_doctor_levels() -> None:
    assert set(GLYPH) == {"ok", "warn", "fail"}


def test_theme_styles_emit_ansi_on_a_colour_terminal() -> None:
    c = Console(theme=THEME, force_terminal=True, color_system="truecolor")
    out = _render(c, "[fail]boom[/fail]")
    assert "boom" in out
    assert "\x1b[" in out  # the theme genuinely styles when colour is on


def test_no_color_attribute_strips_ansi() -> None:
    # `no_color` (what `--no-color` toggles at runtime) drops colour but, per
    # the NO_COLOR contract, leaves bold/underline alone — so test a
    # colour-only style to assert all styling is gone.
    c = Console(
        theme=THEME, force_terminal=True, color_system="truecolor", no_color=True
    )
    out = _render(c, "[ok]boom[/ok]")
    assert "boom" in out
    assert "\x1b[" not in out


def test_no_color_env_var_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    c = Console(theme=THEME, force_terminal=True, color_system="truecolor")
    out = _render(c, "[ok]hi[/ok]")
    assert "hi" in out
    assert "\x1b[" not in out


def test_shared_console_resolves_theme_styles() -> None:
    # Unknown style names raise; this proves the shared console carries THEME.
    _render(console, "[accent]ok[/accent] [muted]dim[/muted]")


def test_err_console_writes_to_stderr() -> None:
    assert err_console.stderr is True
    # Carries the same theme as the stdout console, so [fail] resolves.
    _render(err_console, "[fail]boom[/fail]")


def test_print_error_prefixes_glyph(capsys: pytest.CaptureFixture[str]) -> None:
    print_error("something broke")
    captured = capsys.readouterr()
    assert captured.out == ""  # errors never pollute stdout
    assert GLYPH["fail"] in captured.err
    assert "something broke" in captured.err


def test_print_error_escapes_markup(capsys: pytest.CaptureFixture[str]) -> None:
    # A path or exception string with brackets must render literally, not be
    # swallowed as (or crash on) rich markup.
    print_error("cannot read [bold]/etc/foo[/bold] config")
    captured = capsys.readouterr()
    assert "[bold]/etc/foo[/bold]" in captured.err
