---
name: claude-code-config
description: "Claude Code configuration: CLAUDE.md hierarchy, loading rules, limits, .claude directory structure, Cowork features. Use when user asks about Claude Code setup, CLAUDE.md behavior, memory system, or Desktop Cowork."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [claude-code, configuration, claude-md, memory, cow]
---

# Claude Code Configuration Reference

## CLAUDE.md Loading Hierarchy

Claude Code loads CLAUDE.md files **in both directions** from the current working directory:

### Upward (parent directories) — auto-loaded at session start
Traverses from cwd up to root, collecting all CLAUDE.md files:

| Path | Scope |
|------|-------|
| `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS) | Organization-wide (IT managed) |
| `/etc/claude-code/CLAUDE.md` (Linux/WSL) | Organization-wide |
| `~/.claude/CLAUDE.md` | **Global personal** (all projects) |
| `~/a/CLAUDE.md` | Parent directory |
| `~/a/b/CLAUDE.md` | Current working directory |

**Example:** Starting in `~/a/b/` loads: `~/.claude/CLAUDE.md` → `~/CLAUDE.md` → `~/a/CLAUDE.md` → `~/a/b/CLAUDE.md`

### Downward (subdirectories) — loaded on access
Subdirectory CLAUDE.md files are designed to load **on demand** when Claude reads files in that directory. However, this has known bugs (GitHub #2571, #18098) — subdirectory CLAUDE.md files may not reliably load.

**Workaround:** cd into the subdirectory before starting Claude Code.

### Priority (nearest wins)
```
.claude/settings.local.json > project CLAUDE.md > ~/.claude/CLAUDE.md
```

## CLAUDE.md Size Limit

- **200 lines maximum** (recommended by Anthropic)
- Lines beyond 200 are **silently truncated**
- MEMORY.md also has 200-line hard limit
- Over 200 lines → Claude may ignore half the content
- Keep it concise; split into subdirectory CLAUDE.md files or use `.claude/rules/`

## Other Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `CLAUDE.local.md` | Project root | Private preferences (gitignored) |
| `settings.json` | `.claude/` or `~/.claude/` | Hooks, env vars, permissions |
| `settings.local.json` | `.claude/` | Personal overrides (gitignored) |
| `MEMORY.md` | `~/.claude/` | Auto memory (200 line limit) |
| `skills/<name>/SKILL.md` | `.claude/` or `~/.claude/` | Custom slash commands |
| `rules/` | `.claude/` | Rule files with optional path filters |

## Claude Desktop Cowork

Desktop AI assistant built into Claude Desktop app:

| Feature | Description |
|---------|-------------|
| File system access | Read/write files in sandboxed environment |
| Document processing | Process and organize documents |
| Multi-step workflows | Execute complex automation tasks |
| Desktop automation | Computer Use API (screenshots, clicks, UI navigation) |
| **Scheduled Tasks** | Time-triggered and event-driven automation |

### Cowork vs Claude Code

| | Cowork | Claude Code |
|-|--------|-------------|
| Setup | Zero (built into Desktop) | Requires installation |
| Target | Non-developers | Developers / Power Users |
| Precision | Basic | Higher |
| Extensibility | Limited | High |
| Automation | GUI Scheduled Tasks | CLI cron, `/loop` skill |

### Cowork Scheduled Tasks
- Time-triggered: run on schedule (e.g., daily at 9am)
- Event-triggered: run when conditions met
- Accesses files, skills, Chrome extension
- Runs in Claude Desktop app (sandboxed)

## Pitfalls

- `~/CLAUDE.md` ≠ `~/.claude/CLAUDE.md` — global config lives in `.claude/` directory
- Subdirectory CLAUDE.md loading is unreliable due to known bugs — verify with `/memory` command
- 200-line limit is enforced silently — no warning when truncated
