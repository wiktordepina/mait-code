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
- **A status bar above the prompt**: one row on your theme's panel colour,
  showing the work in hand on the left and what's waiting on you on the right.

```text
 #162  Ship the mait-companion mod         in review  #158   inbox  3   context  142k · 14%
```

| Segment | Shows | Hidden when |
| --- | --- | --- |
| Cards (left) | Each card [bound to this session](board.md): `#id` on the primary colour, then the title. The title is cut first when the row is short. | No card is bound to the session |
| `in review` | The `#id` if one card is In Review for this project, or the count if there are several | Nothing is In Review |
| `inbox` | How many captures are waiting for `/triage` | The inbox is empty |
| `context` | Context window use as `tokens · percent`, green below 50%, amber below 80%, red above that | Claude Code hasn't measured it yet |

If every segment is empty, the whole bar disappears, and it also steps aside
while Claude Code shows a survey.

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
- after a compaction (the context segment only)

Each refresh is a single call to `mc-tool-board summary --json --session <id>`.

It is built to **fail closed**. If a CLI is missing, its output can't be read,
or a Claude Code API it relies on changes, the bar draws nothing and `/capture`
reports that it failed. Your session is never broken. `/capture` registers
separately from the bar, so if Claude Code refuses the command, the bar still
works.
