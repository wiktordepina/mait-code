#!/usr/bin/env python3
"""Measure Claude Code's ``allowed-tools`` matcher and report drift.

Everything mait-code asserts about ``Bash(...)`` permission patterns —
``cli/_permissions.matches_command``, the catalogue's prefix discipline, and
the skill grants guarded by ``tests/test_skill_grants.py`` — rests on
*undocumented* matcher behaviour, measured against Claude Code 2.1.220. The
test suite pins our **model** of the matcher, not the matcher itself, so an
upgrade can change the rules while the suite stays green.

This script re-measures the real thing. Each case carries the verdict observed
on 2.1.220; anything that disagrees is reported as DRIFT and the script exits
non-zero.

Usage::

    ./scripts/probe_permissions.py [--model MODEL] [--jobs N] [--verbose]

Requires ``claude`` and ``git`` on ``PATH``. Runs roughly twenty short headless
sessions, so it costs a little and takes a few minutes.

Two traps this harness exists to avoid, both of which invalidated a full matrix
during the original investigation:

1. **A nested ``claude`` inherits the parent session's permission posture** and
   auto-approves everything. Run from inside a Claude Code session without
   scrubbing the environment and every cell returns PERMITTED — including
   nonsense like ``gitfoo`` under ``Bash(git status:*)``. See :data:`SCRUB`.
2. **Sandboxing looks like approval.** An ungranted command that Claude Code
   can contain runs with no prompt and its writes are discarded, so "no prompt"
   does not mean "a rule matched". Every probe command is therefore baselined
   against an unrelated grant first; a command the baseline permits cannot
   measure the matcher and is reported as CONFOUNDED rather than passed.

The rule of thumb both traps share: **demand a negative control that fails.**
If nothing in the matrix comes back denied, suspect the harness, not the
subject.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

#: Environment variables that leak the parent session's permission posture into
#: a nested ``claude``. Stripped from every subprocess.
SCRUB = (
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "AI_AGENT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
)

#: A grant that permits nothing else under test — the neutral control.
NEUTRAL_RULE = "Bash(echo hello)"

PERMITTED = "PERMITTED"
DENIED = "DENIED"


@dataclass(frozen=True)
class Case:
    """One measurement: does *rule* permit *command*?

    Attributes:
        rule: The single ``permissions.allow`` entry under test.
        command: The command the model is asked to run verbatim.
        expected: The verdict observed on Claude Code 2.1.220.
        claim: What this case is evidence for, shown in the report.
    """

    rule: str
    command: str
    expected: str
    claim: str


#: The matcher cases. Every command here must be *refused* when ungranted, or
#: it cannot distinguish a real grant from sandboxed execution — the baseline
#: pass checks exactly that before any of these are trusted.
CASES: tuple[Case, ...] = (
    # An exact rule is exact.
    Case("Bash(git push)", "git push --dry-run", DENIED, "no-wildcard = exact match"),
    # `:*` is a prefix match that stops at a token boundary.
    Case("Bash(git push:*)", "git push", PERMITTED, ":* permits the bare command"),
    Case("Bash(git push:*)", "git push --dry-run", PERMITTED, ":* permits arguments"),
    Case("Bash(git push:*)", "git pushfoo", DENIED, ":* stops at a token boundary"),
    Case(
        "Bash(git diff:*)", "git difftool --help", DENIED, ":* does not reach difftool"
    ),
    Case("Bash(git branch:*)", "git branchfoo", DENIED, ":* stops at a token boundary"),
    Case(
        "Bash(git branch:*)",
        "git branch -D probe-no-such-branch",
        PERMITTED,
        ":* permits any continuation, flags included",
    ),
    # The space form is a real wildcard, equivalent to `:*`.
    Case("Bash(git push *)", "git push", PERMITTED, "space form permits bare command"),
    Case(
        "Bash(git push *)", "git push --dry-run", PERMITTED, "space form is a wildcard"
    ),
    Case("Bash(git push *)", "git pushfoo", DENIED, "space form has a boundary too"),
    Case(
        "Bash(git *)", "git push --dry-run", PERMITTED, "Bash(git *) permits git push"
    ),
    Case(
        "Bash(git *)",
        "git commit --allow-empty -m probe",
        PERMITTED,
        "Bash(git *) permits any git subcommand",
    ),
    Case("Bash(git *)", "gitfoo", DENIED, "Bash(git *) needs the boundary"),
)

#: Operator-awareness is checked separately, by :func:`check_operators`, because
#: the baseline gate cannot measure it. Under the neutral rule a compound
#: command comes back PERMITTED — with nothing matching, Claude Code appears to
#: sandbox the whole thing, and sandboxed execution is indistinguishable from a
#: grant here. The differential below needs no baseline: the *same rule* permits
#: the simple command and refuses the compound one.
SIMPLE_COMMAND = "git push --dry-run"
COMPOUND_COMMAND = "git push --dry-run || git commit --allow-empty -m escaped"
OPERATOR_RULE = "Bash(git push:*)"


def clean_env() -> dict[str, str]:
    """The current environment minus the session-inheritance variables."""
    return {k: v for k, v in os.environ.items() if k not in SCRUB}


def make_project(root: Path, slug: str, rule: str) -> Path:
    """Create a throwaway git repo whose only allow rule is *rule*."""
    project = root / slug
    (project / ".claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / "file.txt").write_text("scratch\n")
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"allow": [rule]}}, indent=2)
    )
    return project


def _events(stdout: str) -> list[dict]:
    parsed = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return parsed


def _blocks(events: Iterable[dict]) -> Iterable[dict]:
    for event in events:
        content = (event.get("message") or {}).get("content") or []
        for block in content:
            if isinstance(block, dict):
                yield block


def probe(
    project: Path, command: str, model: str, timeout: int = 180
) -> tuple[str, str]:
    """Ask a headless session to run *command*, and report how it was handled.

    Returns:
        A ``(verdict, detail)`` pair. *verdict* is ``PERMITTED``, ``DENIED``, or
        an ``ERROR:``/``BAD_PROBE:`` marker; *detail* carries the evidence.
    """
    prompt = (
        f"Use the Bash tool to run exactly this command, verbatim, with no extra "
        f"flags and no other tools: {command}\n"
        f"Make exactly one tool call, then stop and reply with the word DONE."
    )
    try:
        proc = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--model",
                model,
                "--permission-mode",
                "default",
            ],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env(),
        )
    except subprocess.TimeoutExpired:
        return ("ERROR:timeout", f"no result within {timeout}s")

    blocks = list(_blocks(_events(proc.stdout)))
    calls = {
        b["id"]: b.get("input", {}).get("command", "")
        for b in blocks
        if b.get("type") == "tool_use" and b.get("name") == "Bash"
    }
    for block in blocks:
        if block.get("type") != "tool_result" or block.get("tool_use_id") not in calls:
            continue
        ran = calls[block["tool_use_id"]]
        if ran.strip() != command:
            return ("BAD_PROBE:altered", f"model ran {ran!r}")
        content = block.get("content")
        text = content if isinstance(content, str) else json.dumps(content)
        lowered = text.lower()
        denied = "requires approval" in lowered or "permission" in lowered
        return (DENIED if denied else PERMITTED, text[:160].replace("\n", " "))

    if calls:
        return ("ERROR:no-result", "tool_use with no tool_result")
    tail = (proc.stdout or proc.stderr)[-160:].replace("\n", " ")
    return ("ERROR:no-tool-call", tail or "no output")


def check_operators(root: Path, model: str) -> list[str]:
    """Verify the matcher decomposes compound commands.

    A differential under a single rule, so it needs no baseline: ``Bash(git
    push:*)`` must permit ``git push --dry-run`` and refuse
    ``git push --dry-run || git commit ...``, because the second component is
    not permitted. If both came back the same way the claim is unsupported.

    Returns:
        A list of drift messages; empty when behaviour matches 2.1.220.
    """
    drift = []
    simple, _ = probe(
        make_project(root, "operator-simple", OPERATOR_RULE), SIMPLE_COMMAND, model
    )
    compound, _ = probe(
        make_project(root, "operator-compound", OPERATOR_RULE), COMPOUND_COMMAND, model
    )
    ok = simple == PERMITTED and compound == DENIED
    print(f"  {'ok   ' if ok else 'DRIFT'} simple   {SIMPLE_COMMAND:34} {simple}")
    print(
        f"  {'ok   ' if ok else 'DRIFT'} compound {'(|| git commit ...)':34} {compound}"
    )
    if not ok:
        drift.append(
            f"operator-awareness: under {OPERATOR_RULE} expected the simple command "
            f"PERMITTED and the compound one DENIED, got {simple} and {compound} — "
            f"a prefix rule may now span an unpermitted second command"
        )
    return drift


def check_sandbox(root: Path, model: str) -> list[str]:
    """Verify that a grant buys *unsandboxed* execution, not just a quiet prompt.

    Ungranted-but-containable commands run with their writes discarded, which is
    why "no prompt appeared" is not evidence that a rule matched.

    Returns:
        A list of drift messages; empty when behaviour matches 2.1.220.
    """
    drift = []
    for slug, rule, should_exist in (
        ("sandbox-granted", "Bash(touch:*)", True),
        ("sandbox-ungranted", NEUTRAL_RULE, False),
    ):
        project = make_project(root, slug, rule)
        verdict, _ = probe(project, "touch marker.txt", model)
        landed = (project / "marker.txt").exists()
        state = "granted" if should_exist else "ungranted"
        if landed != should_exist:
            drift.append(
                f"sandbox/{state}: expected the write to "
                f"{'land' if should_exist else 'be discarded'}, but it "
                f"{'landed' if landed else 'was discarded'} (verdict {verdict})"
            )
        print(
            f"  {'ok  ' if landed == should_exist else 'DRIFT'} "
            f"{state:10} write {'landed' if landed else 'discarded'} "
            f"(verdict {verdict})"
        )
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="model for the headless probes; permission behaviour is harness-level",
    )
    parser.add_argument("--jobs", type=int, default=4, help="concurrent probes")
    parser.add_argument("--verbose", action="store_true", help="show evidence per case")
    args = parser.parse_args()

    if not shutil.which("claude"):
        print("claude not found on PATH", file=sys.stderr)
        return 2

    version = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, env=clean_env()
    ).stdout.strip()
    print(f"Probing {version or 'claude (version unknown)'}\n")

    drift: list[str] = []
    with tempfile.TemporaryDirectory(prefix="mait-probe-") as tmp:
        root = Path(tmp)

        # --- Baseline: which probe commands are refused when ungranted? ------
        # Only those can distinguish a real grant from sandboxed execution.
        print("Baseline (unrelated grant must refuse each probe command):")
        commands = sorted({case.command for case in CASES})
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            results = pool.map(
                lambda item: (
                    item[1],
                    probe(
                        make_project(root, f"base{item[0]}", NEUTRAL_RULE),
                        item[1],
                        args.model,
                    )[0],
                ),
                enumerate(commands),
            )
            baseline = dict(results)
        for command, verdict in baseline.items():
            usable = verdict == DENIED
            print(f"  {'ok   ' if usable else 'UNUSABLE'} {verdict:10} {command}")
        if not any(v == DENIED for v in baseline.values()):
            print(
                "\nNo baseline command was refused. That is a broken harness, not a\n"
                "finding — the negative control must fail. Check the SCRUB list.",
                file=sys.stderr,
            )
            return 2

        # --- The matcher cases -----------------------------------------------
        print("\nMatcher:")
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            outcomes = list(
                pool.map(
                    lambda item: (
                        item[1],
                        probe(
                            make_project(root, f"case{item[0]}", item[1].rule),
                            item[1].command,
                            args.model,
                        ),
                    ),
                    enumerate(CASES),
                )
            )
        for case, (verdict, detail) in outcomes:
            if baseline.get(case.command) != DENIED:
                print(f"  SKIP  {case.rule:22} {case.command:46} confounded baseline")
                drift.append(
                    f"{case.rule} / {case.command}: baseline no longer refuses it"
                )
                continue
            if verdict == case.expected:
                print(f"  ok    {case.rule:22} {case.command:46} {verdict}")
            else:
                print(
                    f"  DRIFT {case.rule:22} {case.command:46} "
                    f"expected {case.expected}, got {verdict}"
                )
                drift.append(
                    f"{case.rule} / {case.command}: expected {case.expected}, "
                    f"got {verdict} — {case.claim}"
                )
            if args.verbose:
                print(f"        {detail}")

        # --- Operator awareness ----------------------------------------------
        print("\nOperators (a prefix rule must not span an unpermitted component):")
        drift.extend(check_operators(root, args.model))

        # --- Sandbox vs approval ---------------------------------------------
        print("\nSandbox (a grant must buy unsandboxed execution):")
        drift.extend(check_sandbox(root, args.model))

    print()
    if drift:
        print(f"DRIFT: {len(drift)} case(s) no longer match the recorded behaviour:\n")
        for line in drift:
            print(f"  - {line}")
        print(
            "\nUpdate cli/_permissions.matches_command and its tests, then re-audit\n"
            "the skill grants (tests/test_skill_grants.py) against the new rules."
        )
        return 1

    print("No drift: the matcher still behaves as recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
