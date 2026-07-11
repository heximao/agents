---
name: coding-agents
description: "Delegate coding to external AI agent CLIs: Claude Code, Codex, OpenCode."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Claude, Codex, OpenCode, Anthropic, OpenAI, Autonomous, Code-Review, Refactoring, PTY, Automation]
    related_skills: [hermes-agent, kanban-orchestrator, kanban-worker]
---

# Coding Agents — Hermes Orchestration Guide

Delegate coding tasks to external AI coding agent CLIs via Hermes terminal. Three agents are supported — pick based on availability and task needs.

## Which Agent to Use

| Agent | Provider | Best for | Auth |
|-------|----------|----------|------|
| **Claude Code** | Anthropic | Complex multi-file refactors, PR review, structured extraction | OAuth or `ANTHROPIC_API_KEY` |
| **Codex** | OpenAI | One-shot features, batch issue fixing, parallel worktrees | `OPENAI_API_KEY` or Codex OAuth |
| **OpenCode** | Provider-agnostic | Provider-agnostic tasks, long sessions, when you want model choice | `opencode auth login` or provider env vars |

**Decision flow:**
1. User specifies an agent → use that one
2. Need structured JSON output or session resumption → **Claude Code** (best `-p` mode)
3. Need parallel worktrees on a budget → **Codex** (`--yolo` + worktrees)
4. Need provider flexibility or open-source → **OpenCode**
5. All three available → **Claude Code** for quality, **Codex** for speed

## Shared Orchestration Pattern

All three agents follow the same workflow when orchestrated by Hermes:

```
1. Verify tool installed + authenticated
2. Choose one-shot vs interactive mode
3. Launch (foreground for short, background for long)
4. Monitor progress
5. Report results
```

### One-Shot (Print/Exec Mode) — Preferred

Best for bounded tasks. Runs, returns result, exits. No PTY interaction needed.

```bash
# Claude Code
claude -p 'Add error handling to all API calls in src/' --max-turns 10

# Codex
codex exec 'Add dark mode toggle to settings'

# OpenCode
opencode run 'Add retry logic to API calls and update tests'
```

### Interactive (Background PTY) — For Iterative Work

Best when you need multi-turn conversation, follow-up prompts, or real-time monitoring.

```bash
# Claude Code (requires tmux)
tmux new-session -d -s claude-work -x 140 -y 40
tmux send-keys -t claude-work 'cd /path/to/project && claude' Enter
sleep 5 && tmux send-keys -t claude-work 'Your task here' Enter

# Codex
codex exec --full-auto 'Refactor the auth module'  # background=true, pty=true

# OpenCode
opencode  # background=true, pty=true
# Then: process(action="submit", data="Your task")
```

### PR Review

```bash
# Claude Code (print mode — cleanest)
git diff main...feature-branch | claude -p 'Review this diff for bugs and security issues' --max-turns 1

# Claude Code (from PR number)
claude -p 'Review this PR thoroughly' --from-pr 42 --max-turns 10

# Codex
codex review --base origin/main

# OpenCode
opencode pr 42
```

### Parallel Tasks

Use separate workdirs/worktrees to avoid collisions:

```bash
# Worktree pattern (all agents)
git worktree add -b fix/issue-78 /tmp/issue-78 main
git worktree add -b fix/issue-99 /tmp/issue-99 main

# Launch in parallel
# (agent-specific commands in their sections below)
```

## Agent-Specific Details

For detailed flags, configuration, and pitfalls for each agent, load the reference:

```
skill_view(name="coding-agents", file_path="references/claude-code.md")
skill_view(name="coding-agents", file_path="references/codex.md")
skill_view(name="coding-agents", file_path="references/opencode.md")
```

---

# Claude Code (Anthropic)

## Prerequisites

- **Install:** `npm install -g @anthropic-ai/claude-code`
- **Auth:** `claude` once (browser OAuth), or `ANTHROPIC_API_KEY`, or `claude auth login --console`
- **Version:** `claude --version` (requires v2.x+)
- **Update:** `claude update`

## Key Flags

| Flag | Effect |
|------|--------|
| `-p, --print` | Non-interactive one-shot (exits when done) |
| `--max-turns <n>` | Limit agentic loops (print mode only) |
| `--max-budget-usd <n>` | Cap API spend |
| `--model <alias>` | `sonnet`, `opus`, `haiku`, or full name |
| `--effort <level>` | `low`, `medium`, `high`, `max`, `auto` |
| `--allowedTools <tools>` | Whitelist specific tools |
| `--dangerously-skip-permissions` | Auto-approve all tool use |
| `--output-format json` | Structured JSON output |
| `--json-schema <schema>` | Force structured output matching schema |
| `--bare` | Skip hooks, plugins, MCP, OAuth (fastest startup) |
| `-c, --continue` | Resume most recent conversation |
| `-r, --resume <id>` | Resume specific session |
| `--from-pr <number>` | Resume session linked to a PR |

## PTY Dialog Handling (Interactive Mode)

Claude Code presents confirmation dialogs on first launch:

**Dialog 1: Workspace Trust** — just press Enter (default "Yes")
**Dialog 2: Bypass Permissions** — must press Down then Enter ("Yes, I accept" is NOT the default)

```bash
tmux send-keys -t session Enter              # Trust dialog
sleep 3 && tmux send-keys -t session Down && sleep 0.3 && tmux send-keys -t session Enter  # Permissions dialog
```

## Structured JSON Output

```bash
claude -p 'Analyze auth.py' --output-format json --max-turns 5
# Returns: { "result": "...", "session_id": "...", "total_cost_usd": 0.07, ... }
```

## Pitfalls

- Interactive mode REQUIRES tmux (Claude Code is a TUI app)
- `--dangerously-skip-permissions` dialog defaults to "No, exit" — must navigate DOWN first
- `--max-budget-usd` minimum ~$0.05 (system prompt cache costs this)
- `--max-turns` is print-mode only
- Session resumption requires same directory
- `--bare` skips OAuth — needs `ANTHROPIC_API_KEY`
- Context degradation above 70% window usage — monitor with `/compact`

---

# Codex (OpenAI)

## Prerequisites

- **Install:** `npm install -g @openai/codex`
- **Auth:** `OPENAI_API_KEY` or Codex OAuth from login flow
- **Must run inside a git repository** — Codex refuses outside one
- **Use `pty=true`** — Codex is interactive, hangs without PTY

## Key Flags

| Flag | Effect |
|------|--------|
| `exec "prompt"` | One-shot execution, exits when done |
| `--full-auto` | Sandboxed, auto-approves file changes |
| `--yolo` | No sandbox, no approvals (fastest, most dangerous) |

## Usage Patterns

```bash
# One-shot
codex exec 'Add dark mode toggle to settings'

# Background long task
codex exec --full-auto 'Refactor the auth module'  # background=true, pty=true

# Scratch work (needs git repo)
cd $(mktemp -d) && git init && codex exec 'Build a snake game in Python'
```

## Pitfalls

- Always use `pty=true` — hangs without PTY
- Git repo required — use `mktemp -d && git init` for scratch
- Use `exec` for one-shots — exits cleanly
- `--full-auto` for building — auto-approves in sandbox

---

# OpenCode (Provider-Agnostic)

## Prerequisites

- **Install:** `npm i -g opencode-ai@latest` or `brew install anomalyco/tap/opencode`
- **Auth:** `opencode auth login` or set provider env vars
- **Verify:** `opencode auth list`

## Key Flags

| Flag | Effect |
|------|--------|
| `run 'prompt'` | One-shot execution and exit |
| `--continue` / `-c` | Continue last session |
| `--session <id>` / `-s` | Continue specific session |
| `--model provider/model` | Force specific model |
| `--thinking` | Show model thinking blocks |
| `--file <path>` / `-f` | Attach context files |

## Usage Patterns

```bash
# One-shot (no pty needed)
opencode run 'Add retry logic to API calls'

# Interactive background
opencode  # background=true, pty=true
# Then: process(action="submit", data="Your task")
# Exit: process(action="write", data="\x03") — NOT /exit

# PR review
opencode pr 42
```

## Pitfalls

- `opencode run` does NOT need pty; interactive `opencode` does
- `/exit` is NOT valid — opens agent selector. Use Ctrl+C or kill
- Enter may need pressing twice in TUI (once to finalize, once to send)
- PATH mismatch can select wrong binary — check `which -a opencode`

---

## Rules for All Agents

1. **Prefer one-shot mode** for single tasks — cleaner, no dialog handling
2. **Use interactive mode** only when iteration is needed
3. **Always set `workdir`** — keep the agent focused on the right project
4. **Set limits** (`--max-turns`, `--max-budget-usd`) — prevents runaway costs
5. **Monitor background sessions** — check progress before assuming failure
6. **Clean up tmux/process sessions** — kill when done
7. **Report concrete outcomes** — files changed, tests passed, remaining risks
8. **Use `--allowedTools`** — restrict to what the task needs
