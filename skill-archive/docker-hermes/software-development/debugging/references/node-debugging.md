# Node.js Debugging — Full Reference

## Tool Selection

| Tool | When |
|------|------|
| **`node inspect`** | Built-in, zero install, CLI REPL. Best for quick poking. |
| **CDP via `chrome-remote-interface`** | Scriptable from Node/Python; automated breakpoints, scope capture. |

**Prefer `node inspect` first.** Always available, REPL is fast.

## `node inspect` Full Reference

Launch paused on first line:
```bash
node inspect path/to/script.js
node --inspect-brk $(which tsx) path/to/script.ts  # TypeScript
```

| Command | Action |
|---------|--------|
| `c` / `cont` | continue |
| `n` / `next` | step over |
| `s` / `step` | step into |
| `o` / `out` | step out |
| `pause` | pause running code |
| `sb('file.js', 42)` | set breakpoint at file.js line 42 |
| `sb(42)` | set breakpoint at line 42 of current file |
| `sb('functionName')` | break when function is called |
| `cb('file.js', 42)` | clear breakpoint |
| `breakpoints` | list all breakpoints |
| `bt` | backtrace (call stack) |
| `list(5)` | show 5 lines of source around current position |
| `watch('expr')` | evaluate expr on every pause |
| `watchers` | show watched expressions |
| `repl` | drop into REPL in current scope (Ctrl+C to exit REPL) |
| `exec expr` | evaluate expression once |
| `restart` | restart script |
| `kill` | kill the script |
| `.exit` | quit debugger |

## Attaching to a Running Process

```bash
# 1. Send SIGUSR1 to enable inspector on existing process
kill -SIGUSR1 <pid>
# Node prints: Debugger listening on ws://127.0.0.1:9229/<uuid>

# 2. Attach
node inspect -p <pid>
# or by URL
node inspect ws://127.0.0.1:9229/<uuid>
```

Start with inspector from beginning:
```bash
node --inspect script.js           # listen, keep running
node --inspect-brk script.js       # listen AND pause on first line
node --inspect=0.0.0.0:9230 script.js  # custom host:port
```

## Programmatic CDP (Scripting)

When you want to automate — set many breakpoints, capture scope state, script a repro:

```bash
npm i -g chrome-remote-interface
node --inspect-brk=9229 target.js &
```

Driver script:
```javascript
const CDP = require('chrome-remote-interface');

(async () => {
  const client = await CDP({ port: 9229 });
  const { Debugger, Runtime } = client;

  Debugger.paused(async ({ callFrames, reason }) => {
    const top = callFrames[0];
    console.log(`PAUSED: ${reason} @ ${top.url}:${top.location.lineNumber + 1}`);

    // Walk scopes for locals
    for (const scope of top.scopeChain) {
      if (scope.type === 'local' || scope.type === 'closure') {
        const { result } = await Runtime.getProperties({
          objectId: scope.object.objectId,
          ownProperties: true,
        });
        for (const p of result) {
          console.log(`  ${scope.type}.${p.name} =`, p.value?.value ?? p.value?.description);
        }
      }
    }

    // Evaluate in paused frame
    const { result } = await Debugger.evaluateOnCallFrame({
      callFrameId: top.callFrameId,
      expression: 'typeof state !== "undefined" ? JSON.stringify(state) : "n/a"',
    });
    console.log('state =', result.value ?? result.description);

    await Debugger.resume();
  });

  await Runtime.enable();
  await Debugger.enable();

  await Debugger.setBreakpointByUrl({
    urlRegex: '.*app\\.tsx$',
    lineNumber: 119,  // 0-indexed
  });

  await Runtime.runIfWaitingForDebugger();
})();
```

## Debugging Hermes ui-tui

### Single Ink component under dev
```bash
cd ui-tui
npm run build
node --inspect-brk dist/entry.js
# In another terminal:
node inspect -p <node pid>
sb('dist/app.js', 220)
cont
```

### Running `hermes --tui`
```bash
hermes --tui &
TUI_PID=$(pgrep -f 'ui-tui/dist/entry' | head -1)
kill -SIGUSR1 "$TUI_PID"
curl -s http://127.0.0.1:9229/json/list | jq -r '.[0].webSocketDebuggerUrl'
node inspect ws://127.0.0.1:9229/<uuid>
```

## Running Vitest Tests Under Debugger

```bash
cd ui-tui
node --inspect-brk ./node_modules/vitest/vitest.mjs run --no-file-parallelism src/app/foo.test.tsx
# In another terminal: node inspect -p <pid>, then sb(...), cont
```

## Heap Snapshots & CPU Profiles

```javascript
// CPU profile for 5 seconds
await client.Profiler.enable();
await client.Profiler.start();
await new Promise(r => setTimeout(r, 5000));
const { profile } = await client.Profiler.stop();
require('fs').writeFileSync('/tmp/cpu.cpuprofile', JSON.stringify(profile));

// Heap snapshot
await client.HeapProfiler.enable();
const chunks = [];
client.HeapProfiler.addHeapSnapshotChunk(({ chunk }) => chunks.push(chunk));
await client.HeapProfiler.takeHeapSnapshot({ reportProgress: false });
require('fs').writeFileSync('/tmp/heap.heapsnapshot', chunks.join(''));
```

## Common Pitfalls

1. **Wrong line numbers in TS source.** Breakpoints hit emitted JS. Use `--enable-source-maps` or break in `dist/`.
2. **`--inspect` vs `--inspect-brk`.** Use `--inspect-brk` to set breakpoints before code runs.
3. **Port collisions.** Default 9229. Use `--inspect=0` for random port, read from `/json/list`.
4. **Child processes.** `--inspect` on parent does NOT inspect children. Use `NODE_OPTIONS='--inspect-brk'`.
5. **Background kills.** Ctrl+C out of `node inspect` while target is paused → target stays paused. `cont` first.
6. **Security.** `--inspect=0.0.0.0:9229` exposes arbitrary code execution. Always bind to 127.0.0.1.
