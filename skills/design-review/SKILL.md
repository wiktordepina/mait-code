---
name: design-review
description: Run a cold design review of a refined board card, by a reviewer that has seen none of the conversation that refined it, before anyone builds it. Use when you ask for a design review of a card, a second opinion on a refinement, or want a card scrutinised before picking it up.
argument-hint: "<card id>"
allowed-tools: Bash(mc-tool-board show:*), Bash(mc-tool-board summary --json), Bash(mc-tool-board edit:*), Bash(mc-tool-board add:*), Bash(mc-tool-board comment:*)
---

# /design-review

Review a refined card with a reviewer that has seen **none of this session's conversation**, before anyone builds it.

## Why this exists

Whoever refined a card knows why every line of it is there, so they read it for whether it says what they meant, not for whether what they meant is right. A reviewer who never saw that reasoning reads it the second way, and finds the states the card doesn't cover, the criteria nobody can check, and the code that doesn't work the way the card assumes. Those are far cheaper to fix in a card than in a branch.

Everything below protects that one property.

## What the reviewer *does* inherit

Isolation is not total, and overstating it is worse than not having it. The reviewer holds the system prompt: the project `CLAUDE.md`, the user's identity documents and `MEMORY.md`, which carries past decisions and feedback. It also reads the card, and the card is the refiner's framing: its description, its comments (which may summarise an earlier design review) and its references. The agent's brief tells it to form its view from the description and the code before reading comments and references, to treat an earlier review as framing, and not to follow external links. It has not seen the conversation, and that is the guarantee. Discount its agreement on anything the card or the project's conventions already settle.

## The contamination rule

**Pass the reviewer only: the repository path, the card id, the read-only constraint, and a pointer to its standing brief.**

Never include, in the prompt or in follow-up messages:

- why the card is shaped as it is, or what problem it solves
- which options were weighed, chosen or rejected with the user
- which files or modules matter (it finds them itself; naming them is framing)
- a summary of the card, or of an earlier review
- reassurance that some part is already settled

If you find yourself writing "we decided", stop: that sentence is the failure this skill exists to prevent.

## Instructions

1. **Read the card and gate on it.** Run `mc-tool-board show N --json`.

   - It fails because no such card exists: stop and say so.
   - `kind` is `"epic"`: refuse. Epics aren't built directly; offer to review one of its refined members instead.
   - `status` is `done` or `archived`: refuse. There is nothing left to build.
   - `status` is `backlog`, or `acceptance_criteria` is empty: warn that the reviewer will have little to judge, and suggest refining first. Go ahead only if the user says so.
   - `status` is `in_review`: warn that the card is already built, so a design review mostly churns it. Go ahead only if the user says so.
   - `refined` or `in_progress`: go ahead.

   Then check the card belongs to this repository. One board serves several projects, and the reviewer reviews whatever code it is pointed at. Compare the card's `project` with the `project` that `mc-tool-board summary --json` reports for the current directory. If they differ, stop and ask: the user may be in the wrong repository, or may want the review run from the card's own.

2. **Spawn one `design-reviewer` agent** via the Agent tool (`subagent_type: "design-reviewer"`). A fresh Agent call inherits no context; never `SendMessage` an earlier reviewer, which would carry its first review into the second.

   **If that agent type does not resolve, stop and say so.** The registry is read at session start, so a freshly installed agent is not available until Claude Code restarts. Never fall back to `general-purpose` with the brief pasted in: that agent has no tool restriction, so the reviewer would run with write access while the user believes it is read-only. Offer the restart.

   The prompt carries only the four items in the contamination rule, for example:

   > Design review of board card #N in the repository at /path/to/repo. Follow your standing brief. Read-only: change nothing, and write nothing to the board.

3. **Relay the review in the session.** The agent's output is not shown to the user, so reproduce it: organised, but not softened. Don't quietly drop a finding you disagree with; report it and say why you disagree.

4. **Verify before you act.** Check every concrete claim (the `file:line` ones, and any claim about what a command or module does) yourself, and say which you confirmed and which you could not. A finding you could not reproduce is worth reporting as exactly that.

5. **Propose resolutions.** For each finding, recommend how the card should change, or why it shouldn't. Put proposed cards separately:
   - follow-ups the card implies: `mc-tool-board add "<title>" --from N`, which inherits N's epic;
   - unrelated issues the reviewer noticed: `mc-tool-board add "<title>" --from N --parent none`.

   Ask how any new card orders against N and its siblings before linking `blocks`. `mc-tool-board link` is deliberately outside this skill's grant, so a link also goes through the permission prompt.

6. **Write only what the user approves.** Nothing reaches the board until they say so. Then:
   - fold the approved resolutions into the card with `mc-tool-board edit N --description … --acceptance …`, keeping any section headed **Testing strategy** under exactly that heading (a playbook may read it);
   - add a comment saying what the review changed: `mc-tool-board comment N --author claude "Design review folded in: …"`;
   - add the approved cards.

   Don't move the card, and don't touch its playbook run: a playbook that calls this skill records its own step.

## Notes

- **The grant covers applying an approved review, not deciding one.** `show` reads the card and `summary --json` names this repository's project; `edit`, `add` and `comment` apply what the user approved in step 6. The skill must not write before that approval; the grant makes the approved writes quiet, it doesn't approve them. `link`, `move`, `refine` and `remove` are left out.
- **The reviewer's `Bash` is not pattern-restricted.** Agent definitions list tool names, not permission patterns, and the reviewer needs a shell for `mc-tool-board show` and the odd probe. Its read-only constraint, board included, is enforced by its brief and the usual permission prompts. A board write from the reviewer is a bug in the review, not a step to approve.
- **Session-only.** Nothing is posted anywhere.
- **A clean review is a result.** If the reviewer finds nothing, say so plainly rather than manufacturing concerns.
