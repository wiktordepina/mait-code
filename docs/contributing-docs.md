# Contributing to the docs

This page covers the conventions for editing prose docs, adding API
reference pages, and regenerating the auto-generated bits. It is the
counterpart to `docs/gen_ref_pages.py` — read both if you are touching
the reference surface.

## Quick reference

```bash
# Install docs dependencies
uv sync --group docs

# Build the site locally and serve at http://127.0.0.1:8000
uv run mkdocs serve

# Strict build (used by CI; must be green before merging)
uv run mkdocs build --strict

# Regenerate docs/reference/*.md after editing __all__
uv run python docs/gen_ref_pages.py

# Check for reference drift (CI-style)
uv run python docs/gen_ref_pages.py --check
```

## Prose docs (`docs/*.md`)

The hand-authored pages under `docs/` live under the **Home**,
**Guide**, and **Architecture** tabs (the **Reference** tab is
auto-generated — see below).

Conventions:

- **Markdown**, GitHub-style. The full set of pymdown extensions is
  enabled in `mkdocs.yml` — admonitions, tabbed code blocks, mermaid
  fences, footnotes, etc.
- **British English** spelling and grammar (behaviour, organise,
  centred).
- **Imperative** mood in step-by-step guides ("Run the migration", not
  "You should run the migration").
- **Headings start at H2** within a page; the H1 is the page title
  declared in the nav.
- **Internal links** use relative Markdown paths (`./memory.md`,
  `../architecture.md`); strict mode catches broken targets.
- **Code blocks** declare their language for syntax highlighting:
  ` ```python `, ` ```bash `, ` ```toml `, etc.

To add a new prose page:

1. Create the file under `docs/` (or a subdirectory if a section grows
   that warrants nesting).
2. Add it to the `nav:` block in `mkdocs.yml` under the appropriate
   tab — `strict: true` will fail the build if a doc exists but is not
   in the nav.
3. Run `uv run mkdocs build --strict` to verify.

## API reference (`docs/reference/`)

The Reference tab is **regenerated from each module's `__all__`** by
`docs/gen_ref_pages.py`. Editing files under `docs/reference/` by hand
is futile — the next regeneration run overwrites them, and CI's
`--check` invocation will flag the drift.

### The `__all__` contract

For a module to surface in the reference, it must:

1. Be listed in `REFERENCE_MODULES` inside `docs/gen_ref_pages.py`.
2. Declare `__all__` as a list (or tuple) of string literals.
3. Live at `src/mait_code/<name>.py` or
   `src/mait_code/<dotted>/<name>/__init__.py` (the generator resolves
   either layout).

The generator parses `__all__` via `ast`, then re-scans the source
text for `# Section` comments interleaved inside the list. Those
comments become H2 headings on the rendered page, grouping the
symbols below them.

Example from `src/mait_code/tools/memory/__init__.py`:

```python
__all__ = [
    # CLI
    "main",
    # Storage
    "connection",
    "get_connection",
    # Embeddings
    "EmbeddingProvider",
    "embed_text",
    ...
]
```

becomes a page with `## CLI`, `## Storage`, `## Embeddings`, …
headings, each followed by a `:::` mkdocstrings directive per symbol.

If a module has fewer than ~3 symbols, the section comments are
usually noise — leave them out and let the symbols render as a flat
list.

### Adding a module to the reference

1. Add `__all__` to the module's `__init__.py` (or the single-file
   module). Re-export the public symbols you want documented; keep
   internals out.
2. Optionally group with `# Section` comments.
3. Append a `(name, display)` tuple to `REFERENCE_MODULES` in
   `docs/gen_ref_pages.py`. Use the dotted module name relative to
   `mait_code` (e.g. `"tools.memory"`); the generator handles the path
   resolution.
4. Add the page to the **Reference** section of the nav in
   `mkdocs.yml`. The filename is the dotted name with dots replaced by
   hyphens: `tools.memory` → `tools-memory.md`.
5. Regenerate: `uv run python docs/gen_ref_pages.py`.
6. Verify drift-free: `uv run python docs/gen_ref_pages.py --check`.
7. Verify strict build: `uv run mkdocs build --strict`.

### Removing a symbol from the reference

Remove it from `__all__`. The next regeneration drops it from the
page. Do not edit the generated Markdown directly.

## Google docstring style

mait-code uses Google-style docstrings throughout `src/mait_code/`
because `mkdocstrings` (configured for `docstring_style: google`)
renders them into the reference pages.

The shape:

```python
def store_memory(content: str, *, importance: int = 5) -> int:
    """Persist an observation to the memory store.

    Longer prose paragraph that explains the *why*, the side
    effects, or any subtle behaviour. Omit if the summary line is
    self-explanatory.

    Args:
        content: The observation text to store.
        importance: 1-10 weight feeding the recency/importance
            composite score.

    Returns:
        The new entry's primary-key ID.

    Raises:
        ValueError: If ``content`` is empty.
    """
```

Conventions:

- **Imperative** summary line: "Persist X", not "Persists X" /
  "This function persists X".
- Skip `Args:` if there are no parameters worth documenting beyond
  what the signature already conveys.
- Skip `Returns:` if the function returns `None` obviously.
- Use double back-ticks for inline code (mkdocstrings renders them
  cleanly in either Markdown or HTML contexts).

If `mkdocs build --strict` complains about a symbol's docstring
mentioning an annotation that isn't on the signature (`griffe: No
type or annotation for parameter X`), add the missing type
annotation rather than removing the documentation.

## What CI runs

Brick D will wire `.github/workflows/docs.yml` to run these on every
push to `main` and on every tag:

```bash
uv sync --group docs
uv run python docs/gen_ref_pages.py --check
uv run mkdocs build --strict
```

Until then, the same commands should pass locally before pushing.
