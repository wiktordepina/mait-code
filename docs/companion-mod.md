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
- **A status bar above the prompt**: two rows on your theme's panel colour.
  The top row is the work in hand and what's waiting on you; the bottom row is
  where the session is and what it's using.

```text
 #162  Ship the mait-companion mod     jira  PLAT-4821  PLAT-4830   in review  #158   inbox  3
 ▣ mait-code  ⎇ feat/two-rows          ✦  opus 5.5 · 1M   ◔  142k · 14%   5h  63%   7d  41%
```

The top row:

| Segment | Shows | Hidden when |
| --- | --- | --- |
| Cards (left) | Each card [bound to this session](board.md): `#id` on the primary colour, then the title. The title is cut first when the row is short. | No card is bound to the session |
| `jira` | The Jira keys referenced by the bound cards. Click one to open it in your browser (see [Jira links](#jira-links)). | No bound card has a `JIRA` reference |
| `in review` | The `#id` if one card is In Review for this project, or the count if there are several | Nothing is In Review |
| `inbox` | How many captures are waiting for `/triage` | The inbox is empty |

The bottom row:

| Segment | Shows | Hidden when |
| --- | --- | --- |
| `▣` project | The folder name of the session's project root | Never, in a session with a project |
| `⎇` branch | The branch checked out, or the short commit on a detached HEAD | Not in a git repository |
| `✦` model | The model in use, shortened (`opus 5.5 · 1M`) | Claude Code doesn't say |
| Context | Context window use as `tokens · percent`. The glyph fills with the window (`○ ◔ ◑ ◕ ●`) | Claude Code hasn't measured it yet |
| `5h`, `7d` | How much of the five-hour and seven-day rate-limit windows you've used | You're not on a subscription, or there's no reading yet |

Context and both windows are green below 50%, amber below 80% and red above
that. Project and branch are always drawn in the quieter slim style, because
they're there to orient you rather than to warn.

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

- **`blocks`** (the default): solid blocks, each with a dim label beside it.
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
changes is the inbox, through the inbox CLI, when you `/capture`. It runs
nothing in the background and has no timers. The bar refreshes at these points
only:

- when a session starts
- after each turn
- after a `/capture`
- whenever Claude Code reports new context or rate-limit figures (those
  segments only; compactions included)

Each refresh is one call to `mc-tool-board summary --json --session <id>` and
one or two `git` calls for the branch.

It is built to **fail closed**. If a CLI is missing, its output can't be read,
or a Claude Code API it relies on changes, the affected segments draw nothing and `/capture`
reports that it failed. Your session is never broken. `/capture` registers
separately from the bar, so if Claude Code refuses the command, the bar still
works.
