---
name: pre-pr-review
description: Run an independent, zero-context review of the current branch before opening a pull request. Use when you ask for a pre-PR review, a cold second opinion on a branch, or want changes scrutinised before pushing or requesting a merge.
allowed-tools: Bash(git log:*), Bash(git diff:*), Bash(git status:*), Bash(git branch --show-current)
---

# /pre-pr-review

Review the current branch with a reviewer that shares **none** of this session's context.

## Current state

Branch:

!`git branch --show-current`

Commits vs main (empty means nothing to review):

!`git log --oneline -30 main..HEAD 2>/dev/null`

Diff stat:

!`git diff --stat main...HEAD 2>/dev/null`

Uncommitted changes (these are *not* reviewed):

!`git status --porcelain 2>/dev/null`

## Why this exists

You cannot review your own work in the session that produced it. You know why every
decision was made, so you check whether the code matches the intent rather than
whether the intent was right. A reviewer with no context checks the second thing —
and that is where the findings that matter come from.

Everything below exists to protect that one property.

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

1. **Check the range is worth reviewing.** Read the state above. If there are no
   commits ahead of `main`, say so and stop. If the diff is trivial (a handful of
   lines, a docs typo, a version bump), say plainly that a full review costs roughly
   100k tokens and ten-plus minutes, and ask whether they want it anyway rather than
   spending that by default.

2. **Warn on a dirty tree.** The review covers `main...HEAD` — committed work only.
   If `git status --porcelain` is non-empty, tell the user exactly which files are
   uncommitted and therefore *not* under review, before spawning anything. Let them
   commit first if they want those included.

3. **Spawn one `pre-pr-reviewer` agent** via the Agent tool
   (`subagent_type: "pre-pr-reviewer"`, `run_in_background: false`). A fresh Agent
   call inherits no context — do not use `SendMessage` to an existing agent, which
   would defeat the purpose. The prompt should carry only:

   - the absolute repository path
   - the diff range (`main...HEAD`) and how to read it
   - the PR number, if one is already open
   - the review brief and the read-only constraint

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

7. **Propose what to act on.** Separate merge-blockers from follow-up material,
   recommend which is which, and let the user decide. Offer to fix the blockers;
   offer to add the rest to the board.

## Notes

- **The `allowed-tools` patterns are deliberately narrow.** `log`, `diff` and
  `status` take a `:*` wildcard because none of them has a mutating flag — the same
  reasoning that put them in the tool-approval catalogue. `git branch` does **not**
  get a wildcard: `Bash(git branch:*)` would also permit `git branch -D`, which
  deletes branches. It is pinned to the single exact invocation this skill runs.
  Prefix rules cannot express "this subcommand but not that flag", so anything with
  a destructive flag has to be spelled out in full or left out.

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
- **Cost is real.** Roughly 100k+ subagent tokens and ten to fifteen minutes for a
  substantial branch. That is worth it before a merge you cannot easily walk back;
  it is not worth it on every commit.
- **A clean review is a result, not a failure.** If the reviewer finds nothing, say
  so plainly rather than manufacturing concerns to justify the run.
