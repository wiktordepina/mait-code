---
name: create-skill
description: >
  Knowledge base for creating Claude Code skills. Use when the user asks to
  create a new skill, write a SKILL.md, add a slash command, or needs help
  with skill frontmatter, syntax, or best practices.
allowed-tools: Read,Write,Glob,Bash
---

# Creating Claude Code Skills

## Quick Reference

Skills are `SKILL.md` files in `.claude/skills/<skill-name>/SKILL.md` that extend Claude Code with custom commands and workflows.

## Full Guide

Read the complete skills guide before creating a new skill:

```
/opt/obsidian-vault/Mait/reference/claude-code-skills-complete-guide.md
```

**Always read this file** when creating or modifying skills. It covers all frontmatter fields, syntax features, patterns, and best practices.

## Steps to Create a Skill

1. Read the full guide at the path above
2. Clarify the skill's purpose, trigger conditions, and whether it should be user-invocable, model-invocable, or both
3. Create the directory: `.claude/skills/<skill-name>/`
4. Write the `SKILL.md` with appropriate frontmatter and instructions
5. Test the skill by invoking it

## Key Conventions (This Project)

- Skills live in `.claude/skills/<skill-name>/SKILL.md`
- Use `user-invocable: false` for skills that should only auto-trigger (no `/` command)
- Write clear `description` fields — Claude uses these to decide when to auto-invoke
- Keep skills focused on a single responsibility
