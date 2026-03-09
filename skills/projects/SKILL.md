---
name: projects
description: List and manage registered projects
allowed-tools: Bash(mc-tool-tasks *)
---

# /projects

Show all registered projects.

## Data

!`mc-tool-tasks projects 2>/dev/null || echo "No projects registered yet."`

## Instructions

Present the registered projects list clearly. Each project shows its name, disk path, GitHub URL (if any), and when it was added.

Projects are auto-registered when you work with tasks in a project directory. To register the current project without adding a task, run `mc-tool-tasks list` via Bash (this triggers auto-registration).
