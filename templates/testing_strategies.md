# Testing Strategies

*The ways a card's work can be tested, for refinement to choose from*

---

When a card is refined through the board skill, its description gains a
**Testing strategy** section that names the strategies below which fit the
card, what each will check, and why. A playbook such as `/work` can then run
exactly those at its test step, rather than deciding again.

Edit freely: add the environments you test in, remove what you don't use.
Updates never overwrite your changes.

**How an entry is written.** A `##` heading with the strategy's name, then
prose: what it proves, and how to run it. Write the steps the way you'd brief
a colleague; any commands in them run under the usual permission prompts.

**Scoping.** An entry may start with a `Projects:` line naming the projects it
applies to (comma-separated, as the board names them). Refinement offers an
entry only in those projects. An entry without the line applies everywhere.

This list is a set of suggestions, not a limit: refinement can propose a
strategy that isn't here, and says so when it does.

## unit

The project's own automated tests: unit and integration suites, plus the lint
and type checks that run with them.

Run them the way the project says to, in its `CLAUDE.md`, `CONTRIBUTING.md` or
README. Name the tests that cover this card's change, and add any that are
missing.

## manual

A scripted, hands-on check of the change, on a throwaway target: a scratch
card, a temporary data directory, a test account, a branch nobody else uses.

Write the steps and the expected result for each before running them, so the
check can be repeated. Never point it at real data.
