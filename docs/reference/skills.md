# Skills Reference

Skills are slash commands available in Claude Code sessions when mait-code is installed.

| Skill | Trigger | Description | Status |
|-------|---------|-------------|--------|
| Recall | `/recall <query>` | Search memory for past facts, decisions, patterns | **Implemented** |
| Remember | `/remember <content>` | Manually store a memory observation | **Implemented** |
| Memory Store | *(auto)* | Claude auto-stores observations about user/projects | **Implemented** |
| Reflect | `/reflect` | Synthesise observations into insights; propose MEMORY.md rewrites, merges & retirements | **Implemented** |
| Commit | `/commit` | Detect changes, generate conventional commit message, confirm and commit | **Implemented** |
| Remind | `/remind <when> <what>` | Set a reminder for a future time (manual only — Claude won't auto-invoke) | **Implemented** |
| Reminders | `/reminders` | Show active and overdue reminders | **Implemented** |
| Board | `/board` | View and drive the project kanban board | **Implemented** |
| Triage | `/triage` | Route quick-capture inbox items to the board or memory | **Implemented** |
| Pre-PR Review | `/pre-pr-review` | Independent review of the current branch, by a reviewer that has not seen the conversation | **Implemented** |
| Outward Comms | `/outward-comms [text]` | House style for text written on your behalf for others; rewrites given text or shapes a draft | **Implemented** |
| Code Comments | `/code-comments [path]` | Conventions for comments and docstrings; audits the branch's comments, or sweeps a path | **Implemented** |
| Work | `/work <card>` | Drive a card through the dev flow, refinement to pull request, recording each step on the card (manual only) | **Implemented** |
| Design Review | `/design-review <card>` | Independent review of a refined board card before it's built, by a reviewer that has not seen the refinement | **Implemented** |

## Implemented Skills

### /recall

Search memory for past facts, decisions, patterns, and preferences.

**Usage:**
```
/recall database preferences     # Search for past database decisions
/recall testing patterns         # Find remembered testing approaches
/recall kubernetes               # Look up stored Kubernetes knowledge
/recall                          # Show recent memories (no query)
```

**How it works:**

1. Preprocesses search results via `mc-tool-memory search` (injected before Claude sees the skill)
2. Results are ranked by composite score (recency + importance + relevance)
3. Also preprocesses the five most recent memories via `mc-tool-memory list`, which stand in for results when no query is given
4. For follow-up searches, uses Bash to call `mc-tool-memory search` directly

### /remember

Manually store a memory observation. This is a manual-only skill (`disable-model-invocation: true`) — Claude won't auto-invoke it.

**Usage:**
```
/remember always use tabs for Go code
/remember deployed v2.3 to production today
/remember the auth service uses JWT with RS256
```

**How it works:**

1. Determines the best entry type and importance for the content
2. Stores via `mc-tool-memory store`

### memory-store (auto-invoked)

Not a slash command (`user-invocable: false`) — Claude uses this skill proactively when it learns something new about the user. Uses `mc-tool-memory store` via Bash, and `mc-tool-memory supersede` when the new fact replaces one already stored rather than adding to it.

### /reflect

Synthesise recent observations into high-level insights, and **consolidate**
MEMORY.md rather than only appending to it.

**Usage:**
```
/reflect                                    # Reflect on unreflected entries
```

**How it works:**

1. Runs `mc-tool-memory reflect --json` via Bash, returning `{skipped, reason, insights, ops, stored}`
2. Checks the novelty gate — skips if fewer than 3 unreflected entries exist
3. Gathers unreflected memory entries (tracked by per-project watermark)
4. Calls Claude Haiku to identify patterns, themes, and recurring issues
5. Stores insights as `type=insight` (importance=6) in memory.db
6. Advances the watermark — running `/reflect` again without new entries is a no-op
7. Renders any proposed `ops` as a before/after diff and asks for approval **per operation**
8. For large backlogs: `mc-tool-memory reflect --drain --batch-size 20`

**The four operations.** Reflection doesn't just add lines — it proposes **add**,
**rewrite**, **merge** and **retire**. Each approved op is applied in *two*
places: MEMORY.md via Edit, and the memory database via the matching verb
(`retire`, `merge --into`, or `supersede`) when the op carries backing
`entry_ids`. Without the second half, the raw store would keep resurfacing what
was just consolidated in the curated layer.

**Routing.** The skill keeps mait-code's MEMORY.md and Claude Code's native
per-project auto memory cleanly separated: cross-project **user** facts
(preferences, conventions, working style) belong to mait-code; per-project
**code** facts (architecture, build commands, repo gotchas) belong to the native
layer. A proposed add about the project is written to the native layer instead,
so the two don't drift and double-spend context.

### /remind

Set a reminder for a future time.

**Usage:**
```
/remind in 2 hours check deploy status
/remind tomorrow 9am standup prep
/remind friday review PR #42
```

**How it works:**

1. Parses the time and content from the arguments
2. Stores via `mc-tool-reminders set "<when>" <what>`
3. Uses `dateparser` for flexible natural language time parsing with UTC normalization

### /reminders

Show active and overdue reminders.

**Usage:**
```
/reminders                    # Show active reminders
```

**How it works:**

1. Preprocesses results via `mc-tool-reminders list` (injected before Claude sees the skill)
2. Presents active and overdue reminders
3. `mc-tool-reminders list --all` includes already-dismissed reminders
3. Supports dismissing reminders via `mc-tool-reminders dismiss <id>`

### /board

View and drive the manually-driven kanban board for the current project. Claude acts as the worker — there is no autonomous dispatcher.

**Usage:**
```
/board                                  # Show the board, then act on requests
```

**How it works:**

1. Preprocesses the current project's board via `mc-tool-board list` (injected before Claude sees the skill)
2. Teaches Claude the verb vocabulary so conversational requests map to `mc-tool-board` calls:
   - "pick up the next refined card" → `mc-tool-board next --claim` (top refined card → `in_progress`)
   - "refine card N" → draft description + acceptance criteria, confirm, then `mc-tool-board refine N ...`. The description ends with a **Testing strategy** section, chosen from the user's `testing_strategies.md` (read with `mait-code identity show testing_strategies`)
   - "what's next?" → `mc-tool-board next` (only *ready* cards: refined, not blocked, not waiting on another card); `next --epic N` for one initiative
   - "move it to review" → `mc-tool-board review N --pr <url>`, recording the PR on the card
   - complete / block / unblock / tag / untag / archive / move / add / edit / comment / ref via the matching subcommands
3. Cards flow through fixed columns: backlog → refined → in_progress → in_review → done, plus a hidden `archived` side-state; `blocked` is a tag carried in place, not a column
4. Knows the board's structure beyond columns:
   - **Epics** group cards across projects (`add --epic`, `--parent E`, `epic list` / `show` / `promote`)
   - **`blocks` links** order work between cards (`link A blocks B`, `unlink`); `list --ready` shows what can move
   - **Origins**: a card split off or raised from another is added with `--from N`, inheriting its epic and recording where it came from
   - **Session binding**: In Progress cards record which sessions work them (`bind`, `unbind`, `list --mine`)
5. Never moves, completes, or archives cards without the user's confirmation, and never adds a `blocks` link without being told how the work orders

### /triage

Drain the quick-capture inbox by routing each captured item to where it belongs. Suggestion-based — Claude proposes a destination per item; the user decides.

**Usage:**
```
/triage                                 # Walk the inbox, route each item out
```

**How it works:**

1. Preprocesses the current inbox via `mc-tool-inbox list` (injected before Claude sees the skill)
2. For each item, proposes the best destination and, on confirmation, creates it there:
   - Board card → `mc-tool-board add ...`
   - Memory → `/remember`
3. After an item lands in its destination, drains it with `mc-tool-inbox remove <id>` so the inbox stays near-empty
4. Never routes or removes an item without the user's confirmation

### /commit

Detect changes, generate a conventional commit message, confirm with user, and commit.

**Usage:**
```
/commit                          # Analyse changes and propose a commit
```

**How it works:**

1. Preprocesses `git diff --cached --stat`, `git diff --stat`, and untracked files
2. Analyses the changes and generates a conventional commit message (`type(scope): description`)
3. Presents the proposed message for user confirmation or editing
4. On approval, stages files if needed and runs `git commit`

### /pre-pr-review

Review the current branch with a reviewer that has seen none of the session's
conversation.

**Usage:**
```
/pre-pr-review                   # Review origin/HEAD...HEAD before opening a PR
```

**Why it exists:**

You cannot review your own work in the session that produced it. Knowing why every
decision was made, you check whether the code matches the intent — not whether the
intent was right. A reviewer with no context checks the second thing.

**How it works:**

1. Preprocesses the branch name, the base ref, commits vs that base, diff stat, and
   uncommitted files. The base comes from `origin/HEAD` — the branch the remote calls
   default — so a trunk named `master` or `develop` works untouched, and a local trunk
   lagging behind the remote cannot drag old commits into the review
2. Warns which files are dirty and therefore *not* under review, then spawns one
   `pre-pr-reviewer` agent (see [Agents](#agents)) with a deliberately bare prompt —
   repository path, diff range, and the brief, and nothing about why the change was
   made

!!! warning "Isolation is real but not total"

    The reviewer has not seen the session's conversation, and that is the property
    worth having. It *does* inherit the system prompt: the project `CLAUDE.md`, your
    identity documents, and `MEMORY.md` — which carries past decisions and feedback,
    and therefore some of your framing. Discount its agreement on anything those
    already settle, and do not read a clean review as proof that an unbriefed
    stranger would agree.
3. Relays the review in the session, verifies its concrete `file:line` claims, and
   separates merge-blockers from follow-up material

The reviewer also writes its own description of the change from the diff alone.
Comparing that against the author's framing is diagnostic: a difference in described
*scope* usually means the diff does more than intended, and a reviewer who cannot say
*why* the change is wanted has found a real problem with its legibility.

**Cost:** scales with the diff. Two measured runs: a substantial code change took
~113k subagent tokens and ~14 minutes; a ~280-line docs-and-config change took ~63k
and ~6. Budget accordingly rather than assuming the high end. Worth it before a
merge that is hard to walk back; not worth it per commit.

**Nothing is posted to GitHub** — no review, no comment, no approval — unless you
ask for that separately afterwards.

### /outward-comms

The house style for text other people read, written as you: PR and review
comments, PR descriptions, commit messages, issue comments, chat, email and
committed docs.

**Usage:**
```
/outward-comms                   # Apply the style to the draft in hand
/outward-comms <text>            # Rewrite the given text to the style
```

**How it works:**

1. Reads its rules from `writing_style.md` in the data directory (see
   [setup](../setup.md)), which you own: no em dashes, plain characters in
   prose with glyphs only where they carry structure, no AI clichés, concise
   and direct, and your spelling convention
2. Rewrites the given text, or shapes the draft being written, then runs a
   pre-send pass: dashes, non-ASCII characters, clichés, whether the answer
   comes first
3. Shows you the exact text and waits for your go-ahead before anything is
   sent. That rule lives in the skill, not the editable file, because it is
   about safety rather than style

It applies to new text and doesn't rewrite existing docs unprompted. It loads
the file with `mait-code identity show writing_style`, so a custom `data-dir`
is followed. A `cat` of the file wouldn't do: Claude Code doesn't run skill
preprocessing that reads under `~/.claude/` inline.

### /code-comments

Conventions for comments and docstrings inside source files: functional, not
narrative; no ticket keys or history; no facts that drift (line numbers,
counts, "currently"); comment the counter-intuitive, never the obvious; ASCII
only.

**Usage:**
```
/code-comments                   # Audit the comments this branch adds or changes
/code-comments src/foo/          # Sweep every comment under a path
```

**How it works:**

1. *Write mode* applies the rules while a comment or docstring is written or
   edited. It relies on the skill being triggered, which is best effort;
   invoking it is the guaranteed path, and a playbook can run audit mode too
2. *Audit mode* with no argument reads the branch's diff against its base and
   checks only the comments it adds or changes, plus comments whose meaning the
   change affects. Old violations elsewhere in a touched file are mentioned once,
   not reported. With a path, it sweeps every comment there
3. It matches the project's docstring convention first (config, house rules,
   then the dominant recent pattern), with per-language guidance in
   `reference/languages.md`
4. Findings are reported by file and identifier, not line number, with a
   proposed rewrite or a deletion

The ASCII rule wins over matching the project: a file full of em dashes still
gets ASCII in every comment written or touched. A comment that must name a
non-ASCII character uses its escape or Unicode name (`U+2014 EM DASH`).

It has no `allowed-tools`. It searches with Claude Code's Grep tool where the
session has one, and otherwise with `grep` or `rg` through the shell, prompted
or sandboxed. A `Bash(rg:*)` grant would also allow `rg --pre <cmd>`.

### /work

Drive one board card from wherever it is to a raised pull request, in the
conversation, one step at a time. Manual only: Claude never starts it on its
own.

**Usage:**
```
/work 42                         # Take card #42 through the flow, or resume it
```

**The steps**, written to the card as a [playbook run](../board.md#playbook-runs)
so the board, the TUI and the companion mod's step row show where it is:

| # | Step | Does |
|---|---|---|
| 1 | `refine` | Refine the card (Backlog), or only add a missing Testing strategy section (otherwise) |
| 2 | `design-review` | `/design-review` |
| 3 | `implement` | Move the card to In Progress if needed; build it on a topic branch |
| 4 | `comment-audit` | `/code-comments` over the branch's changed comments |
| 5 | `commit-review` | Re-run the repo's lint, format, typecheck and tests; `/commit` without pushing, then `/pre-pr-review` |
| 6 | `address-findings` | Fix the findings; offers a second review if the fixes add files, change an interface, change a rule, convention or guard policy, or grow the diff by more than ~30% |
| 7 | `tests` | Run exactly the strategies in the card's Testing strategy section |
| 8 | `raise-pr` | Summarise the run, ask, then push and raise the PR |

**How it behaves:**

- **Recorded before reported.** A step is marked `done` or `skipped` on the
  card before Claude says it is finished. The board refuses to start a step
  while another is in progress, and that refusal is treated as an unrecorded
  step to set right, not something to force past.
- **Skippable steps.** Any step can be skipped with a reason, which the board
  records in the run and as a card comment. Step 8's question is never skipped.
- **Checkpoints.** It stops and asks at once when the work contradicts the
  card; small assumptions are batched and reported when the step ends. A step
  waiting on you is marked `paused`, with the question as its reason.
- **Raising the PR.** One yes covers the push and the PR. The PR is raised
  with the skill named by the `pr-skill` setting, or `gh pr create` when it's
  empty or the skill can't be invoked, and its text follows `/outward-comms`.
  Then the run is ended and the card moves to In Review, in that order.
- **Resuming.** The run lives on the card, so `/work N` after a `/clear`, a
  restart or another day picks up at the current step. A step left in progress
  by a session that ended is offered a restart, and an open run from another
  playbook is never touched without asking. What the last pre-PR review covered
  is recorded as a card comment after each review, so it survives too.

**No hooks.** `git push` and `gh pr create` are outside its grant, so the
permission prompt backs up step 8's question. `mc-tool-board move` and
`run start` are left out too: one could archive or complete a card, the other
replace a run.

### /design-review

Review a refined [board card](../board.md) with a reviewer that has seen none of
the conversation that refined it, before anyone builds it.

**Usage:**
```
/design-review 42                # Review card #42
```

**Why it exists:**

Whoever refined a card reads it for whether it says what they meant, not for
whether what they meant is right. A cold reviewer finds the states the card
doesn't cover, the criteria nobody can check, and the code that doesn't work the
way the card assumes, while they are still cheap to fix.

**How it works:**

1. Reads the card with `mc-tool-board show N --json`. It stops on an unknown
   id, refuses an epic or a Done or archived card, and warns on a Backlog card,
   one with no acceptance criteria, or one already In Review. It also stops and
   asks if the card belongs to another project than the current repository's
2. Spawns one `design-reviewer` agent (see [Agents](#agents)) with only the
   repository path, the card id, the read-only constraint and a pointer to its
   brief. It finds the relevant code itself
3. Relays the review, verifies its `file:line` claims, and proposes a
   resolution for each finding, plus any follow-up cards (`--from N`) and cards
   for unrelated issues (`--from N --parent none`)
4. Writes nothing until you approve. Then it edits the card, adds a comment
   saying what the review changed, and adds the cards you accepted. It asks
   before linking `blocks`, and `mc-tool-board link` is outside its grant

!!! warning "The card carries framing too"

    The reviewer has to read the card, and the card is the refiner's own words.
    Its comments may summarise an earlier review, and its references may point at
    research. The reviewer reads the description and the code first, then
    comments and references, treats an earlier review as framing rather than
    findings, and follows no external links. It is also told not to read the
    mait-code data directory or Claude Code's transcripts, which record past
    sessions' discussion. Discount its agreement on anything the card already
    settles.

**Cost:** one measured run on a large refined card took ~56k subagent tokens
and ~2.5 minutes.

It doesn't move the card or touch its playbook run; a playbook that calls it
records its own step.

## Agents

Agent definitions live in `agents/` as individual markdown files with YAML
frontmatter, symlinked into `~/.claude/agents/` at install time. They hold a
subagent's standing instructions, so a skill that spawns one passes only the task —
never the persona.

### pre-pr-reviewer

The reviewer behind `/pre-pr-review`. Reads a diff cold and reports defects, design
objections, and — importantly — the classes of problem it looked for and did *not*
find, so silence can be told from diligence.

Its brief includes explicit licence to reject the premise: if the change solves the
wrong problem, saying so is more useful than a tidy review of a bad idea. It is told
to distrust green CI, on the grounds that the tests were written by whoever wrote the
bug.

**Read-only, with two caveats.** The definition forbids mutating git commands, any
`gh` write, and changing or deleting any file the reviewer did not itself create.
But agent frontmatter lists tool *names*, not permission patterns, and the reviewer
needs a real shell to run tests and typecheckers — so the constraint is enforced by
instruction plus the usual permission prompts, not mechanically.

The second caveat is that read-only is not write-*never*. A reviewer running a repro
script has to put it somewhere, and its scratchpad is shared with the session that
spawned it — so an unqualified "don't write" leaves it either hobbled or quietly
overwriting the author's scratch files. The brief instead sends it to a `mktemp -d`
directory of its own, off-limits to everything else, and bars writing into the
repository at all so nothing it does can surface in `git status`. A write inside its
own directory is expected; a write anywhere else is a bug in the review.

### design-reviewer

The reviewer behind `/design-review`. Reads a refined card and the code it will
change, and reports what it understands the card to ask for, findings ranked
High, Medium and Low with a suggested resolution each, any objection to the
direction, proposed cards, and what it checked and found fine.

It is read-only on the same terms as `pre-pr-reviewer`, scratch directory
included, and also **writes nothing to the board**: what reaches the board is
the user's call, made after reading the review.

## Skill Architecture

Each skill is a directory in `skills/` containing:

```
skills/
├── recall/
│   └── SKILL.md     # Search memory
├── remember/
│   └── SKILL.md     # Store memory (manual)
├── memory-store/
│   └── SKILL.md     # Store memory (auto-invoked by Claude)
├── reflect/
│   └── SKILL.md     # Synthesise observations into insights
├── remind/
│   └── SKILL.md     # Set a reminder
├── reminders/
│   └── SKILL.md     # Show reminders
├── board/
│   └── SKILL.md     # View and drive the kanban board
├── triage/
│   └── SKILL.md     # Route the quick-capture inbox to the board or memory
├── commit/
│   └── SKILL.md     # Smart commit with conventional message
├── pre-pr-review/
│   └── SKILL.md     # Cold second opinion on a branch before opening a PR
├── outward-comms/
│   └── SKILL.md     # House style for text written for other people
├── code-comments/
│   ├── SKILL.md     # Conventions for comments and docstrings
│   └── reference/
│       └── languages.md  # Per-language docstring shapes
├── design-review/
│   └── SKILL.md     # Cold second opinion on a refined card before building it
└── work/
    └── SKILL.md     # Drive a card from refinement to a pull request
```

Skills are symlinked into `~/.claude/skills/` by `mait-code install` (and refreshed by `mait-code update`, which also prunes links to removed skills) and loaded by Claude Code automatically.

### Skill Definition Format

```yaml
---
name: skill-name
description: What the skill does, and when it should be used
argument-hint: "<args>"
allowed-tools: Bash(mc-tool-example show), Bash(mc-tool-example show:*), Read
---

# /skill-name

Instructions for Claude when this skill is invoked.
```

Key fields:

- `name` / `description` — The description is what Claude matches on when deciding
  whether a skill applies, so it should say *when* to use the skill, not only what
  it does
- `user-invocable: false` — Hides it from the slash-command list (what `memory-store`
  uses; skills are user-invocable by default, so no shipped skill sets this true)
- `disable-model-invocation: true` — Prevents Claude from auto-invoking (for side-effect skills like `/remind` and `/remember`)
- `allowed-tools` — Tools the skill is allowed to use, scoped past the bare
  executable (e.g. `Bash(mc-tool-memory search:*)`). `Bash(mc-tool-memory *)`
  is a real wildcard granting every subcommand including `delete`; see
  [Granting `allowed-tools`](../development.md#granting-allowed-tools) for the
  measured matcher semantics
- `argument-hint` — Shown in autocomplete to guide usage
