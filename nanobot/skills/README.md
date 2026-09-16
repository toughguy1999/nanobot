# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Loading

Main agents and subagents see only directory names and descriptions in their system
prompts. They call `load_skill(name)` to load the full body without frontmatter into
ordinary tool history. Workspace skills override same-named builtins. No skill body
is always injected; long-term memory loading remains independent.

The XML result includes the absolute directory and any missing declared commands or
environment variable names. Dependencies are checked on each load, without hiding
skills or preventing loading. Supporting resources are read separately as needed,
under existing file/shell permissions. Loading a builtin does not expand those permissions.

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `skill-creator` | Create new skills |
