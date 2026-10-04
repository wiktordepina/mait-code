# The remote API

`mait_code.remote` is the part of a mait-code instance that another machine or
agent may touch: read the board, raise cards, refine them, search memories and
list reminders. It is a **Python module, not a server**. A separate service you
run — typically one that speaks MCP to remote Claude Code sessions or other
agents — imports it and decides who may call what. mait-code itself never opens
a port.

That split is deliberate. mait-code has no background services, so the
listening, the authentication, the per-client scopes and the process lifecycle
live in the host. The rules about *what may happen to the instance* live here,
next to the data model and its tests.

## What it can do

| Function | Does |
|----------|------|
| `list_cards` | Cards ordered priority-then-oldest; filter by project, status, tag or title. Archived cards are left out unless asked for by status. |
| `get_card` | One card with its comments, in the `mc-tool-board show --json` shape. |
| `list_projects` | The projects that have cards. |
| `create_card` | A new card, **always in backlog**: there is no status parameter. |
| `refine_card` | Edit description and acceptance criteria, and move between **backlog and refined** only. |
| `search_memories` | The same hybrid search and ranking as `mc-tool-memory search`, each result with a `score`. |
| `list_reminders` | Active reminders, due time as ISO 8601, each flagged `overdue` or not. |

Every function takes the instance's data directory as its first argument.

```python
from pathlib import Path

from mait_code import remote

data = Path("/home/agent/.claude/mait-code-data")

card = remote.create_card(
    data, client="hermes", project="homelab", title="Rotate the forge token"
)
remote.refine_card(
    data, card["id"], client="laptop", acceptance="- token rotated\n- runbook updated"
)
```

## What it deliberately can't

Deleting or archiving cards, tags, moving a card into In Progress, In Review or
Done, writing or retiring memories, applying reflections, and changing
reminders. These are decisions for whoever owns the instance, so the functions
**don't exist** on this surface; they aren't refused at runtime. A test pins
the module's public names to an allowlist, so adding one is a visible change to
this contract, not a quiet addition.

A refine of a card outside backlog/refined, or towards any other column, raises
`TransitionRefused` and changes nothing. The status check and the write happen
in one transaction, so a card the instance moves on concurrently can't be
pulled back.

## Provenance

Every write names its caller. `create_card` stores `client` as the card's
**Created by** field, which `mc-tool-board show` prints and the board TUI shows
as *via &lt;client&gt;* on the card's meta line. `refine_card` adds a comment
authored by `client` saying what changed. A card raised by an agent is
identifiable before anyone picks it up, which matters once card text becomes a
prompt.

## Running it as a different user

A host service should run as its own user rather than as the one that owns the
instance, so that a compromised session on the instance can't reach the
service's credentials. The module is written for that arrangement:

- **No config that executes.** It reads only `board.db`, `memory.db` and
  `reminders.db` from the data directory. It never reads `dashboard.toml`,
  whose command tiles run shell commands, and never applies the settings
  `[env]` table or touches the process environment. Run anything that *does*
  read the instance's config, like the home hub, as the instance's own user.
- **No migrations.** The host pins its own mait-code release. If a database's
  schema version isn't the one that release expects, calls raise
  `SchemaMismatch`, which names both versions, instead of upgrading or
  downgrading the instance. Upgrade whichever side is behind. A missing
  database raises `FileNotFoundError`; nothing is created.
- **Read-only where it can be.** Memories and reminders are opened read-only.
  The board is opened read-write with a 10-second busy timeout, since the
  instance writes it too.
- **Permissions.** The service user needs read access to the data directory,
  and write access to `board.db` **and** its `board.db-wal` and `board.db-shm`
  files. SQLite's WAL mode writes all three; group-write on the database alone
  isn't enough. Reading the other two databases in WAL mode also needs their
  `-shm` files to exist, so the instance should have opened them at least once.

## Embeddings

`search_memories` runs keyword and vector search. The vector half embeds the
query with the provider in the **host's** settings, which must match the
instance's (`embedding-provider`, `embedding-model` or `bedrock-model-id`). If
they differ, or the provider can't load, results fall back to keyword-only
rather than failing. See [how memory works](memory.md) for the settings.
