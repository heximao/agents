# CLAUDE.md — 仓库维护指南

本文件指导 AI 和维护者如何管理此仓库。关于仓库介绍和使用方式，见 [README.md](./README.md)。

---

## 目录结构

| 目录 | 定义 | 说明 |
|------|------|------|
| `skill-archive/` | 所有 skill 的存档（唯一源） | 源文件只存在这里，其他位置都是符号链接 |
| `skills/` | 多 agent 兼容的用户级 skill 目录 | Codex、OpenCode 等支持此目录的 agent 可直接使用 |
| `~/.claude/skills/` | Claude 专用用户级 skill 目录 | 仅 Claude 使用的 skill 链接到这里 |
| `~/.codex/skills/` | Codex 专用用户级 skill 目录 | 仅 Codex 使用的 skill 链接到这里 |
| `~/.config/opencode/skills/` | OpenCode 专用用户级 skill 目录 | 仅 OpenCode 使用的 skill 链接到这里 |
| `~/.hermes/skills/` | Hermes 专用用户级 skill 目录 | 仅 Hermes 使用的 skill 链接到这里 |
| `<project>/.claude/skills/` | 项目级 skill 目录 | 仅某个项目使用的 skill 链接到这里 |

### Skill 归属判定

1. **多 agent 通用** → `skills/`（Codex、OpenCode 等都能用）
2. **某 agent 专用** → 对应 agent 的用户级 skill 目录（如 `~/.codex/skills/`）
3. **某项目专用** → 项目 `.claude/skills/`

## Skill 文件结构

```
skill-name/
├── SKILL.md              # 必需：skill 定义（含 YAML frontmatter）
├── scripts/              # 可选：可执行脚本
├── examples/             # 可选：使用示例
└── references/           # 可选：参考文档
```

`SKILL.md` frontmatter 必须包含 `name` 和 `description`。

## 创建新 Skill

```bash
# 1. 在 skill-archive/ 创建源文件
cd skill-archive/
mkdir <skill-name>
# 创建 SKILL.md，写好 frontmatter 和内容

# 2. 按归属创建符号链接
# 多 agent 通用：
ln -s ../skill-archive/<skill-name> skills/<skill-name>

# Claude 专用：
ln -s ~/.agents/skill-archive/<skill-name> ~/.claude/skills/<skill-name>

# Codex 专用：
ln -s ~/.agents/skill-archive/<skill-name> ~/.codex/skills/<skill-name>

# OpenCode 专用：
ln -s ~/.agents/skill-archive/<skill-name> ~/.config/opencode/skills/<skill-name>

# Hermes 专用：
ln -s ~/.agents/skill-archive/<skill-name> ~/.hermes/skills/<skill-name>

# 项目级：
ln -s ~/.agents/skill-archive/<skill-name> <project>/.claude/skills/<skill-name>

# 3. 提交（skill-archive 中的源文件）
git add skill-archive/<skill-name>
git commit -m "feat: add <skill-name>"
git push
```

## 删除 Skill

删除 = 从所有位置移除符号链接 + 删除源文件。

```bash
# 移除符号链接
rm skills/<skill-name>
rm ~/.claude/skills/<skill-name>       # 如有
rm ~/.codex/skills/<skill-name>       # 如有
rm ~/.config/opencode/skills/<skill-name>    # 如有
rm ~/.hermes/skills/<skill-name>          # 如有
rm <project>/.claude/skills/<skill-name>  # 如有

# 删除源文件
rm -rf skill-archive/<skill-name>

# 提交
git add skill-archive/ skills/
git commit -m "remove: delete <skill-name>"
git push
```

## 安装原则

**不要全量安装。** AI 加载已安装 skill 的全部内容，无关 skill 会浪费 token、挤占上下文。

```bash
# 安装（从 skill-archive 符号链接）
ln -s ~/.agents/skill-archive/<skill-name> <target-dir>/<skill-name>

# 卸载（删符号链接，不删源文件）
rm <target-dir>/<skill-name>
```

## Git 约定

- 提交信息：`feat: add ...` / `fix: ...` / `remove: ...` / `docs: ...`
- 分支策略：`main` 为主分支

## 注意事项

- `.` 开头的目录和文件，写入前须向用户确认
- 执行 `rm`、`mv` 等破坏性命令前，须确认目标路径
- 绝不在输出中暴露密钥、Token 等敏感信息
