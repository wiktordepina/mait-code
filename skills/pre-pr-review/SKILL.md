---
name: pre-pr-review
description: Run an independent review of the current branch by a reviewer that has seen none of this session's conversation, before opening a pull request. Use when you ask for a pre-PR review, a cold second opinion on a branch, or want changes scrutinised before pushing or requesting a merge.
allowed-tools: Bash(git log --oneline:*), Bash(git diff --stat:*), Bash(git status --porcelain:*), Bash(git branch --show-current)
---

# /pre-pr-review

Review the current branch with a reviewer that has seen **none of this session's conversation**.

## Current state

Branch:

!`git branch --show-current`

Commits vs main — an error here means this repo's trunk is not `main` (see step 1):

!`git log --oneline -30 main..HEAD`

Diff stat:

!`git diff --stat main...HEAD`

Uncommitted changes (these are *not* reviewed):

!`git status --porcelain`

## Why this exists

You cannot review your own work in the session that produced it. You know why every
decision was made, so you check whether the code matches the intent rather than
whether the intent was right. A reviewer who never saw that reasoning checks the
second thing — and that is where the findings that matter come from.

Everything below exists to protect that one property.

## What the reviewer *does* inherit

Isolation is not total, and overstating it is worse than not having it — a reader
who believes the reviewer knows nothing will read its agreement as independent
corroboration. Verified by probing a live subagent: it holds the project
`CLAUDE.md`, the user's identity documents, and `MEMORY.md` — which for a
mait-code project is a curated list of past decisions and feedback, i.e. exactly
the kind of framing the rule below withholds from the prompt. It does **not** hold
any of the conversation.

So the guarantee is narrower than "no context": the reviewer has not seen the
reasoning that produced this change, but it has seen the standing conventions of
the project. Discount its agreement on anything those conventions already settle.

## The contamination rule

**Pass the reviewer only: the repository path, the diff range, and the review brief.**

Never include, in the prompt or in follow-up messages:

- why the change was made, or what problem it solves
- which approach was chosen, rejected, or discussed with the user
- that you wrote it, that it is finished, or that CI is green
- a summary, changelog entry, or draft PR description
- reassurance that some part is already known to be fine

Naming a file to look at is fine. Explaining what you did to it is not. If you find
yourself writing "the author decided", stop — that sentence is the failure mode this
skill exists to prevent.

## Instructions

1. **Establish the base ref, then check the range is worth reviewing.** The blocks
   above assume the trunk is `main`. If they show a `fatal: ambiguous argument
   'main'`, this repo's trunk is something else (`master`, `develop`, a fork's
   upstream) — find it and re-run the range against that instead. Never read an
   error, or a suppressed one, as "no commits to review": a silent false negative
   here tells the user their branch is empty when it is full of work.

   Check the base is *current*, not merely present. A local `main` several commits
   behind `origin/main` moves the merge base backwards, so the review covers work
   someone else already merged — inflating an expensive run and producing findings
   on code that is not under review. Prefer `origin/main` where it exists, or say
   that the local base is stale.

   Once the range resolves: if there really are no commits ahead of the base, say so
   and stop. If the diff is trivial (a handful of lines, a docs typo, a version
   bump), say plainly what a review costs and ask whether they want it anyway,
   rather than spending that by default. If the commit list above hit its 30-entry
   cap, say so rather than letting a truncated list read as complete.

2. **Warn on a dirty tree.** The review covers `main...HEAD` — committed work only.
   If `git status --porcelain` is non-empty, tell the user exactly which files are
   uncommitted and therefore *not* under review, before spawning anything. Let them
   commit first if they want those included.

3. **Spawn one `pre-pr-reviewer` agent** via the Agent tool
   (`subagent_type: "pre-pr-reviewer"`, `run_in_background: false`). A fresh Agent
   call inherits no context — do not use `SendMessage` to an existing agent, which
   would defeat the purpose.

   **If that agent type does not resolve, stop and say so.** The registry is read at
   session start, so a freshly installed agent is not available until Claude Code
   restarts. Do not quietly fall back to `general-purpose` with the brief pasted in:
   that agent holds no tool restriction, so the reviewer would run with write access
   while the user believes it is read-only. Offer the restart, or ask explicitly
   before running the degraded version.

   The prompt should carry only:

   - the absolute repository path
   - the diff range (`main...HEAD`) and how to read it
   - a pointer to the standing brief, and the read-only constraint

   Do **not** pass a PR number. A reviewer holding one will fetch the pull request,
   and the first thing it finds there is the description — the author's framing,
   arriving by the back door the contamination rule was written to close.

   Keep it short. The agent definition holds the reviewer's standing instructions;
   do not restate them, and do not embellish them with specifics about this change.

4. **Relay the review in the session.** The agent's output is not shown to the user,
   so reproduce it — organised, but not softened. Do not quietly drop findings you
   disagree with; report them and say you disagree, with your reasoning.

5. **Verify before you act.** Subagents are confidently wrong sometimes. Check the
   concrete claims — the `file:line` ones — yourself before treating any as fact,
   and say which you confirmed and which you did not. A finding you could not
   reproduce is worth reporting as exactly that.

6. **Compare the descriptions.** The reviewer writes its own account of what the
   change does. Put it beside your own framing and report where they diverge — a
   difference in described *scope* usually means the diff does more than intended,
   and a reviewer who cannot say *why* the change is wanted has found a real problem
   with its legibility.

   Discount agreement in proportion to how much of your own narrative the diff
   carries. A branch that adds a changelog entry, a README section or an explanatory
   docstring has handed the reviewer your framing inside the very thing it is
   reviewing; matching descriptions then prove nothing. Say so when reporting, rather
   than counting it as confirmation.

7. **Propose what to act on.** Separate merge-blockers from follow-up material,
   recommend which is which, and let the user decide. Offer to fix the blockers;
   offer to add the rest to the board.

## Notes

- **The `allowed-tools` patterns are deliberately narrow**, and each wildcard
  includes a flag rather than stopping at the subcommand. A `:*` rule permits
  *any* continuation after the prefix, flags included, so `Bash(git branch:*)`
  would permit `git branch -D` — `git branch` is pinned to the one exact
  invocation this skill runs. `Bash(git diff --stat:*)` is narrowed on the same
  principle, though measurement against Claude Code 2.1.220 showed the sibling
  it was originally guarding against (`git difftool --extcmd=<anything>`) is
  already refused by plain `Bash(git diff:*)`: `:*` stops at a token boundary.
  The narrower prefix is kept as it costs nothing and does not rely on that.

  The rule of thumb: extend the prefix far enough that no dangerous sibling command
  shares it. Verify with `perms.matches_command` against `perms.MUTATING_INVOCATIONS`
  rather than by eye — `git difftool` is not in that list, so the guard test alone
  will not save you.

  This skill needs to *read* the repository, never to change it. If a future edit
  seems to need `Bash(git *)`, that is a sign the skill has grown a job it should
  not have.

- **The reviewer's `Bash` access is not pattern-restricted**, and cannot be — agent
  definitions list tool *names*, not permission patterns, and the reviewer needs a
  real shell to run the test suite and typechecker. Its read-only constraint is
  therefore enforced by instruction, backed by the normal permission prompts, rather
  than mechanically. Worth knowing when you approve its commands: if it asks to run
  something that writes, that is a bug in the review, not a step you should wave
  through.

- **Session-only by default.** Nothing goes to GitHub — no review, no comment, no
  approval — unless the user explicitly asks for that afterwards. A cold review is
  for the author's benefit first.
- **Cost is real, and scales with the diff.** Two measured runs: a ~950-line source
  change took ~113k subagent tokens and ~14 minutes; a ~280-line docs-and-config
  change took ~63k and ~6. Budget accordingly rather than assuming the high end —
  the mid-sized branches are the cheapest and often the most worthwhile. It is worth
  it before a merge you cannot easily walk back; it is not worth it per commit.
- **A clean review is a result, not a failure.** If the reviewer finds nothing, say
  so plainly rather than manufacturing concerns to justify the run.
