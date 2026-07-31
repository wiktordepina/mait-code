# The settings editor

Everything mait-code reads — where your data lives, which theme the TUIs wear,
which embedding provider powers memory search, how retrieval is scored — is a
*setting*. `mait-code settings` is the full-screen editor for all of it: a
master–detail app that shows every knob, what it's currently set to and *where
that value came from*, and lets you change it with the right control for its
type, validated before it's written.

![The settings editor: the categorised list on the left, the inline editor for
the highlighted setting on the right, with its help line, current source and an
Apply button.](assets/settings/settings.png)

## Why it exists

Configuration that lives only in environment variables and a hand-edited file is
easy to get wrong and hard to reason about: you can never quite tell whether a
value is the default, something you set last month, or a shell export shadowing
both. The editor makes the whole picture legible. Every row carries its resolved
value and its **source** — `default`, `settings` (the file), `env`, or `derived`
— so "why is it *this*?" is answered on screen. And because each setting knows
its own type, choices and validator, the editor can offer a radio set where the
value is an enum, reject a bad number before it's saved, and refuse to leave the
scoring weights in a state that doesn't add up.

It is the same configuration the `mait-code settings` CLI subcommands read and
write — the editor is just the interactive face of it. Nothing here is hidden
from `settings list`/`get`/`set`, and vice versa.

## The layout

Three regions, top to bottom:

- **The masthead** — the shared brand banner, labelled *Settings* (see [the home
  hub guide](home.md) for how the banner works).
- **The body** — the **settings list** on the left, grouped into categories; the
  **editor** on the right, which adapts to whatever setting is highlighted.
- **The footer** — the live key hints.

Each row in the list reads `<key>  <value>`. Values at their built-in default are
dimmed, so what you've actually changed stands out. A `⚠` marks a
**migration-sensitive** setting — one whose change triggers a re-embed (more on
that below).

The categories:

| Category | What's in it |
|----------|--------------|
| **General** | `data-dir` (where everything lives) and `theme`. |
| **Bridge** | Whether the [Bridge](bridge.md) is `enabled`, and which channel it uses. (The channel's server/topics/token live in the Bridge screen, not here.) |
| **Logging** | Log level, log file, and how many rotated backups to keep. |
| **Embeddings** | The provider (`local` or `bedrock`), the model, and the Bedrock model id / region. |
| **Models** | The extraction and reflection models, LLM and git timeouts, and reflection batch/novelty tuning. |
| **Scoring & dedup** | The retrieval scoring weights and decay half-lives, the dedup similarity thresholds and scope boosts, and the [review-resurfacing](memory.md#review-keeping-curated-memory-fresh) threshold and importance floor. |
| **Paths (derived)** | Read-only paths computed from `data-dir` — the database files, the model cache, the observations directory. |
| **Custom env** | Arbitrary environment variables injected at startup — [covered below](#custom-environment-variables-the-env-table). |
| **Tool approvals** | Curated Claude Code permission rules you can opt into, so the safe commands stop prompting — [covered below](#tool-approvals-safe-permission-presets). |

General, Logging, Embeddings and Custom env open on boot; the more advanced
groups start collapsed to keep the initial list short.

## Editing a setting

Move the highlight with the arrow keys; the editor on the right re-renders for
whatever you land on. The control matches the setting's type:

![The adaptive editor on an enum setting: highlighting `theme` renders a radio
set of every installed theme, the current one marked.](assets/settings/settings-editor.png)

- **Enums** (`theme`, `embedding-provider`, `log-level`, …) become a **radio
  set** of the allowed choices, the current one selected — no way to type an
  invalid value.
- **Free text and numbers** (`data-dir`, `log-file`, timeouts, thresholds …)
  become an **input with live validation**: a bad value shows its error as you
  type, and *Apply* won't write it.
- **Derived values** (everything under *Paths*) are **read-only** — they're
  computed from `data-dir`, so the editor shows the value and says so rather than
  pretending you can change it.

Press `Ctrl+S` (or `Enter` in an input) to apply. A line under the editor
confirms `✓ applied`, along with any warning the change carries.

### The scoring weights

Retrieval ranks memories by a blend of recency, importance and relevance, and
those three weights **must sum to 1.0**. Editing them one at a time would
inevitably pass through invalid states, so they collapse into a single
**grouped** row. Its editor is a small modal with all three fields and a running
sum; *Apply* only lights up when they total `1.0`. (The `settings set` CLI
rejects the individual weight keys for the same reason — change them here, or
edit `settings.toml` directly and let `doctor` validate the result.)

### Migrations and `data-dir`

A few changes have consequences beyond the file, and the editor confirms them in
a modal before doing anything:

- Changing the **embedding provider or model** (the `⚠` rows) means stored
  vectors no longer match — so it offers to **re-embed** every memory now. If you
  say yes, the editor drops out to the terminal so `reindex` can print its normal
  progress, then returns.
- Changing **`data-dir`** offers to **move** your existing data to the new
  location rather than leaving it stranded.

Decline either and the setting still changes — the follow-up just waits until you
run it yourself.

## Where settings live

Resolution order, highest priority first:

1. an **environment variable** (`MAIT_CODE_*`) — source `env`,
2. the **settings file** — source `settings`,
3. the **built-in default** — source `default`.

The file is `settings.toml` under `$XDG_CONFIG_HOME/mait-code/` (i.e.
`~/.config/mait-code/settings.toml` unless `XDG_CONFIG_HOME` is set). The editor
writes it for you, fully commented: primary knobs uncommented, advanced ones
commented-out until you opt in, and the derived paths shown as informational
comments you can't assign. Derived values are computed, never read from the file.

!!! tip "An export can shadow the file"
    Because `env` wins, a `MAIT_CODE_*` exported in your shell overrides whatever
    the editor writes. If a change doesn't seem to take, check your environment —
    the `settings list` view names the source of every value, so a stray export
    shows up as `env`.

## Custom environment variables — the `[env]` table

Some tools need environment variables that aren't mait-code settings at all —
the classic case is `AWS_PROFILE` for Bedrock embeddings. Inside a Claude Code
session the `env` block of `~/.claude/settings.json` supplies it, but a
standalone `mait-code doctor --fix` or `mc-tool-memory reindex` would need a
manual prefix on every invocation.

Instead, declare them once in an `[env]` table at the end of `settings.toml`:

```toml
[env]
AWS_PROFILE = "dev-bedrock"
```

Every mait-code entry point — the `mait-code` CLI and TUIs, the `mc-tool-*`
tools, the `mc-hook-*` hooks — injects these into its environment at startup.
The rules:

- **The real environment wins.** A variable already set in your shell is left
  alone, so a one-off `AWS_PROFILE=other mc-tool-memory …` override still works.
- **`MAIT_CODE_*` keys are not allowed.** Those are first-class settings with
  their own resolution order; `[env]` entries with that prefix are ignored at
  startup and `doctor` warns about them.
- **The table survives rewrites.** `settings set`, the interactive editor and
  install/update all carry it over untouched.

### Managing them

You don't have to edit the file by hand (though that works too):

- **Interactive editor** — the **Custom env** group lists every variable;
  pick one to change its value or remove it, or use the *+ add variable…*
  row to create one. Names are validated live as you type.

![The Custom env group in the settings editor: AWS_PROFILE selected with an
editable value input, a provenance line naming the [env] table as the source,
and Apply and Remove buttons.](assets/settings/settings-env.png)
- **CLI** — address a variable as `env.<NAME>`:

  ```console
  $ mait-code settings set env.AWS_PROFILE dev-bedrock
  $ mait-code settings get env.AWS_PROFILE
  dev-bedrock	(settings)
  $ mait-code settings unset env.AWS_PROFILE
  ```

`settings list` shows each entry as an `env.<NAME>` row with its provenance
(`settings` when the table supplies it, `env` when your shell shadows it).
Values whose names look secret (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`,
`CREDENTIAL`) are masked in the list and tree views.

## Tool approvals — safe permission presets

Claude Code asks for approval on every `Bash` call unless a rule in
`permissions.allow` matches it. For the genuinely safe, high-frequency
commands — `git status`, `wc`, `mc-tool-board list` — that's a prompt dozens of
times a session for no benefit, and it quietly trains the habit of approving
without reading.

The **Tool approvals** group is a curated catalogue of such rules, grouped into
*Git (read-only)*, *File inspection*, *Project tooling* and *mait-code tools*.
Nothing is on by default. Highlight a preset to see the exact rules it writes,
pick a scope, and press **Enable**.

![The Tool approvals group in the settings editor: the git status preset
selected, showing the rule it writes, a scope picker defaulting to the
gitignored project file, the resolved target path, and Enable and Disable
buttons.](assets/settings/settings-tool-approvals.png)

### Scopes

Claude Code reads permissions from three files and takes the union of all of
them, so each row names the scope it came from:

| Scope | File | When to use it |
|-------|------|----------------|
| **Global** | `~/.claude/settings.json` | You want this everywhere. |
| **Project (shared)** | `<repo>/.claude/settings.json` | Committed — everyone who clones the repo gets it. |
| **Project (local)** | `<repo>/.claude/settings.local.json` | Gitignored and personal. **The default.** |

Project scopes need a git repository; outside one, only Global is offered. The
pane prints the resolved target file under the picker, and updates it as you
move the selection, so you can see exactly what you're about to write to.

**Disable** removes the preset from *every* scope holding it, not just the one
in the picker — since Claude Code unions the three files, leaving a copy behind
would keep the rule in force while the row read `off`.

### What's not in the catalogue

Permission patterns are *prefix* matches, so they can't express "this
subcommand but not that flag". Anything whose safe form is distinguished only
by an argument is left out rather than shipped with a caveat:

- `mc-tool-board next` — read-only until `--claim`, which claims a card.
- `mc-tool-memory entities` — searches until `entities merge`, which rewrites
  the graph.
- `mc-tool-memory review` — a prefix rule for it also spans `reviewed`, a
  different, mutating subcommand.
- `mc-tool-inbox drain` and `mc-tool-reminders check`, which both mutate.

A few presets *are* offered but flagged **not read-only** — `uv run ruff check`
(prefix matching also permits `--fix`), `uv run ruff format` and `uv run
pytest`. They can rewrite tracked files or run project code. That's reversible
with git, but the pane warns you before you opt in.

Writes are surgical: your own hand-written rules keep their place and their
order, unrelated keys are preserved, and the file is backed up (once per
session, as `settings.json.bak-<timestamp>`) before the first change. A settings
file that isn't valid JSON is reported rather than overwritten.

## Off the terminal

`mait-code settings` only opens the editor when it's attached to a TTY. Piped or
redirected, it falls back to the read-only `settings list` — a provenance-aware
table of every knob, its resolved value and its source — so scripts and CI see a
stable, parseable view instead of a TUI. The fallback ends with a tool-approvals
section listing the presets you have enabled and where, and `settings list
--json` carries the same under a `tool_approvals` key.

## Reference

### Keys

| Key | Action |
|-----|--------|
| <kbd>↑</kbd> / <kbd>↓</kbd> | Move between settings |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> / <kbd>Enter</kbd> | Apply the edit (or open the grouped weights editor) |
| <kbd>Esc</kbd> | Back to the list (from the editor); quit (from the list) |
| <kbd>q</kbd> | Quit |
| <kbd>?</kbd> | Key cheat-sheet |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> | Command palette (incl. theme switching) |

### The CLI behind it

The editor is the interactive face of the `mait-code settings` command. The same
store backs `settings list` (the read-only table), `settings get <key>` (one
resolved value and its source, for scripting) and `settings set <key> <value>`
(validate → write → run any follow-up). See the
[CLI reference](reference/mait-code.md) for the full surface and flags, and
[How memory works](memory.md) for what the scoring and dedup knobs actually tune.
