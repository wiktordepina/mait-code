"""Tests for the interactive ``mait-code settings`` editor.

questionary needs a real TTY, so we exercise the thin glue by faking the
``questionary`` module — its ``select``/``text``/``confirm`` return canned
answers via ``.ask()``. The heavy lifting (validation, persistence,
follow-ups) is covered against ``apply_setting`` in ``test_settings_edit``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mait_code import config
from mait_code.cli import _settings_editor as editor


class _Ask:
    """A stand-in for a questionary question — ``.ask()`` returns a value."""

    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


class _FakeQuestionary:
    """Scripts questionary prompts: pop a queued answer per prompt call."""

    def __init__(self, *, select=None, text=None, confirm=True):
        self._select = list(select or [])
        self._text = list(text or [])
        self._confirm = confirm
        self.prints: list[str] = []

    def Choice(self, title, value, disabled=None):  # noqa: N802 — questionary API
        return SimpleNamespace(title=title, value=value, disabled=disabled)

    def select(self, *_a, **_k):
        return _Ask(self._select.pop(0))

    def text(self, *_a, **_k):
        return _Ask(self._text.pop(0))

    def confirm(self, *_a, **_k):
        return _Ask(self._confirm)

    def print(self, message, style=None):
        self.prints.append(message)


def _patch_questionary(monkeypatch: pytest.MonkeyPatch, fake: _FakeQuestionary):
    import questionary

    for name in ("Choice", "select", "text", "confirm", "print"):
        monkeypatch.setattr(questionary, name, getattr(fake, name))


class TestEditorLoop:
    def test_exit_returns_immediately(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        fake = _FakeQuestionary(select=[editor._EXIT_SENTINEL])
        _patch_questionary(monkeypatch, fake)
        editor.run_interactive_editor()  # should not raise

    def test_edit_one_persists(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        # Pick log-level, type DEBUG, then exit.
        fake = _FakeQuestionary(
            select=["log-level", "DEBUG", editor._EXIT_SENTINEL], text=["DEBUG"]
        )
        # log-level has choices → editor uses select for the value too.
        _patch_questionary(monkeypatch, fake)
        editor.run_interactive_editor()
        assert config.read_settings_file()["log-level"] == "DEBUG"

    def test_edit_text_setting_persists(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        # embedding-model has no choices → value comes from text().
        fake = _FakeQuestionary(
            select=["embedding-model", editor._EXIT_SENTINEL],
            text=["some/other-model"],
            confirm=False,  # defer the re-embed follow-up
        )
        _patch_questionary(monkeypatch, fake)
        editor.run_interactive_editor()
        assert config.read_settings_file()["embedding-model"] == "some/other-model"


class TestWeightEditor:
    def test_valid_sum_persists(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        fake = _FakeQuestionary(
            select=[editor._WEIGHTS_SENTINEL, editor._EXIT_SENTINEL],
            text=["0.2", "0.3", "0.5"],
        )
        _patch_questionary(monkeypatch, fake)
        editor.run_interactive_editor()
        values = config.read_settings_file()
        assert values["score-weight-recency"] == "0.2"
        assert values["score-weight-importance"] == "0.3"
        assert values["score-weight-relevance"] == "0.5"

    def test_invalid_sum_rejected(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config.write_settings_file({"embedding-provider": "local"})
        fake = _FakeQuestionary(
            select=[editor._WEIGHTS_SENTINEL, editor._EXIT_SENTINEL],
            text=["0.5", "0.5", "0.5"],  # sums to 1.5
        )
        _patch_questionary(monkeypatch, fake)
        editor.run_interactive_editor()
        # Nothing written for the weights.
        assert "score-weight-recency" not in config.read_settings_file()
        assert any("must be 1.0" in m for m in fake.prints)


class TestValidatorBuilder:
    def test_builds_validator_that_accepts_and_rejects(self) -> None:
        by_key = {s.key: s for s in config.SETTINGS}
        validate = editor._make_validator(by_key["log-level"])
        assert validate("DEBUG") is True
        assert isinstance(validate("LOUD"), str)
