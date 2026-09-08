---
name: debugging
description: "Debug anything: systematic methodology + Python (pdb/debugpy) and Node.js (inspect/CDP) tool guides."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, troubleshooting, root-cause, python, pdb, debugpy, nodejs, node-inspect, cdp, breakpoints, dap]
    related_skills: [test-driven-development, plan, subagent-driven-development]
---

# Debugging

Three layers — use the right one for the situation:

| Layer | What | When |
|-------|------|------|
| **Methodology** (below) | 4-phase root cause investigation | ANY technical issue — always start here |
| **Python debugging** | pdb, debugpy, remote-pdb | Python code needs breakpoints/stepping |
| **Node.js debugging** | node inspect, CDP | Node/TS code needs breakpoints/stepping |

**The Iron Law: NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

---

## Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

### 1. Read Error Messages Carefully
- Don't skip past errors or warnings
- Read stack traces completely — note line numbers, file paths, error codes
- Use `read_file` on relevant source files, `search_files` to find the error string

### 2. Reproduce Consistently
- Can you trigger it reliably? What are the exact steps?
- If not reproducible → gather more data, don't guess

### 3. Check Recent Changes
```bash
git log --oneline -10
git diff
git log -p --follow src/problematic_file.py | head -100
```

### 4. Gather Evidence in Multi-Component Systems
For EACH component boundary: log what data enters/exits, verify config propagation, check state at each layer. Run once to gather evidence, THEN identify the failing component.

### 5. Trace Data Flow
Where does the bad value originate? Keep tracing upstream until you find the source. Fix at the source, not the symptom.

```python
search_files("function_name(", path="src/", file_glob="*.py")
search_files("variable_name\\s*=", path="src/", file_glob="*.py")
```

### Phase 1 Completion
- [ ] Error messages fully read and understood
- [ ] Issue reproduced consistently
- [ ] Recent changes identified
- [ ] Evidence gathered (logs, state, data flow)
- [ ] Root cause hypothesis formed

**STOP: Do not proceed until you understand WHY it's happening.**

---

## Phase 2: Pattern Analysis

1. **Find working examples** — similar working code in the same codebase
2. **Compare against references** — read the reference implementation COMPLETELY
3. **Identify differences** — list every difference, however small
4. **Understand dependencies** — what other components does this need?

---

## Phase 3: Hypothesis and Testing

1. **Form a single hypothesis** — "I think X is the root cause because Y"
2. **Test minimally** — smallest possible change, one variable at a time
3. **Verify** — did it work? → Phase 4. Didn't? → new hypothesis. DON'T add more fixes on top.

---

## Phase 4: Implementation

1. **Create failing test case** — simplest possible reproduction
2. **Implement single fix** — address root cause, ONE change at a time
3. **Verify fix** — run specific test + full suite

### The Rule of Three
- < 3 fixes tried: return to Phase 1 with new information
- **≥ 3 fixes tried: STOP and question the architecture**
- Each fix reveals new shared state/coupling? → architectural problem
- Discuss with user before attempting more fixes

---

## Red Flags — STOP and Follow Process

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "It's probably X, let me fix that"
- Proposing solutions before tracing data flow
- "One more fix attempt" (when already tried 2+)

**ALL of these mean: STOP. Return to Phase 1.**

---

## Hermes Integration

### Investigation Tools
- **`search_files`** — find error strings, trace function calls, locate patterns
- **`read_file`** — read source code with line numbers
- **`terminal`** — run tests, check git history, reproduce bugs
- **`web_search`/`web_extract`** — research error messages, library docs

### With delegate_task
```python
delegate_task(
    goal="Investigate why [specific test/behavior] fails",
    context="""
    Follow debugging skill Phase 1:
    1. Read the error message carefully
    2. Reproduce the issue
    3. Trace the data flow to find root cause
    4. Report findings — do NOT fix yet
    Error: [paste full error]
    File: [path to failing code]
    """,
    toolsets=['terminal', 'file']
)
```

---

## Python Debugging

Three tools, pick by situation:

| Tool | When |
|------|------|
| **`breakpoint()` + pdb** | Local, interactive, simplest |
| **`python -m pdb`** | Launch script under pdb, no source edits |
| **`debugpy`** | Remote/headless/attach to running process |

**Start with `breakpoint()`.** It's the cheapest thing that works.

For full Python debugging details, see: `skill_view(name="debugging", file_path="references/python-debugging.md")`

### Quick pdb Reference

| Command | Action |
|---------|--------|
| `n` | next line (step over) |
| `s` | step into |
| `r` | return from current function |
| `c` | continue |
| `l` / `ll` | list source / full function |
| `w` | where (stack trace) |
| `u` / `d` | move up / down in stack |
| `p expr` / `pp expr` | print / pretty-print |
| `b file:line` | set breakpoint |
| `b func` | break on function entry |
| `cl N` | clear breakpoint N |
| `!stmt` | execute arbitrary Python |
| `interact` | full Python REPL in current scope |
| `q` | quit |

### Recipe: Local breakpoint
```python
def compute(x, y):
    result = some_helper(x)
    breakpoint()           # drops into pdb here
    return result + y
```
**Remove before committing:** `rg -n 'breakpoint\(\)' --type py`

### Recipe: Debug pytest
```bash
pytest tests/test.py::test_name --pdb -p no:xdist  # pdb on failure
# xdist doesn't work with pdb — always add -p no:xdist or -n 0
```

### Recipe: Post-mortem
```python
import pdb, sys
try:
    run_the_thing()
except Exception:
    pdb.post_mortem(sys.exc_info()[2])
```

### Recipe: Remote debug with debugpy
```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
# Attach from terminal: nc 127.0.0.1 5678 (via remote-pdb)
# Or from VS Code launch.json
```

### Python Pitfalls
1. pdb under pytest-xdist silently does nothing — use `-p no:xdist`
2. `breakpoint()` in CI/non-TTY hangs — safe locally, never commit
3. `PYTHONBREAKPOINT=0` disables all breakpoints
4. debugpy attach to PID fails on hardened kernels (`ptrace_scope=1`)
5. pdb doesn't follow forks — each child needs its own breakpoint

---

## Node.js Debugging

Two tools, pick one:

| Tool | When |
|------|------|
| **`node inspect`** | Built-in, zero install, CLI REPL |
| **CDP via `chrome-remote-interface`** | Scriptable, automated breakpoints |

**Prefer `node inspect` first.** Always available, REPL is fast.

For full Node.js debugging details, see: `skill_view(name="debugging", file_path="references/node-debugging.md")`

### Quick `node inspect` Reference

```bash
node inspect path/to/script.js              # paused on first line
node --inspect-brk script.js                # with inspector, paused
node --inspect-brk $(which tsx) script.ts   # TypeScript
```

| Command | Action |
|---------|--------|
| `c` / `cont` | continue |
| `n` / `next` | step over |
| `s` / `step` | step into |
| `o` / `out` | step out |
| `pause` | pause running code |
| `sb('file.js', 42)` | set breakpoint |
| `cb('file.js', 42)` | clear breakpoint |
| `bt` | backtrace |
| `list(5)` | show source around position |
| `repl` | REPL in current scope |
| `exec expr` | evaluate expression |

### Attaching to Running Process
```bash
kill -SIGUSR1 <pid>                    # enable inspector
node inspect -p <pid>                  # attach CLI
# or
curl -s http://127.0.0.1:9229/json/list | jq -r '.[0].webSocketDebuggerUrl'
node inspect ws://127.0.0.1:9229/<uuid>
```

### Node Pitfalls
1. `--inspect` vs `--inspect-brk` — use `-brk` to set breakpoints before code runs
2. Default port 9229 — use `--inspect=0` for random port if multiple processes
3. Breakpoints hit emitted JS, not `.ts` — use `--enable-source-maps` or break in `dist/`
4. `--inspect` on parent does NOT inspect children — use `NODE_OPTIONS='--inspect-brk'`
5. Background kills: if you Ctrl+C `node inspect` while target is paused, target stays paused
