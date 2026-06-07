---
name: heximao-multi-profile
description: "Manage multiple Hermes profiles — batch startup, routing rules placement, context file loading priority, and cross-profile conflict resolution."
version: 1.0.0
author: heximao
metadata:
  hermes:
    tags: [hermes, profiles, multi-agent, gateway, orchestration]
    related_skills: [hermes-agent, kanban-orchestrator, kanban-worker]
---

# Hermes Multi-Profile Management

Operational guide for running, routing, and coordinating multiple Hermes profiles on a single host.

## Context File Loading Priority

When Hermes starts, it loads project context from the cwd. The priority is **first found wins** — only ONE project context type is loaded:

| Priority | File | Scope | Walks up? |
|----------|------|-------|-----------|
| 1 | `HERMES.md` / `.hermes.md` | Hermes-native | Yes — walks to git root |
| 2 | `AGENTS.md` / `agents.md` | Cursor/AGENTS standard | No — cwd only |
| 3 | `CLAUDE.md` / `claude.md` | Claude Code standard | No — cwd only |
| 4 | `.cursorrules` / `.cursor/rules/*.mdc` | Cursor | No — cwd only |

**Always loaded (independent of above):**
- `SOUL.md` from `$HERMES_HOME` — loaded regardless of cwd, always present in system prompt.

**Key insight for routing rules:** If you need rules to be present regardless of which project directory the agent starts from, write them to `SOUL.md` in the profile's `~/.hermes/profiles/<name>/SOUL.md`. CLAUDE.md only loads when the agent starts from that specific directory.

Source: `agent/prompt_builder.py::build_context_files_prompt()` and `_load_claude_md()`.

## Where to Put Cross-Profile Routing Rules

When a coordinator profile needs to know which profile handles what:

| Target | File | Pros | Cons |
|--------|------|------|------|
| Coordinator only, any cwd | `~/.hermes/profiles/<coordinator>/SOUL.md` | Always loaded, profile-scoped | Shares space with identity |
| Coordinator only, specific project | `~/project/CLAUDE.md` | Clean separation | Only loads from that cwd |
| All profiles | `~/.hermes/CLAUDE.md` | Universal | Wastes tokens on unrelated agents |

**Recommended:** Put routing rules in the coordinator's `SOUL.md`. It's the only file guaranteed to load regardless of cwd.

## Batch Gateway Startup

### Start a Single Profile
```bash
hermes gateway start --profile <name>
```

### Start All Profiles
```bash
for p in $(hermes profile list 2>&1 | awk 'NR>2 && $1 !~ /◆/ {print $1}'); do
  echo "Starting $p..."
  hermes gateway start --profile "$p" 2>&1 | tail -1
  sleep 2
done
```

### Check All Profile Status
```bash
hermes profile list
```

The `◆` marker indicates the current active profile (the one running the CLI session). It doesn't need a gateway.

### Start Missing Profiles Only
```bash
hermes profile list 2>&1 | grep "stopped" | awk '{print $1}' | while read p; do
  hermes gateway start --profile "$p" 2>&1
  sleep 2
done
```

## Profile Naming Conventions

For domain-specific agent teams, use a `<domain>-<role>` pattern:

| Pattern | Example | Purpose |
|---------|---------|---------|
| `<domain>-topic-master` | `finance-topic-master`, `ai-topic-master` | Topic screening per domain |
| `topic-master` | `topic-master` | Generic fallback topic screening |
| `writer-<style>` | `writer-jinjiancheng`, `writer-xiajie` | Writing in specific styles |
| `<domain>-kanban` | `investment-kanban`, `knowledge-kanban` | Kanban workers for domain |

### Routing Between Topic Masters

When a coordinator routes topic-screening requests:

```
AI/ML keywords → ai-topic-master
Finance keywords → finance-topic-master
Everything else → topic-master (generic fallback)
Uncertain → ask the user, don't guess
```

## Pitfalls

### Feishu App ID Conflict
Multiple profiles **cannot** share the same Feishu `app_id`. If two profiles both configure Feishu with the same app, the second one will crash on startup:

```
ERROR: Another local Hermes gateway is already using this Feishu app_id (PID NNNN)
```

**Fix:** Either:
1. Give each Feishu-using profile its own `app_id`
2. Disable Feishu on profiles that don't need it
3. Use only one profile for Feishu messaging

### Profile list shows stopped but gateway status shows running
`hermes profile list` checks the pid file in the profile directory. `hermes gateway status --profile <name>` checks the actual launchd service. If they disagree, trust `gateway status`.

### Default profile CAN have a gateway
The `◆default` profile is the current interactive CLI session. It can also have a gateway running simultaneously for messaging platforms — they are independent processes. If default has no messaging platforms configured, starting its gateway is harmless but useless (it will log "No messaging platforms enabled" and sit idle).

### Cleaning up old launchd plists kills running services
On macOS, gateway services are managed via `~/Library/LaunchAgents/ai.hermes.gateway-<profile>.plist`. If you delete old-format plists (e.g. dot-separated `ai.hermes.gateway.profilename.plist`) while their services are running, the services will be unloaded and stopped. **Always check what's running before deleting plists.**

```bash
# Step 1: List all plists
ls ~/Library/LaunchAgents/ai.hermes.gateway*.plist

# Step 2: Unload OLD ones first (this stops them)
launchctl bootout gui/$(id -u)/<old-label>

# Step 3: Delete old plist files
rm ~/Library/LaunchAgents/<old-plist>.plist

# Step 4: Create NEW plists for any profiles that lost theirs
# (copy from a working template, change profile name and HERMES_HOME)

# Step 5: Load and start
hermes gateway start --profile <name>
```

## macOS launchd Plist Management

Each profile's gateway runs as a launchd user agent. The plist files live at:
```
~/Library/LaunchAgents/ai.hermes.gateway-<profile>.plist
```

### Naming Convention
Use **hyphen-separated**: `ai.hermes.gateway-<profile>.plist`
Historical versions used dot-separated (`ai.hermes.gateway.profilename.plist`) — these are deprecated.

### Key Plist Settings
| Key | Value | Purpose |
|-----|-------|---------|
| `RunAtLoad` | `true` | Auto-start on login |
| `KeepAlive.SuccessfulExit` | `false` | Restart on crash, not on clean exit |
| `HERMES_HOME` env var | `/Users/.../profiles/<name>` | Isolates profile state |
| `ProgramArguments` | `--profile <name>` | Routes to correct profile |

### Create a Missing Plist
```bash
# Copy from an existing working plist, then edit:
cp ~/Library/LaunchAgents/ai.hermes.gateway-analyst.plist \
   ~/Library/LaunchAgents/ai.hermes.gateway-<new-profile>.plist

# Edit: change Label, --profile arg, HERMES_HOME, WorkingDirectory, log paths
```

### Verify Auto-Start Config
```bash
for f in ~/Library/LaunchAgents/ai.hermes.gateway-*.plist; do
  name=$(basename "$f" .plist)
  autoload=$(/usr/libexec/PlistBuddy -c "Print :RunAtLoad" "$f" 2>/dev/null || echo "not set")
  disabled=$(/usr/libexec/PlistBuddy -c "Print :Disabled" "$f" 2>/dev/null || echo "false")
  echo "$name: RunAtLoad=$autoload Disabled=$disabled"
done
```

## Quick Reference

```bash
# Create a new profile
hermes profile create <name> --clone <source>

# List all profiles with models and gateway status
hermes profile list

# Start/stop a specific profile's gateway
hermes gateway start --profile <name>
hermes gateway stop --profile <name>

# Restart a profile's gateway
hermes gateway restart --profile <name>

# Check gateway logs for a profile
tail -20 ~/.hermes/profiles/<name>/logs/gateway.log
tail -20 ~/.hermes/profiles/<name>/logs/gateway.error.log
```
