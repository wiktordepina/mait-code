"""Tests for the ``mc-tool-web-fetch`` CLI entrypoint (``main``).

``main`` parses args, calls ``fetch_url`` and (unless ``--raw``)
``convert_content``, and prints the result. The fetch/convert layers are
covered directly in ``test_fetch.py`` / ``test_convert.py``; here we mock them
so no real network is touched and only the CLI wiring — arg plumbing, the
raw-vs-markdown branch, charset fallback, and error handling — is exercised.

``main`` imports ``fetch_url``/``convert_content`` lazily from their modules,
so the mocks are installed on those source modules (the lookup happens at call
time).
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import pytest

from mait_code.tools.web_fetch import cli as cli_mod
from mait_code.tools.web_fetch.fetch import FetchError, FetchResult


def _result(**over) -> FetchResult:
    base = dict(
        url="https://example.com",
        status_code=200,
        content_type="text/html",
        charset="utf-8",
        body=b"<h1>Hi</h1>",
    )
    base.update(over)
    return FetchResult(**base)


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    fetch: Callable | None = None,
    convert: Callable | None = None,
) -> None:
    monkeypatch.setattr(sys, "argv", ["mc-tool-web-fetch", *argv])
    if fetch is not None:
        monkeypatch.setattr("mait_code.tools.web_fetch.fetch.fetch_url", fetch)
    if convert is not None:
        monkeypatch.setattr(
            "mait_code.tools.web_fetch.convert.convert_content", convert
        )
    cli_mod.main()


def test_main_markdown_output(monkeypatch, capsys):
    _run_main(
        monkeypatch,
        ["https://example.com"],
        fetch=lambda *a, **k: _result(body=b"<h1>Title</h1>"),
        convert=lambda *a, **k: "# Title",
    )
    out = capsys.readouterr().out
    assert "URL: https://example.com" in out
    assert "Content-Type: text/html" in out
    assert "---" in out
    assert "# Title" in out


def test_main_plumbs_args_to_fetch(monkeypatch, capsys):
    captured: dict = {}

    def fake_fetch(url, *, timeout, max_size, allow_private):
        captured.update(
            url=url, timeout=timeout, max_size=max_size, allow_private=allow_private
        )
        return _result()

    _run_main(
        monkeypatch,
        [
            "https://example.com",
            "--timeout",
            "5",
            "--max-size",
            "1234",
            "--allow-private",
        ],
        fetch=fake_fetch,
        convert=lambda *a, **k: "x",
    )
    assert captured == {
        "url": "https://example.com",
        "timeout": 5,
        "max_size": 1234,
        "allow_private": True,
    }


def test_main_raw_skips_conversion(monkeypatch, capsys):
    _run_main(
        monkeypatch,
        ["https://example.com", "--raw"],
        fetch=lambda *a, **k: _result(
            body=b"plain body text", content_type="text/plain"
        ),
    )
    out = capsys.readouterr().out
    assert "plain body text" in out
    assert "Content-Type:" not in out  # the header block is markdown-only


def test_main_raw_truncates_to_max_chars(monkeypatch, capsys):
    _run_main(
        monkeypatch,
        ["https://example.com", "--raw", "--max-chars", "4"],
        fetch=lambda *a, **k: _result(body=b"abcdefghij"),
    )
    assert capsys.readouterr().out.strip() == "abcd"


def test_main_raw_bad_charset_falls_back_to_utf8(monkeypatch, capsys):
    # A bogus charset raises LookupError on decode; the fallback still prints.
    _run_main(
        monkeypatch,
        ["https://example.com", "--raw"],
        fetch=lambda *a, **k: _result(
            body="héllo".encode("utf-8"), charset="not-a-charset"
        ),
    )
    assert "héllo" in capsys.readouterr().out


def test_main_fetch_error_exits_nonzero(monkeypatch, capsys):
    def boom(*a, **k):
        raise FetchError("boom")

    with pytest.raises(SystemExit, match="1"):
        _run_main(monkeypatch, ["https://example.com"], fetch=boom)
    assert "Error fetching https://example.com: boom" in capsys.readouterr().err
