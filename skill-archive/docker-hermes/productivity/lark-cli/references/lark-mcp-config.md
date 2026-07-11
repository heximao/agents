# Lark MCP Advanced Configuration

## Command Parameters

`lark-mcp` supports these key flags:

| Flag | Description |
|------|-------------|
| `mcp` | Start MCP server (stdio transport) |
| `login` | OAuth login for user identity |
| `-V` | Show version |
| `--domain lark` | Use international Lark instead of Feishu |
| `-t <tools>` | Enable specific API presets (comma-separated) |

## Default Enabled APIs

By default, lark-mcp enables common APIs. To see available presets:
```bash
lark-mcp mcp --help
```

## MCP Client Configuration Examples

### Stdio (most common)
```json
{
  "mcpServers": {
    "lark": {
      "command": "lark-mcp",
      "args": ["mcp"],
      "env": {
        "LARK_APP_ID": "cli_xxx",
        "LARK_APP_SECRET": "xxx"
      }
    }
  }
}
```

### With specific tools
```json
{
  "mcpServers": {
    "lark": {
      "command": "lark-mcp",
      "args": ["mcp", "-t", "messenger,docs,base,sheets,calendar"]
    }
  }
}
```

## Capability Matrix

| Domain | Capabilities |
|--------|-------------|
| Messenger | Send/reply messages, manage group chats, view history, search, download media |
| Docs | Create, read, update, search documents, media & whiteboards |
| Drive | Upload/download files, search docs & wiki, manage comments |
| Sheets | Manage data tables, fields, records, views, dashboards, automation |
| Slides | Create/manage presentations, read content, add/remove slides |
| Calendar | Create/query/update events, manage calendars |
| Mail | Search, read, draft, send, reply, forward, archive emails |
| Tasks | Create/query/update/complete tasks, manage task lists, subtasks |
| Meetings | Search meetings, get transcripts |
| Base | Manage Base apps, tables, records |

## References

- [Lark CLI GitHub](https://github.com/larksuite/cli)
- [Lark OpenAPI MCP GitHub](https://github.com/larksuite/lark-openapi-mcp)
- [Feishu Open Platform Docs](https://open.feishu.cn)
