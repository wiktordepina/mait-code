# The companion mod

!!! warning "Optional, Claude Code-only, early access"
    The companion mod is built on Claude Code's **mods API** (function-hook
    plugins), which is in early access and may change between Claude Code
    releases without notice. It is **off by default**, and it only exists inside
    Claude Code: none of mait-code's other surfaces depend on it.

**mait-companion** brings two mait-code conveniences into the Claude Code
prompt itself:

- **`/capture <text>`** files a thought to the [quick-capture inbox](board.md)
  immediately, with no model turn. It's the same as `mc-tool-inbox add`, but
  you don't have to leave the prompt. `/capture` with no text prints its usage.
- **A status bar above the prompt**: rows on your theme's panel colour. The
  top row is the work in hand and what's waiting on you; the second is where
  the session is and what it's using. Below them, a step row appears for each
  bound card with a [playbook run](board.md#playbook-runs), and a last row
  while subagents are running.

```text
 #162  Ship the mait-companion mod     jira  PLAT-4821  PLAT-4830   in review  #158   inbox  3
 ▣ mait-code  ⎇ feat/two-rows ±3 ↑1      ✦ opus 5.5   142k/1M  ━─────── 14%   5h·7d  63·41%
 ≣ ▸ #162  ✓  ↷  ▶  ○  ○  3/5 Implement · 6m
 ⋔ ▸ 3 agents  Explore ×2 · pre-pr-reviewer · 1m12s
```

In the default style each segment is a badge: its label on the surface colour,
joined to its value on the segment's own colour, with a cell of panel between
badges so each label reads with its own value.

The top row:

| Segment | Shows | Hidden when |
| --- | --- | --- |
| Cards (left) | Each card [bound to this session](board.md): `#id` on the primary colour, then the title. The title is cut first when the row is short. | No card is bound to the session |
| `jira` | The Jira keys referenced by the bound cards, after a `jira` label on the primary colour the cards use. Click one to open it in your browser (see [Jira links](#jira-links)). | No bound card has a `JIRA` reference |
| `in review` | The `#id` if one card is In Review for this project, or the count if there are several | Nothing is In Review |
| `inbox` | How many captures are waiting for `/triage` | The inbox is empty |

The second row:

| Segment | Shows | Hidden when |
| --- | --- | --- |
| `▣` project | The folder name of the session's project root | Never, in a session with a project |
| `⎇` branch | The branch checked out, or the short commit on a detached HEAD. After it, `±3` counts uncommitted changes, and `↑1↓2` the commits ahead of and behind the upstream; each is left out at zero | Not in a git repository |
| `✦` model | The model in use, shortened (`opus 5.5`), in coloured text rather than a block | Claude Code doesn't say |
| Context | Tokens used over the window's size (`142k/1M`), then an eight-cell gauge (a heavy line in full ink for the filled part, a faded light line for the rest) and the percentage | Claude Code hasn't measured it yet |
| `5h·7d` | How much of the five-hour and seven-day rate-limit windows you've used, in that order, coloured by the fuller. At 80% or more it counts down to the reset (`↻41m`) | You're not on a subscription, or there's no reading yet |

Context and the windows are green below 50%, amber below 80% and red above
that. Project and branch are always drawn in the quieter slim style, because
they're there to orient you rather than to warn.

Each bound card with an open [playbook run](board.md#playbook-runs) gets a
step row. Collapsed, it shows the card, a rail with one block per step, and
where the run has got to:

- `3/5 Implement · 6m`: the step in progress and how long it has been running.
  A paused step shows its reason instead, or "waiting for you".
- `2/5 done · next Implement`: between steps.
- `all 5 done` or `not started`.

| Glyph | Step |
| --- | --- |
| `○` | pending |
| `▶` | in progress |
| `✓` | done |
| `↷` | skipped |
| `‖` | paused |
| `!` | pending, behind a step that has already started |

A `!` step also raises a chip on the right (`! Comment audit pending`, or
`! 2 steps pending`). It can mean a step was missed or one was reset to be
redone; the bar can't tell which. Click `▸ #162` to open the row: each step on
its own line, in two columns from 100 cells wide, with the time a done step
took, the time so far on the current one, and the reason for a skipped or
paused one. Times include any time a step spent paused. In the `slim` style,
or when the row is too short for blocks, the rail is drawn as coloured glyphs.

The last row is the subagents this session has started and that haven't
reported back yet. Collapsed, it's one line: how many, their types, and how
long the oldest has been running. Click `▸ 3 agents` (or focus the bar with
`ctrl+x tab` and press Enter on it) to open it: each agent's task, the tool
it last called and its running time, grouped under their type when the types
differ. Teammates, which idle and wake rather than report once, are left out.

If every segment in a row is empty, that row disappears, and the whole bar steps
aside while Claude Code shows a survey.

## Jira links

Add a Jira issue to a card as a reference labelled `JIRA`:

```bash
mc-tool-board ref add 162 JIRA PLAT-4821
```

A full `https://` URL works too and is linked as it stands. A bare key is
linked under your Jira site, which you set once:

```bash
mait-code settings set jira-base-url https://acme.atlassian.net
```

Until that is set, bare keys are still shown, but you can't click them.

Each key is a button rather than a terminal hyperlink. Claude Code prints a
hyperlink's whole URL beside its text when it isn't sure the terminal supports
links (under a multiplexer, for example), and a button avoids that. Clicking
one runs `xdg-open` (or `open` on macOS). Without mouse support, press
`ctrl+x tab` to focus the bar and select the key from there.

## Switching it on

Use the home hub: open **System ▸ Companion mod** and press Enter. You'll be
asked to confirm before it turns on. You can also use the settings editor's
**Companion mod** group, or a shell:

```bash
mait-code settings set mods enabled
```

Turning it on adds the mod's folder (`mods/mait-companion` in your mait-code
clone) to `CLAUDE_CODE_PLUGIN_DIRS` in the `env` block of
`~/.claude/settings.json`. Turning it off removes that entry again, and so does
`mait-code uninstall`. Any other plugin folders already listed there are left
alone. Claude Code reads the variable when a session starts, so the change takes
effect in your **next** session. `mait-code doctor` reports whether the setting
and `settings.json` agree.

## Styles and colours

The bar comes in two styles, selected by the `status-bar-style` setting:

- **`blocks`** (the default): badges, each label joined to its value's block.
- **`slim`**: a coloured glyph and value on the panel, with no blocks.

```bash
mait-code settings set status-bar-style slim
```

The bar's colours come from mait-code itself, through
`mait-code settings get theme --palette`, so it follows the same `theme`
setting as the TUIs. Themes that only defer to the terminal's own colours (the
`ansi-*` ones) are shown with mait-dark instead. The mod reads the theme and the
style once, when a session starts.

## How it behaves

The mod is a thin client: it calls the `mc-tool-*` and `mait-code` CLIs and
draws what they return, and holds no data of its own. The only thing it
changes is the inbox, through the inbox CLI, when you `/capture`. The bar
refreshes at these points only:

- when a session starts
- after each of your turns (not after each subagent's)
- as a board command Claude runs mid-turn returns (any `mc-tool-board`
  call, not a subagent's), so a card it claims shows straight away
- after a `/capture`
- whenever Claude Code reports new context or rate-limit figures (those
  segments only; compactions included)
- as a subagent starts, calls a tool or reports back (the agents row only)

Each refresh is one call to `mc-tool-board summary --json --session <id>` and
two or three `git` calls for the branch and its state. Its one timer moves
running times on: every five seconds while subagents are running, every thirty
while only a playbook step is in progress, and not at all otherwise. The timer
calls nothing; it only redraws.

It is built to **fail closed**. If a CLI is missing, its output can't be read,
or a Claude Code API it relies on changes, the affected segments draw nothing and `/capture`
reports that it failed. Your session is never broken. `/capture` registers
separately from the bar, so if Claude Code refuses the command, the bar still
works.
