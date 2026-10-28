# Writing Style

*How text written on your behalf reads to other people*

---

These are the rules `/outward-comms` applies to anything another person reads:
PR comments and descriptions, review replies, commit messages, issue comments,
chat messages, emails, and docs committed to a repo. `communication_style.md`
governs how the companion replies to you; this file governs how it writes as
you. Edit freely: the skill reads this file each time it runs, and updates
never overwrite your changes.

## Rule 1: No em dashes

Readers increasingly take the em dash (`—`) as a sign of machine-written text.
Don't use it, anywhere, in any outward-facing text.

Replace it with whichever fits:

| Instead of an em dash | Use |
|---|---|
| Parenthetical aside | Spaced hyphen ` - `, or brackets |
| Two clauses, second explains the first | Colon `:` |
| Two clauses, loosely joined | Full stop, or a semicolon |
| Abrupt pivot | Just start a new sentence |

En dashes (`–`): avoid in prose. Acceptable in numeric ranges, but a plain
hyphen (`12-14%`, `$8-9k`) is preferred.

## Rule 2: Plain characters in prose

Inside a sentence, stick to ASCII. Typographic substitutes read the same as
their plain versions, and the plain versions survive terminals, diffs,
plain-text email and commit messages.

| Instead of | Use |
|---|---|
| `—` `–` dashes | see Rule 1 |
| `“ ” ‘ ’` smart quotes | `"` and `'` |
| `…` ellipsis | `...` |
| `→ ← ⇒ ↑ ↓` arrows mid-sentence | `->`, or words: "becomes", "then", "up from" |
| `• ▪ ‣` bullets mid-text | a markdown `-` list, or a plain hyphen |
| `× ÷ ≤ ≥ ≠ ± ≈` | `x`, `/`, `<=`, `>=`, `!=`, `+/-`, `~` |
| `α β λ Δ π µ` Greek letters | spell them out: alpha, delta, pi, micro |
| `© ® ™ § ¶ °` | `(c)`, `(R)`, `(TM)`, "section", "para", "degrees" |
| `½ ¼ ¾` | `1/2`, `1/4`, `3/4` |
| non-breaking space, zero-width space | an ordinary space, or nothing |

Currency symbols you'd type yourself (`£`, `€`) are fine.

### Rule 2a: Glyphs and emoji doing structural work

The list above covers characters that decorate prose. A glyph carrying
**structure** is a different thing and is often the better choice: a status
column in a table, an arrow in a flow, a small ASCII or box-drawn diagram, a
mark that lets a reader scan a result set instead of reading every row. Where a
glyph genuinely lowers the cost of reading, use it. A long technical document
that lands as an undifferentiated wall of text has a real cost, and refusing a
glyph that would have broken it up is not good style.

The test is **function, not decoration**:

- A tick in a results column, so a reader sees which rows passed at a glance:
  earns its place.
- A warning mark on the one caveat in a long list, so it can't be skimmed
  past: earns its place.
- An emoji on every heading because the page looked plain: doesn't. Nor does a
  glyph standing in for a word in a sentence that read fine already.

**By medium:**

| Medium | Position |
|---|---|
| PR bodies and descriptions | **Allowed by default.** Tables with status marks, comparison tables, a small ASCII diagram of a flow. No need to ask. |
| Published HTML documents | Allowed for visual and structural work. Prose stays plain. |
| Chat (Slack and the like) | Allowed where the medium expects it and you use them there yourself. |
| Issue trackers, review replies, emails, commit bodies, docs committed to a repo | Only where the benefit is clear and substantial. **Ask first**, unless you asked for them. |
| PR titles, commit subject lines | **Never.** These get truncated, pasted into chat and copied into release notes, so a glyph follows the change around forever. |

Two things this doesn't relax:

- **Rule 1 still holds everywhere.** An em dash is not structural work.
- **Markdown that renders.** Prefer real syntax to a glyph imitating it. A
  GitHub task list (`- [x]`) gives a genuine checkbox and stays ASCII, so it
  beats a pasted tick in a list. It only renders at the start of a list item:
  inside a table cell it shows literally, so a table wants a glyph or a plain
  word instead.

Narrow exceptions, where accuracy beats the rule:

- **Quoting verbatim.** Someone else's message, a log line, an error string:
  reproduce it exactly, character for character.
- **Code and identifiers.** Filenames, config values, package names, test
  fixtures that genuinely contain the character.
- **Proper nouns.** Spell people's names and place names correctly: José,
  Zürich, Malmö.
- **Units and maths where ASCII is genuinely wrong** in context. Prefer "us"
  or "microseconds" over `µs`; keep the symbol only if the reader would
  misread the substitute.

## Rule 3: No AI clichés

Cut sycophantic openers, formulaic acknowledgements, and filler transitions.
The lists aren't exhaustive; the pattern matters more than the list.

**Openers to delete outright:**

- "Good question", "Great question", "Fair question"
- "You're absolutely right", "You're right", "Good point", "Fair point"
- "Nice catch", "Good catch", "Good spot", "Well spotted"
- "Honest answer:", "To be honest", "Honestly"
- "Absolutely", "Certainly", "Of course"
- "Thanks for flagging this", "Thanks for the thorough review"
- "I appreciate you raising this"

**Filler to delete:**

- "It's worth noting that", "It's important to note that"
- "That said," as a reflex hedge (fine once, if it earns its place)
- "I hope this helps", "Let me know if you have any questions",
  "Happy to discuss further"
- Restating the question before answering it
- A closing paragraph that summarises the paragraph above it

**Genuine warmth is not a cliché.** If a reviewer found a real bug, "Fixed,
thanks" is fine. The banned thing is formulaic praise as a warm-up before the
actual content. The test: delete the sentence. If nothing is lost, it was a
cliché.

## Rule 4: Concise and direct

- **Answer first.** Lead with the answer, the decision, or the fact. Context
  and reasoning follow only if the reader needs them.
- **One point per paragraph.** If a paragraph makes two points, split it or
  cut one.
- **No stylistic decorators.** No rhetorical questions, no "the interesting
  thing here is", no dramatic one-line paragraphs for effect, no bolding
  scattered through a short message for emphasis.
- **Don't pad a short answer.** If the answer is one sentence, send one
  sentence. Length is not politeness.
- **Don't stack hedges.** "It seems like this might possibly be" is one hedge
  too many. Say it, or say you're not sure and why.

**Concision never deletes substance.** Keep genuine uncertainty, caveats,
assumptions, and anything the reader needs in order to disagree. Cut the
decoration around them, not the content. A message that admits a gap is better
than one that reads smoothly and hides it.

## Rule 5: Register and spelling

- Use your spelling convention throughout (see `user_context.md`). The default
  is British English.
- Write to a technical peer. No explaining what they already know, no
  condescension, no over-formality.
- Plain declaratives. Active voice.

## Examples

**Before:**

> Good question! You're absolutely right to flag this — it's an important
> consideration. The reason we've gone with two instances rather than three is
> that Aurora actually decouples durability from instance count. It's worth
> noting that the storage layer keeps six copies across three AZs regardless.
> Hope that clarifies things, and let me know if you'd like me to expand!

**After:**

> Two instances are enough because Aurora decouples durability from instance
> count: the storage layer keeps six copies across three AZs regardless.

**Before:**

> Thanks for the review! Nice catch on the typo — I've gone ahead and fixed
> that. Let me know if there's anything else.

**After:**

> Fixed, thanks.
