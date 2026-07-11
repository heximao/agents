---
name: lark-cli
description: "Integrate Feishu/Lark CLI (lark-cli) with Hermes Agent — direct CLI usage and MCP server integration for Docs, Base, Calendar, Mail, Messenger, and more."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lark, feishu, mcp, cli, productivity, integration]
    related_skills: [native-mcp, lark-mail]
---

# Lark CLI Integration

Lark CLI (`@larksuite/cli`) is the official Feishu/Lark command-line tool with 200+ commands covering Messenger, Docs, Base, Sheets, Slides, Calendar, Mail, Tasks, Meetings, and more. It also provides 26 AI Agent Skills.

There are two integration paths: **direct CLI** (use lark-cli commands via `terminal`) and **MCP server** (expose lark tools as first-class Hermes tools).

## Quick Decision Guide

| Need | Approach |
|------|----------|
| Occasional lark commands in conversation | Direct CLI install |
| Lark tools always available as native Hermes tools | MCP server |
| Already have lark-cli on host, just want Hermes to use it | Direct CLI install in container |

## Approach 1: Direct CLI Installation

Install inside the Hermes container/environment:

```bash
npm install -g @larksuite/cli
```

Then use via `terminal` tool:
```bash
lark-cli --version
lark-cli docs list
lark-cli messenger send --to <chat_id> --text "hello"
```

**Authentication:** Run `lark-cli login` to authenticate with a Feishu account (user identity). For app identity, set `LARK_APP_ID` and `LARK_APP_SECRET` environment variables.

**When host already has lark-cli:** If the host machine has lark-cli installed but the container doesn't, the simplest fix is `npm install -g @larksuite/cli` inside the container. Mounting host binaries is fragile (Go binary + dependency paths).

## Approach 2: MCP Server Integration

The official `@larksuiteoapi/lark-mcp` package exposes Lark APIs as MCP tools.

### Install

```bash
npm install -g @larksuiteoapi/lark-mcp
```

### Configure in Hermes

Add to `~/.hermes/config.yaml` (or `$HERMES_HOME/config.yaml`):

```yaml
mcp_servers:
  lark:
    command: "lark-mcp"
    args: ["mcp"]
    env:
      LARK_APP_ID: "cli_aXXXXXXXXXXXXXXXX"
      LARK_APP_SECRET: "XXXXXXXXXXXXXXXXXXXXXXXX"
    timeout: 120
```

For user identity (OAuth), run `lark-mcp login` first, then omit `LARK_APP_ID`/`LARK_APP_SECRET` from env.

For the international Lark (not Feishu), add `--domain lark` to args:
```yaml
    args: ["mcp", "--domain", "lark"]
```

To enable specific API presets only, use `-t`:
```yaml
    args: ["mcp", "-t", "messenger,docs,base"]
```

### After Configuration

Restart Hermes Agent. MCP tools appear as `mcp_lark_*` (e.g., `mcp_lark_send_message`, `mcp_lark_create_doc`).

## Prerequisites

- **Node.js** — required for both approaches
- **Feishu/Lark App** — create at [Feishu Open Platform](https://open.feishu.cn) for app identity auth
- **mcp Python package** — needed for MCP approach only: `pip install mcp`

## Pitfalls

1. **`npm install -g` permission errors**: Use `sudo npm install -g @larksuite/cli` or configure npm global prefix to a user-writable directory.
2. **`ignore-scripts=true`**: lark-cli's npm package uses `postinstall` to download the Go binary. If `npm config set ignore-scripts true` is set, the install succeeds but the CLI is unusable. Either unset it or install with `npm install -g @larksuite/cli --ignore-scripts=false`.
3. **MCP tools not appearing**: Ensure `mcp_servers` (not `mcp` or `servers`) key is used in config.yaml. Check startup logs for connection errors. Restart Hermes after config changes.
4. **Feishu vs Lark domain**: Default is Feishu (China). Add `--domain lark` for international Lark.
5. **App permissions**: The Feishu app needs appropriate permission scopes enabled. Bulk-enable required scopes via the Feishu Open Platform console before first use.
