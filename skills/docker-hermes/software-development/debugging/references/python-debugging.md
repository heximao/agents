# Python Debugging — Full Reference

## Tool Selection

| Tool | When |
|------|------|
| **`breakpoint()` + pdb** | Local, interactive, simplest. Add `breakpoint()` in source, run normally. |
| **`python -m pdb`** | Launch existing script under pdb with no source edits. |
| **`debugpy`** | Remote / headless / attach to already-running process. Talks DAP. |

## Full pdb Reference

| Command | Action |
|---------|--------|
| `h` / `h cmd` | help |
| `n` | next line (step over) |
| `s` | step into |
| `r` | return from current function |
| `c` | continue |
| `unt N` | continue until line N |
| `j N` | jump to line N (same function only) |
| `l` / `ll` | list source around current line / full function |
| `w` | where (stack trace) |
| `u` / `d` | move up / down in the stack |
| `a` | print args of the current function |
| `p expr` / `pp expr` | print / pretty-print expression |
| `display expr` | auto-print expr on every stop |
| `b file:line` | set breakpoint |
| `b func` | break on function entry |
| `b file:line, cond` | conditional breakpoint |
| `cl N` | clear breakpoint N |
| `tbreak file:line` | one-shot breakpoint |
| `!stmt` | execute arbitrary Python (assignments included) |
| `interact` | drop into full Python REPL in current scope (Ctrl+D to exit) |
| `q` | quit |

The `interact` command is the most powerful — you can import anything, inspect complex objects, even call methods that mutate state.

## Recipe: Launch a script under pdb (no source edits)

```bash
python -m pdb path/to/script.py arg1 arg2
# Lands at first line of script
(Pdb) b path/to/script.py:42
(Pdb) c
```

## Recipe: Post-mortem on any exception

```python
import pdb, sys
try:
    run_the_thing()
except Exception:
    pdb.post_mortem(sys.exc_info()[2])
```

Or wrap a whole script:
```bash
python -m pdb -c continue script.py
# When it crashes, pdb catches it and you're in the frame of the exception
```

Or set a global hook:
```python
import sys
def excepthook(etype, value, tb):
    import pdb; pdb.post_mortem(tb)
sys.excepthook = excepthook
```

## Recipe: Remote debug with debugpy

### Pattern A: Source-edit — process waits for debugger at launch

```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
print("debugpy listening on 5678, waiting for client...", flush=True)
debugpy.wait_for_client()
debugpy.breakpoint()  # optional: pause immediately once attached
```

### Pattern B: No source edit — launch with `-m debugpy`

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client your_script.py arg1
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client -m your.module
```

### Pattern C: Attach to an already-running process

```bash
python -m debugpy --listen 127.0.0.1:5678 --pid <pid>
# debugpy injects itself into the process
```

Some kernels block ptrace-based injection. Fix:
```bash
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope
```

### Remote-pdb (simpler alternative for terminal agents)

```bash
pip install remote-pdb
```

```python
from remote_pdb import set_trace
set_trace(host="127.0.0.1", port=4444)  # blocks until connection
```

Then: `nc 127.0.0.1 4444` — get a `(Pdb)` prompt exactly as if debugging locally.

## Debugging Hermes-specific Processes

### Tests
Always add `-p no:xdist` or run single tests without xdist.

### `run_agent.py` / CLI
Add `breakpoint()` near the suspect line, run `hermes` normally.

### `tui_gateway` subprocess
**A. Source-edit the gateway:**
```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
```

**B. Use `remote-pdb`:**
```python
from remote_pdb import set_trace
set_trace(host="127.0.0.1", port=4444)
```

### Gateway (`gateway/run.py`)
Long-lived. Use `remote-pdb` at a handler, or `debugpy` with `--wait-for-client` if restarting.

## Common Pitfalls

1. **pdb under pytest-xdist silently does nothing.** Always use `-p no:xdist` or `-n 0`.
2. **`breakpoint()` in CI / non-TTY contexts hangs.** Safe locally; never commit it.
3. **`PYTHONBREAKPOINT=0`** disables all `breakpoint()` calls.
4. **`debugpy.listen` blocks only if you also call `wait_for_client()`.**
5. **Attach to PID fails on hardened kernels.** `ptrace_scope=1` (Ubuntu default).
6. **Threads.** `pdb` only debugs current thread. For multithreaded code, use `debugpy`.
7. **asyncio.** `pdb` works in coroutines but `await` inside pdb requires Python 3.13+.
8. **`scripts/run_tests.sh` strips credentials.** If bug depends on user config, debug with raw `pytest` first.
9. **Forking / multiprocessing.** pdb does not follow forks. Each child needs its own breakpoint.

## One-Shot Recipes

**"Why is this dict missing a key?"**
```python
# add above the KeyError site
breakpoint()
# then in pdb:
(Pdb) pp d
(Pdb) pp list(d.keys())
(Pdb) w
```

**"This test passes in isolation but fails in the suite."**
```bash
source .venv/bin/activate
python -m pytest tests/ -x --pdb -p no:xdist
```

**"My async handler deadlocks."**
```python
import remote_pdb; remote_pdb.set_trace(host="127.0.0.1", port=4444)
```
Trigger the handler. `nc 127.0.0.1 4444`, then `w` to see the suspended frame.

**"Post-mortem on a crash in a subprocess."**
```bash
PYTHONFAULTHANDLER=1 python -m pdb -c continue path/to/entrypoint.py
```
