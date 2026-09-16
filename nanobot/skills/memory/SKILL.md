---
name: memory
description: Two-layer memory system with rg-based recall.
---

# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with rg.

## Search Past Events

```powershell
rg -i "keyword" memory/HISTORY.md
```

Use the `exec_command` tool to run rg. Combine patterns: `rg -i "meeting|deadline" memory/HISTORY.md`

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")
