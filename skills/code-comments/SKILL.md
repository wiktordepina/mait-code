---
name: code-comments
description: House conventions for code comments and docstrings - functional not narrative, no history or ticket references, no ephemeral facts, comment the counter-intuitive rather than the obvious, ASCII only. Use when writing or editing a comment, docstring or module header, and when asked to audit, tidy or rewrite the comments on a branch or in a path.
argument-hint: "<optional: file or path to sweep>"
---

# /code-comments

How comments get written in the user's code. Two modes:

* **Write mode** (usually triggered rather than invoked): apply these rules
  while writing or editing a comment or docstring. No need to announce it.
* **Audit mode** (invoked, or when asked to tidy comments): read the comments
  in scope, report what breaks the rules, propose rewrites. See *Audit mode*
  below for its two scopes.

Write mode relies on the skill being triggered, which is best effort. The
guaranteed paths are invoking `/code-comments` and a playbook's comment-audit
step, which runs audit mode over the branch.

Related: `/outward-comms` governs prose that other people read. This skill
governs text inside source files. Rule 7 below covers the one overlap on its
own terms.

## Rule 1: Match the project before applying a default

Comment and docstring style is a project-level decision, not a personal one. A
consistent file beats a correctly-formatted one. Establish the convention
first, in this order, stopping at the first answer:

1. **Explicit config.** `pyproject.toml` (`[tool.ruff.lint.pydocstyle]`
   convention, pydocstyle, pylint, darglint), `.golangci.yml`, `.editorconfig`,
   `setup.cfg`, `.rubocop.yml`.
2. **Written house rules.** `CONTRIBUTING.md`, `CLAUDE.md`, `AGENTS.md`,
   `docs/style*`, a team style guide the repo links to.
3. **The dominant pattern in the code.** Sample the file being edited first,
   then its nearest siblings, then the most recently touched modules. Prefer
   recent code over the oldest code in the repo: old files often show a
   convention the project has already moved away from.
4. **Ask.** If the project is greenfield, or has no comments to learn from, or
   is split near evenly between two styles with no config to break the tie,
   ask which style to use. Do not silently pick one.

Detection is cheap, so do it rather than assume. Search with the Grep tool:

| Looking for | Pattern | Files |
|---|---|---|
| Google docstrings | `Args:\|Returns:\|Raises:` | `*.py` |
| Sphinx / reST docstrings | `:param \|:returns?:\|:raises?` | `*.py` |
| NumPy docstrings | `Parameters\n\s*-{3,}` (multiline) | `*.py` |
| A declared convention | `convention\|docstring\|pydocstyle\|darglint` | `pyproject.toml`, `setup.cfg` |

**Mixed repo:** follow the file you are editing. Mention the inconsistency to
the user once, as an observation, and leave the rest of the repo alone unless
they ask for a sweep.

**Greenfield, and the user has no preference:** default to the most readable
plain-text option for the language. Google style for Python, godoc prose for
Go, a header block for shell.

Rule 1 decides flavour and layout. It does not override Rule 7: a file full of
non-ASCII comments still gets ASCII in every comment you write or touch.

## Rule 2: Functional, not narrative

A comment describes the code as it is now. It is not a changelog, a rationale
diary, or a record of the conversation that produced it.

**Never appears in a comment:**

* Ticket keys, issue numbers, PR numbers, commit SHAs (`ABC-123`, `#412`,
  `see PR 87`, `per a3f9c21`)
* History and transitions: "used to", "previously", "we changed this to",
  "originally", "as of the refactor", "the old implementation", "now uses",
  "temporary until we migrate", "left over from"
* Comparison to an alternative that isn't in the code: "unlike the v1 client",
  "this replaces the batch job"
* Attribution and dialogue: names, dates, "as discussed", "per review
  feedback", "the user asked for", "TODO(someone)"
* Apology or self-commentary: "this is ugly but", "sorry about this", "hacky"
* Section banners made of punctuation, ASCII art, decorative rules

**The five-minute test.** Read the comment as if it were written five minutes
ago by someone who has never seen an earlier version of the file. If any part
of it only makes sense to a reader who knows the history, cut that part.

The information is not lost: history belongs in git, decisions belong in an
ADR, work belongs in the tracker.

### Rewriting history into fact

Almost every history comment has a functional statement hiding inside it. Find
it and keep only that.

| Instead of | Write |
|---|---|
| `# we used to retry 3 times, now 5 after ABC-123` | `# five attempts covers the observed p99 broker failover` |
| `# don't use requests here, it broke in prod (see #88)` | `# urllib3 directly: requests' session pooling is not fork-safe under gunicorn` |
| `# temporary workaround until upstream fixes this` | `# upstream returns 200 with an error body, so status alone is not enough` |
| `# switched to cents after the rounding bug in invoices` | `# amounts are integer cents: float totals drift when a refund is split` |
| `# TODO(alice): clean this up` | delete it, or make it a card on the board |

**TODO and FIXME:** allowed, sparingly, and must be self-contained. State the
condition that makes the work possible or necessary, with no owner, no date and
no ticket. `# TODO: collapse into one query once the read replica is available`
is fine. `# TODO: fix this properly` is noise. If it needs tracking, it belongs
on the board, not in the source.

## Rule 3: No ephemeral facts

Anything a comment asserts about the code must stay true as the code moves
around it. Facts that drift silently are worse than no comment: they are
actively misleading once stale, and nothing fails when they rot.

**Do not reference:**

* Line numbers or ranges (`see line 42`, `defined at L118`)
* Counts that are visible in the code (`the three handlers below`, `all 12
  regions`, `both branches`)
* Positions and ordering (`the second one`, `the last item in the list above`)
* Sizes, timings and thresholds copied from elsewhere (`the 30s timeout in the
  caller`) rather than named
* Dates, sprint names, release numbers, "currently", "at the time of writing"
* Env or resource names that a rename would break, when a description works
  instead

**Do instead:**

* Refer to things by name: `see resolve_customer()`, `mirrors TIMEOUT in
  client.py`, `matches the handler registry keys`
* Say what the set is, not how big: `one handler per payment method`
* Let a constant carry the number, and comment the constant once
* If the fact genuinely lives in two places, make the comment say so, so the
  next reader knows to check both

## Rule 4: Comment the intricacy, never the obvious

The default is no comment. Code that reads clearly needs nothing, and a comment
that restates the line above it is pure cost: it doubles the reading and rots
independently.

**Do not comment:**

* What the statement plainly does (`# increment the counter`, `# return the
  result`, `# loop over users`)
* Anything the name already says. If the comment is the function name in a
  sentence, delete the comment. If the name is bad, rename it instead.
* Anything the type hints or signature already say
* Language or library basics a competent reader of that stack knows

**Do comment:**

* **Counter-intuitive code.** Anything where a reader's first instinct would be
  "this looks wrong" or "this could be simpler". Say why it is that way. This
  is the single highest-value comment there is.
* **Non-obvious constraints from outside the file.** API quirks, rate limits,
  eventual consistency, an ordering the code cannot express, a field that means
  something other than its name suggests.
* **Deliberate omissions.** A case not handled, an error swallowed on purpose,
  a retry deliberately absent. Silence looks like an oversight.
* **Non-obvious units, ranges and encodings.** Seconds versus milliseconds,
  base64 of a UTF-8 payload, inclusive versus exclusive bounds, 1-indexed.
* **Concurrency and lifecycle facts.** What holds a lock, what is safe to call
  once only, what must not run in a thread.
* **Chosen tradeoffs.** Why the O(n^2) version is right at this size, why the
  data is loaded eagerly.

The test: would a competent engineer reading this file cold get it wrong, or
waste minutes working out why, without the comment? If yes, comment it. If no,
delete it.

## Rule 5: Section markers

One line, occasionally two, marking a phase of a longer body. These are
welcome where they help someone skim a function, and only there.

```python
# resolve the customer before touching the order store
...

# fan out per region, sequential on purpose: the billing API is single-flight
...
```

* Lower case, no full stop, imperative or gerund. Match whichever the file
  already uses.
* Only in a body long enough to have phases. A five-line function does not
  need signposting.
* They must add something a glance does not: the phase's purpose, or a
  constraint that shapes it. `# setting up the client` above two lines of
  obvious client setup is filler; `# client per region: credentials are not
  shared across partitions` earns its place.
* If a function needs four or more of them, it probably wants splitting into
  functions. Say so rather than adding the markers.
* Never number them (`# step 1`, `# step 2`). They break on reorder, which is
  Rule 3.

## Rule 6: Docstrings and API blocks

Structure comes from the project convention (Rule 1). What goes in it:

**Coverage.** Anything callable from outside its module gets the full treatment:
a summary line, then the sections the language convention provides for
parameters, return value and errors. Private helpers get a one-line summary,
and gain sections only where a parameter, return value or failure mode is
genuinely non-obvious. A three-line private helper with an honest name needs
nothing.

**The summary line.** One sentence, declarative, says what the function
returns or does. Not the function name reworded. Not a paragraph.

**Parameters.** Document the meaning, the constraint, the surprise. Do not
document the type: the signature does that, and prose types go stale. Skip a
parameter entirely if its name and type say everything.

* Weak: `customer_id: The customer ID.`
* Strong: `customer_id: External customer reference, not the internal row id.`

**Returns.** Say what it is and what the empty, zero or None case means. Do not
repeat the return annotation.

**Errors.** Document what a caller can be expected to handle, and the condition
that raises it. Do not list every exception that could theoretically escape.

**Side effects belong in the docstring.** Writes to disk, network calls,
mutation of an argument, cache population, anything the signature hides.

Language-specific templates and per-language rules: `reference/languages.md`.
Read that file before writing docstrings in a language you have not already
seen conventions for in this repo.

## Rule 7: ASCII only

Every comment, docstring and module header is plain ASCII: nothing matching
`[^\x00-\x7F]`. Source files are read through diffs, terminals, pagers, log
lines and tools that assume ASCII, and anything outside it renders wrongly,
misaligns or breaks in at least one of them.

This rule wins over Rule 1. A file whose existing comments use em dashes or
smart quotes still gets ASCII in every comment you write or touch; Rule 1 only
decides docstring flavour and layout.

| Instead of | Use |
|---|---|
| em and en dashes | ` - ` or a colon for an aside, a hyphen in a range (`12-14`) |
| smart quotes | `"` and `'` |
| an ellipsis glyph | `...` |
| arrows | `->`, `<-`, or words |
| comparison and maths signs | `<=`, `>=`, `!=`, `+/-`, `~`, `x` |
| Greek letters | spell them out: `alpha`, `delta`, `micro` |
| box drawing, bullets, emoji | plain text, a `-` list, or nothing |

**Naming a non-ASCII character.** A comment that has to talk about one (a test
for a glyph, a parser for smart quotes) names it by escape or Unicode name,
never the literal: `U+2014 EM DASH`, `"\u2014"`.

The other exceptions are narrow: a verbatim quoted error string or log line,
an identifier or literal that genuinely contains the character, a proper noun.

Check a file with the Grep tool, pattern `[^\x00-\x7F]`.

## Audit mode

Two scopes:

* **No argument (the default):** the current branch's changes. Read the diff
  against the base branch (the remote's default, as `/pre-pr-review` resolves
  it) plus any uncommitted changes. In scope: comment and docstring lines the
  branch adds or changes, and any comment in the same function or block whose
  meaning the change affects. Old violations elsewhere in a touched file are
  out of scope: mention them once, as an observation, and offer a separate
  pass. A playbook's comment-audit step uses this scope.
* **A path:** a sweep of every comment in that file or directory. Only when
  asked: it inflates a diff and buries the real change.

**Grep first, then read.** Search with the Grep tool rather than `rg` through
the shell. These patterns catch the mechanical breaches:

| Breach | Pattern (case-insensitive where marked) |
|---|---|
| Ticket keys, PR and issue refs, commit SHAs | `(#[0-9]+\|[A-Z]{2,10}-[0-9]{1,6}\|\b[0-9a-f]{7,40}\b)` |
| History narration (i) | `used to\|previously\|formerly\|originally\|legacy\|as of \|now (uses\|we)\|no longer\|left over\|temporar\|workaround\|deprecated in favour\|before this\|old (impl\|version\|code)` |
| Ephemeral references (i) | `\b(line\|lines\|L) ?[0-9]+\|at the time of writing\|currently\|for now\|see above\|see below\|the (two\|three\|four\|five) ` |
| Non-ASCII | `[^\x00-\x7F]` |

Grep is a first pass, not the verdict. `currently` inside a string literal is
fine, a SHA-shaped hex string might be a real fixture, and a comment can break
Rule 4 without matching any pattern. Read the hits, and in the default scope
keep only those on lines the branch touched.

**Then read for the judgement calls:** comments that restate their code,
comments that no longer match the code, comments that would confuse a reader
coming in cold, and the inverse - counter-intuitive code with nothing
explaining it. A missing comment on a genuinely surprising line is a finding.

**Report as:** file and the identifier it sits in (not the line number), the
rule broken, the proposed replacement or a deletion. Group by file. If a
comment is wrong rather than merely badly styled, flag that first and
separately: a comment that contradicts its code is a bug report, and the code
may be the thing that is broken.

**Deleting is a valid fix, and often the right one.** Do not rewrite a comment
that should not exist.

## Pass before finishing

Over every comment written or touched:

1. Does it say anything the code does not already say? If not, delete it.
2. Would it still make sense to someone who has never seen an earlier version
   of this file? Cut anything that fails.
3. Any ticket key, PR number, SHA, name, date, or history word?
4. Any line number, count, position, or "currently"?
5. Does the surprising code in this change have a comment, and does the
   unsurprising code lack one?
6. Does the style match the file it is in?
7. Grep the touched files for `[^\x00-\x7F]` (Rule 7).

## Examples

**Before:**

```python
def get_orders(customer_id, limit=50):
    # ABC-123: we used to fetch all orders and filter in python, but that
    # was too slow, so now we push the limit down to the query. Note the
    # limit is capped at 200 - see line 88 in the repository layer.
    # loop over the rows and build the result
    rows = self._repo.recent(customer_id, limit)
    return [Order.from_row(r) for r in rows]
```

**After:**

```python
def get_orders(customer_id: str, limit: int = 50) -> list[Order]:
    """Return a customer's most recent orders, newest first.

    Args:
        customer_id: External customer reference, not the internal row id.
        limit: Silently clamped to MAX_PAGE by the repository layer.

    Returns:
        Empty list if the customer exists but has no orders.

    Raises:
        CustomerNotFound: No customer with this reference, including
            soft-deleted ones.
    """
    rows = self._repo.recent(customer_id, limit)
    return [Order.from_row(r) for r in rows]
```

**Before:**

```go
// sleep for a bit
time.Sleep(2 * time.Second)
```

**After:**

```go
// the tag write is read-your-writes only after propagation, so poll rather
// than assume the next Describe call sees it
time.Sleep(2 * time.Second)
```

**Before:**

```bash
# increment counter
count=$((count + 1))

# check if we should continue
if [ "$count" -lt 5 ]; then
```

**After:**

```bash
count=$((count + 1))

# five attempts: IAM propagation is eventually consistent and typically
# settles inside four
if [ "$count" -lt "$MAX_ATTEMPTS" ]; then
```
