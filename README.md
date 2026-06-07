# .agents 仓库

个人 Claude Code skills 的统一管理库，用于集中存放、版本控制和共享可复用的 AI 助手技能定义。

## 📚 简介

这是一个精选的 skills 集合仓库，包含：
- **40+ 专业 skills**：涵盖前端设计、软件开发、内容创作、数据分析、财务分析等多个领域
- **完整版本管理**：每个 skill 都在 Git 中追踪，支持历史回溯和团队协作
- **按需安装机制**：使用符号链接实现轻量级管理，避免上下文污染

## 🚀 快速开始

### 第一次使用

```bash
# 1. Clone 本仓库
git clone <repo-url> ~/.agents
cd ~/.agents

# 2. 验证仓库结构
ls -la
# 输出应包含：skills/、skill-archive/、README.md
```

### 安装 Skill

**关键原则**：不要全量安装所有 skills！按需安装，避免 token 浪费。

```bash
# 方式一：安装到项目目录（推荐）
ln -s ~/.agents/skills/frontend-design ~/my-project/.claude/skills/frontend-design

# 方式二：安装到全局目录（仅限常用 skill）
ln -s ~/.agents/skills/skill-creator ~/.claude/skills/skill-creator

# 卸载 skill
rm ~/.claude/skills/skill-name
```

### 验证安装

```bash
# 查看已安装的 skills
ls -la ~/.claude/skills/

# 查看符号链接指向
ls -la ~/.claude/skills/skill-name
```

## 📁 仓库结构

```
.agents/
├── README.md              # 本文件
├── skills/                # 所有可用的 skills（主要目录）
│   ├── agent-development/
│   ├── frontend-design/
│   ├── skill-creator/
│   ├── 股票智能分析师/
│   └── ... (40+ skills)
├── skill-archive/         # 已弃用或归档的 skills
└── .git/                  # 版本控制
```

## 🎯 核心概念

### 为什么不全量安装？

Claude Code 会加载所有已安装 skill 的完整内容到上下文中。大量无关 skill 会：
- ❌ 消耗大量 tokens（你的费用）
- ❌ 挤占有限的上下文窗口
- ❌ 降低 AI 的专注力和准确性

### 正确的安装策略

| 场景 | 安装位置 | 示例 |
|-----|--------|------|
| 仅在某个项目使用 | `project/.claude/skills/` | frontend-design 只用于前端项目 |
| 在多个项目使用 | `~/.claude/skills/` | skill-creator（多项目都用） |
| 已停用但保留参考 | `skill-archive/` | 旧版本 skills |

## 📦 精选 Skills 导览

### 开发类
- **agent-development** — 创建和调试 Claude agents
- **frontend-design** — 高质量前端 UI 组件和页面
- **software-development** — 通用软件开发辅助
- **hook-development** — Claude Code hook 开发
- **skill-creator** — 创建和优化 skills

### 专业领域
- **股票智能分析师** — A股/港股/美股分析和选股
- **tender-offer-arbitrage** — 事件驱动型套利机会扫描
- **transaction-verification** — 交易记录核对与验证
- **dcf-model** — DCF 估值模型计算

### 内容创作
- **documentation-writer** — 遵循 Diátaxis 框架的技术文档
- **content-marketing** — 内容营销策略和选题
- **md2wechat** — Markdown 转微信公众号 HTML
- **writing-rules** — 专业写作规范

### 工具和集成
- **web-access** — 联网搜索、网页抓取、社交媒体采集
- **aihot** — 实时 AI 行业资讯和热点
- **hot-topics** — 微博、知乎等平台热搜榜单
- **mcp** — Model Context Protocol 工具集

[更多 skills... 见 `skills/` 目录](./skills/)

## 🔄 维护和更新

### 更新仓库

```bash
cd ~/.agents
git pull origin main
```

### 创建新 Skill

```bash
cd skills/
mkdir my-new-skill
# 编辑 my-new-skill/SKILL.md
git add my-new-skill/
git commit -m "feat: add my-new-skill"
git push
```

### Skill 文件结构

```
skill-name/
├── SKILL.md              # 必需：skill 定义（含 YAML frontmatter）
├── scripts/              # 可选：可执行脚本
├── examples/             # 可选：使用示例和演示
└── references/           # 可选：相关文档和资源
```

## 💡 最佳实践

1. **定期清理** — 移除不使用的 skills 的符号链接，保持上下文清爽
2. **项目级隔离** — 优先在 `project/.claude/skills/` 安装，避免全局污染
3. **版本同步** — 定期 `git pull` 获取最新的 skills 和改进
4. **文档优先** — 在用新 skill 前，先读 `SKILL.md` 了解使用方法
5. **按需加载** — 只在当前项目安装真正需要的 skills

## 📖 相关资源

- [Skills 详细说明](./skills/README.md)
- [官方 Claude Code 文档](https://docs.anthropic.com/)
- [OMC 多智能体编排框架](./skills/omc-reference/)

## 📝 许可和使用

本仓库中的 skills 遵循各自的许可证。部分 skills 由 Anthropic 官方维护，部分为社区贡献。

## 🤝 贡献

欢迎提出改进建议或贡献新的 skills！

---

**最后更新**：2026-06-07