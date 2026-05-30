"""Shared Textual TUI layer for mait-code.

The colour source of truth is :mod:`mait_code.tui.palette` (pure data &mdash; safe
to import from the CLI hot path; it pulls in no Textual). The Textual theme
lives in :mod:`mait_code.tui.theme` and the base app in
:mod:`mait_code.tui.app`; import those submodules directly when you need them
(they pull in Textual), e.g. ``from mait_code.tui.app import MaitApp``.

This package's ``__init__`` deliberately imports only :mod:`~mait_code.tui.palette`
so that importing it stays Textual-free.
"""

from __future__ import annotations

from mait_code.tui import palette

__all__ = ["palette"]
