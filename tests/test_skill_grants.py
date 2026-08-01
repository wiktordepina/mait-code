"""Guard the ``allowed-tools`` grants in ``skills/*/SKILL.md``.

Skill frontmatter is governed by the same matcher as the tool-approval
catalogue, but nothing was checking it. #100 found several skills holding the
full write surface of a store they only read from — ``recall`` could
``mc-tool-memory delete``, ``reminders`` could ``set`` and ``dismiss``, and
``commit`` held an unrestricted ``Bash(git *)``.

These tests pin the two properties that matter: no skill grants a command it
has no business running, and every pattern uses the measured, boundary-aware
``:*`` form rather than the older space form.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mait_code.cli import _permissions as perms

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

#: Commands a skill must never permit unprompted, mapped to why. Destructive,
#: irreversible, or simply outside every skill's remit.
FORBIDDEN = {
    "mc-tool-board remove 3": "destructive and unrecoverable by the board's own docs",
    "mc-tool-memory delete 3": "irreversible memory deletion",
    "mc-tool-memory reindex": "rebuilds the whole index",
    "mc-tool-memory restore": "overwrites the store",
    "mc-tool-inbox drain": "empties the inbox wholesale",
    "git push origin main": "publishes; never unprompted",
    "git reset --hard HEAD~1": "discards work",
    "git clean -fdx": "deletes untracked files",
    "git rebase -i HEAD~3": "rewrites history",
    "git commit --amend": "rewrites the previous commit",
    "git difftool --extcmd=rm": "arbitrary command execution",
    "git checkout -- .": "discards working-tree changes",
}


def _grants() -> dict[str, list[str]]:
    """Map skill name to its ``Bash(...)`` patterns."""
    found: dict[str, list[str]] = {}
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        for line in skill_md.read_text().splitlines():
            if not line.startswith("allowed-tools:"):
                continue
            patterns = [
                entry.strip()
                for entry in line.split(":", 1)[1].split(", ")
                if entry.strip().startswith("Bash(")
            ]
            if patterns:
                found[skill_md.parent.name] = patterns
            break
    return found


GRANTS = _grants()


def test_skills_were_discovered() -> None:
    """A glob that silently matches nothing would make every test below vacuous."""
    assert GRANTS, f"no skill grants parsed from {SKILLS_DIR}"


@pytest.mark.parametrize("skill", sorted(GRANTS))
def test_no_skill_permits_a_forbidden_command(skill: str) -> None:
    offenders = [
        (pattern, command, reason)
        for pattern in GRANTS[skill]
        for command, reason in FORBIDDEN.items()
        if perms.matches_command(pattern, command)
    ]
    assert offenders == []


@pytest.mark.parametrize("skill", sorted(GRANTS))
def test_grants_use_the_boundary_aware_colon_form(skill: str) -> None:
    """The space form is a real wildcard (measured on 2.1.220), not a literal.

    Both forms behave identically, so this is a consistency rule rather than a
    security one — but it keeps every grant in the shape the docs describe.
    """
    space_form = [p for p in GRANTS[skill] if re.search(r" \*\)$", p)]
    assert space_form == []


@pytest.mark.parametrize("skill", sorted(GRANTS))
def test_grants_are_scoped_past_the_bare_executable(skill: str) -> None:
    """``Bash(mc-tool-board:*)`` would permit every subcommand it has.

    A wildcard directly on the executable name defeats the point of the
    catalogue's prefix discipline. ``web-fetch`` is the deliberate exception:
    the tool takes a URL, not a subcommand, so there is nothing to scope past.
    """
    if skill == "web-fetch":
        return
    bare = [
        pattern
        for pattern in GRANTS[skill]
        if re.fullmatch(r"Bash\([\w.-]+:\*\)", pattern)
    ]
    assert bare == []
