"""Interactive ``mait-code settings`` editor (questionary).

Thin glue over :func:`~mait_code.cli._settings_edit.apply_setting`: it picks a
setting, prompts for a value with live validation, and lets ``apply_setting``
own validation, persistence, env-shadow enforcement and the destructive
follow-ups. The only logic that lives here is the **grouped weight editor**,
which must retune all three scoring weights and check their sum before a single
combined write — the one change ``set`` deliberately refuses piecemeal.

Requires a TTY; the bare ``settings`` callback only routes here when attached
to one, falling back to the read-only list otherwise.
"""

from __future__ import annotations

from collections.abc import Callable

from mait_code import config
from mait_code.cli._settings_edit import (
    SettingError,
    apply_setting,
    validation_error,
)

__all__ = ["run_interactive_editor"]

_WEIGHTS_SENTINEL = "__weights__"
_EXIT_SENTINEL = "__exit__"


def run_interactive_editor() -> None:
    """Loop over the registry, editing one setting (or the weights) per pass."""
    import questionary

    while True:
        choice = _select_setting(questionary)
        if choice is None or choice == _EXIT_SENTINEL:
            return
        if choice == _WEIGHTS_SENTINEL:
            _edit_weights(questionary)
        else:
            _edit_one(questionary, choice)


def _select_setting(questionary) -> str | None:
    """Present the picker; return a setting key, a sentinel, or None to exit."""
    choices = []
    for setting in config.SETTINGS:
        if setting.key in config._WEIGHT_KEYS:
            continue  # folded into the grouped weights entry below
        value, source = config.resolve(setting)
        title = f"{setting.key:<28} {value:<24} {source}"
        if setting.settable:
            choices.append(questionary.Choice(title=title, value=setting.key))
        else:
            choices.append(
                questionary.Choice(title=title, value=setting.key, disabled="read-only")
            )

    weights = " / ".join(config.get(k) for k in config._WEIGHT_KEYS)
    choices.append(
        questionary.Choice(
            title=f"{'scoring weights…':<28} {weights:<24} grouped",
            value=_WEIGHTS_SENTINEL,
        )
    )
    choices.append(questionary.Choice(title="exit", value=_EXIT_SENTINEL))

    return questionary.select(
        "Select a setting to edit", choices=choices, use_shortcuts=False
    ).ask()


def _edit_one(questionary, key: str) -> None:
    """Prompt for a new value for *key* and apply it."""
    by_key = {s.key: s for s in config.SETTINGS}
    setting = by_key[key]
    current, _ = config.resolve(setting)

    if setting.choices:
        answer = questionary.select(
            f"{key}",
            choices=list(setting.choices),
            default=current if current in setting.choices else None,
        ).ask()
    else:
        answer = questionary.text(
            f"{key}",
            default=current,
            validate=_make_validator(setting),
        ).ask()

    if answer is None or answer == current:
        return  # cancelled or unchanged

    def confirm(prompt: str) -> bool:
        return bool(questionary.confirm(prompt, default=False).ask())

    try:
        outcome = apply_setting(key, answer, confirm=confirm)
    except SettingError as exc:
        questionary.print(f"error: {exc}", style="fg:red")
        return

    questionary.print(
        f"{outcome.key}: {outcome.old_value} → {outcome.new_value}", style="fg:green"
    )
    for warning in outcome.warnings:
        questionary.print(f"warning: {warning}", style="fg:yellow")


def _edit_weights(questionary) -> None:
    """Retune all three scoring weights, enforcing sum = 1.0 before writing."""
    by_key = {s.key: s for s in config.SETTINGS}
    new_values: dict[str, str] = {}
    for key in config._WEIGHT_KEYS:
        setting = by_key[key]
        answer = questionary.text(
            f"{key}",
            default=config.resolve(setting)[0],
            validate=_make_validator(setting),
        ).ask()
        if answer is None:
            return  # cancelled — write nothing
        new_values[key] = answer

    total = sum(float(v) for v in new_values.values())
    if abs(total - 1.0) > 1e-6:
        questionary.print(
            f"weights sum to {total:.3f}, must be 1.0 — not saved.", style="fg:red"
        )
        return

    values = config.read_settings_file()
    values.update(new_values)
    config.write_settings_file(values)
    config._settings_cache = None
    questionary.print("scoring weights updated.", style="fg:green")


def _make_validator(setting: config.Setting) -> Callable[[str], bool | str]:
    """Build a questionary validator from the setting's validation rules."""

    def validate(text: str) -> bool | str:
        msg = validation_error(setting, text)
        return True if msg is None else msg

    return validate
