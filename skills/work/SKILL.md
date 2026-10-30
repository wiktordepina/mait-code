---
name: work
description: Drive one board card through the dev flow - refine, design review, implement, comment audit, commit and pre-PR review, address findings, run the agreed tests, raise a PR - recording each step on the card. Only when the user runs /work N.
argument-hint: "<card id>"
disable-model-invocation: true
allowed-tools: Bash(mc-tool-board show:*), Bash(mc-tool-board summary --json), Bash(mc-tool-board bind:*), Bash(mc-tool-board run step:*), Bash(mc-tool-board run end:*), Bash(mc-tool-board run show:*), Bash(mc-tool-board edit:*), Bash(mc-tool-board refine:*), Bash(mc-tool-board comment:*), Bash(mc-tool-board review:*), Bash(mait-code identity show testing_strategies:*), Bash(mait-code settings get pr-skill --json), Bash(git rev-parse --abbrev-ref origin/HEAD)
---

# /work

Take card N from wherever it is to a raised pull request, in this
conversation, one step at a time. Each step calls the skill that already does
that job rather than repeating it, and its progress is recorded on the card as
a playbook run, so `mc-tool-board show N`, the board TUI and the companion
mod's step row all show where the work has got to.

Not for research, brainstorms or reviewing someone else's PR: those don't end
in a branch of yours.

## The steps

The run is always written with these eight names, in this order:

| # | Step | Does |
|---|---|---|
| 1 | `refine` | Refine the card, with a testing strategy |
| 2 | `design-review` | `/design-review N` |
| 3 | `implement` | Build it on a branch |
| 4 | `comment-audit` | `/code-comments` over the branch |
| 5 | `commit-review` | Repo checks, `/commit` (no push), then `/pre-pr-review` |
| 6 | `address-findings` | Fix what the review found |
| 7 | `tests` | Run the card's agreed tests |
| 8 | `raise-pr` | Summarise, ask, push, raise the PR |

Record progress as you go, with the step's name:

```bash
mc-tool-board run step N <step> in_progress              # starting it
mc-tool-board run step N <step> done                     # finished
mc-tool-board run step N <step> paused --reason "<the question>"
mc-tool-board run step N <step> skipped --reason "<why>"
```

Record a step `done` or `skipped` before telling the user it is finished: the
run, not the conversation, is what a later session resumes from.

Only one step is in progress at a time, so the board refuses to start a step
while another is still in progress, and the refusal names that step. It means
the earlier step was never recorded, not that the board is wrong: if it is
finished, mark it `done`; if it was dropped, `skipped` with the reason. If it
isn't finished, it is still the current step: go back to it, or ask, before
starting the new one. Don't use `pending`, or `paused` without a real
question, to get past the refusal, even though its message offers "reset".

## Skipping

Any step can be skipped, by the user or on your suggestion (a docs-only change
needs no design review), always with a reason the user can read later:
`mc-tool-board run step N <step> skipped --reason "docs-only change"`. The
board records the reason in the run and adds the card comment itself, so don't
post a comment of your own. Never skip silently, and never skip step 8's
question.

## Checkpoints

The same rules hold in every step:

- **Contradicting the refinement:** if the work turns out to need something
  the card's description or acceptance criteria rule out, or a criterion turns
  out to be wrong, stop and ask straight away. Set the step `paused` with the
  question as its reason while you wait, and back to `in_progress` once
  answered.
- **Small assumptions:** choices the card doesn't settle and the user
  probably won't mind (a name, a file location, a message wording) don't stop
  the step. Make them, keep a list, and report them together when the step
  ends, so the user can overturn any.
- **Waiting on the user** for anything else (an approval, a restart, a manual
  check only they can do): `paused`, with what you're waiting for as the
  reason.

## Starting

1. `mc-tool-board show N --json`. Refuse an epic (`kind: "epic"`) and a card
   that is Done or archived. Check the card's `project` matches the `project`
   that `mc-tool-board summary --json` reports for this directory; if not,
   ask.
2. `mc-tool-board bind N`, whatever the card's column, so the card shows as
   this session's work.
3. Look at the card's `run`:
   - **None:** start one (`run start` isn't granted, so it prompts once; a
     grant would also let `--replace` through unasked):

     ```bash
     mc-tool-board run start N --playbook work --steps refine design-review implement comment-audit commit-review address-findings tests raise-pr
     ```

   - **An open `work` run:** ask whether to resume it or start again
     (`run start ... --replace`, which ends the old run; it stays in history).
     To resume, see *Resuming*.
   - **An open run from another playbook:** say whose it is and ask before
     touching it. Never replace it unasked.

## Step 1: `refine`

Depends on the card's column:

- **Backlog:** refine it the way the board skill does: draft a description
  and acceptance criteria, show them, and on approval
  `mc-tool-board refine N --description ... --acceptance ...`.
- **Refined, In Progress or In Review:** the card is already refined. If its
  description has the Testing strategy section (below), skip the step with the
  reason "already refined". If not, add only that section, with approval, using
  `mc-tool-board edit N --description ...`, then mark the step done.

**The Testing strategy section is required before step 1 ends.** It is a
paragraph in the description reading exactly `**Testing strategy**`, followed
by one bullet per chosen strategy: what it will check for this card, and why.
Choose from the user's strategies, `mait-code identity show
testing_strategies`: the entries whose `Projects:` line names this project,
plus those with none. If the command fails, offer `unit` and `manual` and tell
the user to run `mait-code update`. Ask the user to confirm the choice.

## Step 2: `design-review`

Invoke `/design-review N` and follow it: relay the review, verify its claims,
and fold in what the user approves. The design-review skill doesn't touch the
run; this step does. If the card changed materially, re-read it before step 3.

## Step 3: `implement`

- If the card is in Backlog or Refined, move it to In Progress:
  `mc-tool-board move N in_progress` (this keeps the session bound).
- Work on a topic branch, never on the default branch. Create one if needed
  (`feat/...`, `fix/...`, following the repository's habit).
- Build against the acceptance criteria and follow the repository's own
  conventions (`CLAUDE.md`, `CONTRIBUTING.md`). Run its checks (the lint,
  format, typecheck and test commands those files name) as you go.
- At the end of the step, report the batched assumptions.

## Step 4: `comment-audit`

Invoke `/code-comments` with no argument, so it audits only the comments this
branch adds or changes. Fix what it finds that the user agrees with.

## Step 5: `commit-review`

- First run the repository's checks again, the same ones as step 3: step 4
  edits code after them. Fix whatever fails before committing, so the review
  isn't spent on what a linter would catch.
- Invoke `/commit` to commit the work. **Do not push.**
- Then invoke `/pre-pr-review`, which reviews the committed range cold.
  Relay its findings as that skill says, then record what it covered, so a
  later session can tell reviewed commits from new ones:
  `mc-tool-board comment N --author claude "Pre-PR review covered <base>...<short sha of HEAD>"`.
- Before marking the step done, note the base and the size of the reviewed
  diff (`git diff --stat <base>...HEAD`, its last line): step 6 measures
  against it.

## Step 6: `address-findings`

Fix the findings the user wants fixed, and commit them (`/commit`, no push).
Skip the step, with a reason, if there was nothing to fix.

Then offer a second `/pre-pr-review` when any of these hold (and record its
coverage with a comment, as in step 5):

- the fixes add files or modules;
- the fixes change an interface (a judgement call: say that it is one);
- the fixes change a skill's rules, a shipped convention or a guard's policy,
  such as an allowlist or what it refuses, however small the diff (also a
  judgement call: say that it is one);
- the diff grew by more than about 30%: compare the `git diff --stat` line
  total against the base now with the total at the first review.

## Step 7: `tests`

Run exactly the strategies in the card's **Testing strategy** section. Don't
choose again: the card decided. Read each strategy's steps from the user's
`testing_strategies.md` where the card names one from there. Report each
result. A failure sends you back to fix it (a new commit), and the step stays
in progress until the strategies pass or the user accepts a failure, which you
then report in step 8.

A strategy only the user can carry out (a manual check on their machine, a
deploy they own) pauses the step with what they need to do as the reason.

## Step 8: `raise-pr`

1. **Summarise the run:** the steps done; the steps skipped, with their
   reasons; whether the last pre-PR review covered the current `HEAD` (the
   latest "Pre-PR review covered" comment names its sha; list any commits
   after it as unreviewed); and the test results.
2. **Ask** whether to push and raise the PR. One yes covers both. This
   question is never skipped.
3. On a yes, in this order:
   1. Decide who raises it: `mait-code settings get pr-skill --json`. If
      `value` names a skill that exists and can be invoked, it raises the PR.
      If the value is empty, the skill can't be found or invoked, or the
      command fails (no settings file, an older mait-code), use
      `gh pr create`, and say which you used.
   2. Draft the PR title and body with `/outward-comms`, unless the PR skill
      writes its own.
   3. Push the branch (`git push -u origin <branch>`), unless the PR skill
      pushes itself. It isn't granted, so it goes through the permission
      prompt.
   4. Raise the PR with the PR skill, or `gh pr create` with the drafted
      title and body.
4. Then, in this order:

   ```bash
   mc-tool-board run step N raise-pr done
   mc-tool-board run end N
   mc-tool-board review N --pr <url>
   ```

   `review` moves the card to In Review and releases the session's binding,
   which takes the step row with it, so the run is ended first while the row
   can still show it finishing.

On a no, set the step `paused` with the user's reason and stop there.

## Resuming

Resume at the run's current step: the one in progress, else the lowest paused
one. If there is neither, start the first step that is still pending.

- **A step in progress when /work starts** was probably left by a session
  that has ended, but a parallel session may still be on it: check the card's
  `sessions` in `show --json` for another live binding. If there is one, say
  so and ask before touching the run; if not, say what the step was and offer
  to restart it from the top.
- **A paused step:** show its reason (the open question) and pick up from the
  answer.
- **What lived only in the conversation is rebuilt from git and the run:**
  - *What the last pre-PR review covered:* the sha in the card's latest
    "Pre-PR review covered" comment; commits after it are unreviewed
    (`git log --oneline <sha>..HEAD`).
  - *Step 6's baseline:* the diff size at that sha
    (`git diff --stat <base>...<sha>`).
  - *Batched assumptions* from an earlier session are gone: say so rather than
    guessing at them.

## Notes

- **No hooks.** Step 8's question is the gate. `git push` and `gh pr create`
  are deliberately outside this skill's grant, so the permission prompt is a
  second one.
- **Grants.** The board commands are the ones the run needs, narrowed where a
  prefix would let more through: `run start` is left out because a grant would
  also allow `--replace`, and `move` because it can archive or complete a
  card. Neither is granted here; another skill used earlier in the session may
  grant it. Read-only git (`log`, `diff`) isn't granted either: `--output`
  makes both write a file, and they run fine prompted or sandboxed.
- **The run outlives the session.** It sits on the card, so `/clear`, a
  restart or another day picks up where it stopped, via *Resuming*.
