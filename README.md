# .agents

Agent Skills 统一管理仓库。

---

## 为什么需要一个集中 Skill 仓库

每个 AI Agent（Claude Code、OpenCode、Codex、Hermes……）都有自己的 Skill 机制，但 Skill 本身是可复用的——一个「飞书日历」Skill 不应该为每个 Agent 各写一份。

集中管理解决三个问题：

1. **一次编写，多处使用。** 改一处，所有 Agent 都生效。
2. **版本控制。** Git 管理变更历史，可回溯、可协作。
3. **避免漂移。** 散落在各处的副本会逐渐分叉，集中存档保证唯一源。

## 为什么沿用 `.agents` 目录

集中存放需要选一个目录。`~/.agents/skills` 是由 Vercel 发起的跨 Agent 用户级 Skill 目录规范，**OpenCode 和 Codex 已经认可并兼容了这个路径**——链接到这里的 Skill 自动生效。

既然 `.agents/` 已经是事实上的 Skill 目录，源文件自然放在同级的 `skill-archive/` 下，`skills/` 作为分发层承接兼容 Agent 的自动加载。未兼容的 Agent（Claude Code、Hermes）则从 `skill-archive/` 直接链接到各自专用目录。

## 各 Agent 的 Skill 自动加载机制

不同 Agent 的 Skill 发现路径不同，理解这一点才能正确安装：

| Agent | 用户级自动加载路径 | 项目级自动加载路径 | 加载方式 |
|-------|-------------------|-------------------|---------|
| **OpenCode** | `~/.agents/skills` | | 自动扫描 |
| | `~/.config/opencode/skills` | | 自动扫描 |
| **Codex** | `~/.agents/skills` | | 自动扫描 |
| | `~/.codex/skills` | `<project>/.codex/skills`| 自动扫描 |
| **Claude Code** | `~/.claude/skills` | `<project>/.claude/skills` | 自动扫描 |
| **Hermes** | `~/.hermes/skills` | — | 自动扫描 |

> **关键区别：** OpenCode 和 Codex 会自动识别 `~/.agents/skills`，Claude Code 和 Hermes 不会——它们需要符号链接到各自专用目录。

## 安装使用指南

> ⚠️ **按需安装，不要全量加载。** 过多的 Skill 会干扰上下文，降低 Agent 的判断准确度。

所有安装都是从 `skill-archive/` 创建符号链接。区别在于链接到哪里——取决于你用的 Agent 和作用域。

### 用户级（全局生效）

**OpenCode / Codex** 原生识别 `~/.agents/skills`，链接到这里两个 Agent 都能用：

```bash
# 两个 Agent 通用
ln -s ~/.agents/skill-archive/<skill-name> ~/.agents/skills/<skill-name>

# 只给其中一个 Agent 用
ln -s ~/.agents/skill-archive/<skill-name> ~/.config/opencode/skills/<skill-name>   # OpenCode
ln -s ~/.agents/skill-archive/<skill-name> ~/.codex/skills/<skill-name>              # Codex
```

**Claude Code / Hermes** 不识别 `~/.agents/skills`，需要链接到各自专用目录：

```bash
ln -s ~/.agents/skill-archive/<skill-name> ~/.claude/skills/<skill-name>             # Claude Code
ln -s ~/.agents/skill-archive/<skill-name> ~/.hermes/skills/<skill-name>             # Hermes
```

### 项目级（仅项目使用）

```bash
ln -s ~/.agents/skill-archive/<skill-name> <project>/.claude/skills/<skill-name>     # Claude Code
ln -s ~/.agents/skill-archive/<skill-name> <project>/.codex/skills/<skill-name>      # Codex
```

### 卸载

删符号链接即可，`skill-archive/` 中的源文件不受影响：

```bash
rm <target-dir>/<skill-name>
```

---

## 当前可用 Skills

共 **98** 个 Skill，按来源分类。

### anthropic — Anthropic 官方（17）

| Skill | 说明 |
|-------|------|
| `algorithmic-art` | p5.js 算法艺术生成 |
| `brand-guidelines` | Anthropic 品牌色彩与排版规范 |
| `canvas-design` | 视觉设计：海报、艺术品、静态设计 |
| `claude-api` | Claude API / Anthropic SDK 开发指南 |
| `doc-coauthoring` | 结构化文档协作编写流程 |
| `docx` | Word 文档（.docx）创建、编辑、分析 |
| `frontend-design` | 高质量前端界面设计，避免 AI 审美同质化 |
| `internal-comms` | 内部沟通文档：状态报告、周报、FAQ |
| `mcp-builder` | MCP Server 开发指南 |
| `pdf` | PDF 读取、合并、拆分、OCR、表单填充 |
| `pptx` | PowerPoint 幻灯片创建与编辑 |
| `skill-creator` | Skill 创建、优化与性能评测 |
| `slack-gif-creator` | Slack 优化的动画 GIF 制作 |
| `theme-factory` | 10 套预设主题，可应用于任意 artifact |
| `webapp-testing` | Playwright 本地 Web 应用测试 |
| `web-artifacts-builder` | claude.ai HTML artifact 构建（React + Tailwind） |
| `xlsx` | Excel 电子表格（.xlsx）创建与编辑 |

### hermes — Hermes 生态（53）

**Apple 生态**

| Skill | 说明 |
|-------|------|
| `apple-notes` | Apple Notes 管理（memo CLI） |
| `apple-reminders` | Apple Reminders 管理（remindctl） |
| `findmy` | Apple 设备 / AirTag 追踪 |
| `imessage` | iMessage / SMS 收发（imsg CLI） |
| `macos-computer-use` | macOS 桌面操控：截屏、鼠标、键盘 |

**开发工具**

| Skill | 说明 |
|-------|------|
| `claude-code` | 委派编码给 Claude Code CLI |
| `codex` | 委派编码给 OpenAI Codex CLI |
| `opencode` | 委派编码给 OpenCode CLI |
| `hermes-agent` | 配置、扩展 Hermes Agent |
| `hook-development` | Claude Code 插件 Hook 开发指南 |
| `kanban-worker` | Hermes Kanban Worker 生命周期 |
| `kanban-orchestrator` | Kanban 编排者分解与路由策略 |

**GitHub**

| Skill | 说明 |
|-------|------|
| `github-auth` | GitHub 认证：HTTPS / SSH / gh CLI |
| `github-code-review` | PR 代码审查 |
| `github-issues` | Issue 创建、分类、标签管理 |
| `github-pr-workflow` | PR 全生命周期：分支、提交、合并 |
| `github-repo-management` | 仓库克隆、创建、Fork、Release |
| `codebase-inspection` | 代码库统计：LOC、语言分布 |

**软件工程**

| Skill | 说明 |
|-------|------|
| `test-driven-development` | TDD：RED-GREEN-REFACTOR 流程 |
| `systematic-debugging` | 4 阶段根因调试法 |
| `requesting-code-review` | 提交前审查：安全扫描、质量门禁 |
| `plan` | Plan 模式：写可执行的 Markdown 计划 |
| `spike` | 一次性实验：验证想法再开发 |
| `python-debugpy` | Python 调试：pdb + debugpy |
| `node-inspect-debugger` | Node.js 调试：--inspect + Chrome DevTools |
| `hermes-agent-skill-authoring` | Hermes Skill 编写规范 |

**创意 & 设计**

| Skill | 说明 |
|-------|------|
| `architecture-diagram` | 暗色主题 SVG 架构图 / 云架构图 |
| `ascii-art` | ASCII 艺术：pyfiglet、cowsay |
| `ascii-video` | 视频转彩色 ASCII 动画 |
| `baoyu-infographic` | 信息图：21 布局 × 21 风格 |
| `claude-design` | 单页 HTML 设计：Landing、Deck |
| `comfyui` | ComfyUI 图像 / 视频 / 音频生成 |
| `design-md` | Google DESIGN.md Token 规范 |
| `excalidraw` | Excalidraw 手绘风格图表 |
| `humanizer` | 去 AI 腔：给文本加真实感 |
| `manim-video` | Manim 数学 / 算法动画 |
| `p5js` | p5.js 创意编程 |
| `popular-web-designs` | 54 个真实设计系统（Stripe、Linear…） |
| `pretext` | DOM-free 文字排版与 ASCII 艺术 |
| `sketch` | 快速 HTML 原型：2-3 方案对比 |
| `songwriting-and-ai-music` | 歌曲创作 + Suno AI 音乐提示 |
| `touchdesigner-mcp` | TouchDesigner 实时视觉控制 |

**效率工具**

| Skill | 说明 |
|-------|------|
| `google-workspace` | Gmail / Calendar / Drive / Docs / Sheets |
| `himalaya` | IMAP/SMTP 终端邮件（himalaya CLI） |
| `imap-mail` | IMAP 邮件读取与整理 |
| `nano-pdf` | PDF 文本编辑（自然语言指令） |
| `notion` | Notion API + ntn CLI |
| `airtable` | Airtable REST API 操作 |
| `obsidian` | Obsidian 笔记管理 |
| `powerpoint` | PowerPoint 创建与编辑 |
| `maps` | 地理编码、POI、路线规划 |
| `teams-meeting-pipeline` | Teams 会议摘要流水线 |

**数据 & AI**

| Skill | 说明 |
|-------|------|
| `jupyter-live-kernel` | Jupyter 内核交互式 Python |
| `huggingface-hub` | HuggingFace 模型 / 数据集管理 |
| `native-mcp` | MCP 客户端：连接 Server、注册工具 |

**研究**

| Skill | 说明 |
|-------|------|
| `arxiv` | arXiv 论文搜索 |
| `blogwatcher` | 博客 / RSS 监控 |
| `llm-wiki` | Karpathy LLM Wiki 知识库 |
| `polymarket` | Polymarket 预测市场查询 |
| `research-paper-writing` | ML 论文写作流水线（NeurIPS/ICML） |

**社交 & 媒体**

| Skill | 说明 |
|-------|------|
| `xurl` | X/Twitter 操作：发帖、搜索、DM |
| `youtube-content` | YouTube 字幕 → 摘要 / 帖子 / 博客 |
| `gif-search` | Tenor GIF 搜索下载 |
| `heartmula` | 歌词 + 标签 → AI 音乐生成 |
| `songsee` | 音频频谱分析 |

**游戏 & 其他**

| Skill | 说明 |
|-------|------|
| `minecraft-modpack-server` | Minecraft 模组服务器管理 |
| `pokemon-player` | Pokemon 无头模拟器游玩 |
| `openhue` | Philips Hue 灯光控制 |
| `dogfood` | Web 应用探索性 QA |
| `yuanbao` | 元宝群：@提及、成员查询 |

**Hermes 内部**

| Skill | 说明 |
|-------|------|
| `heximao-coordinator-workflow` | Hermes 协调者任务分配工作流 |
| `heximao-context-loading` | 项目上下文文件加载规则 |
| `heximao-multi-profile` | 多 Profile 管理与路由 |
| `smart-search` | OpenCLI 智能搜索路由器 |

### lark — 飞书集成（21）

| Skill | 说明 |
|-------|------|
| `lark-approval` | 审批实例与任务管理 |
| `lark-apps` | HTML 部署到飞书妙搭 |
| `lark-attendance` | 考勤打卡记录查询 |
| `lark-base` | 多维表格：字段、记录、视图、工作流 |
| `lark-calendar` | 日历与日程管理、会议室预定 |
| `lark-contact` | 通讯录：姓名 ↔ open_id 解析 |
| `lark-doc` | 云文档 / Docx / Wiki 读写编辑 |
| `lark-drive` | 云空间：上传下载、文件管理、导入 |
| `lark-event` | 实时事件监听（NDJSON 流） |
| `lark-im` | 即时通讯：消息收发、群聊管理 |
| `lark-mail` | 邮箱：收发、草稿、附件、规则 |
| `lark-markdown` | Markdown 文件查看与编辑 |
| `lark-minutes` | 妙记：音视频转纪要、逐字稿 |
| `lark-okr` | OKR 目标与关键结果管理 |
| `lark-openapi-explorer` | 原生 OpenAPI 接口探索 |
| `lark-shared` | lark-cli 共享规则与认证 |
| `lark-sheets` | 电子表格：读写、查找、导出 |
| `lark-skill-maker` | 自定义 lark-cli Skill 创建 |
| `lark-slides` | 幻灯片：创建、编辑、读取 |
| `lark-task` | 任务、清单与任务智能体 |
| `lark-vc` | 视频会议：历史会议、纪要、逐字稿 |
| `lark-vc-agent` | 视频会议：代为入会、实时事件 |
| `lark-whiteboard` | 画板：导出、编辑、DSL/PlantUML 更新 |
| `lark-wiki` | 知识库：空间、成员、节点管理 |
| `lark-workflow-meeting-summary` | 会议纪要汇总工作流 |
| `lark-workflow-standup-report` | 日程待办摘要工作流 |

### heximao — 内容创作（11）

| Skill | 说明 |
|-------|------|
| `article-style-analyse` | 多篇文章风格分析 → 生成仿写 Skill |
| `gemini-image-gen` | Gemini API 封面图生成 |
| `heximao-jinjiancheng-dianpin-style` | 金渐成点评风格写作 |
| `jin-jiancheng-style` | 金渐成风格写作（v1） |
| `jin-jiancheng-style-horizen` | 金渐成风格写作（v2） |
| `jin-jiancheng-style2` | 金渐成投资分析风格 |
| `xiaohongshu-marketing-master` | 小红书营销文案 |
| `xueqiu-article-title-creator` | 雪球爆款标题写作 |
| `wechat-article-title-creator` | 公众号爆款标题创作 |
| `wechat-comment-format` | 公众号留言排版 |

### opencli — OpenCLI 工具（4）

| Skill | 说明 |
|-------|------|
| `opencli-adapter-author` | 为新站点编写 OpenCLI Adapter |
| `opencli-autofix` | Adapter 失败时自动诊断修复 |
| `opencli-browser` | 通过 OpenCLI 驱动真实浏览器 |
| `opencli-usage` | OpenCLI 总览与使用指南 |

### playwright-cli — Playwright（1）

| Skill | 说明 |
|-------|------|
| `playwright-cli` | 浏览器自动化测试 |

### web — 社区 / 工具（22）

**金融 & 投资**

| Skill | 说明 |
|-------|------|
| `股票智能分析师` | A 股 / 港股 / 美股技术面 + 基本面分析 |
| `dcf-model` | DCF 现金流折现估值模型 |
| `tender-offer-arbitrage` | 事件驱动套利机会扫描 |
| `transaction-verification` | 交易记录核查与校验 |

**内容 & 营销**

| Skill | 说明 |
|-------|------|
| `aihot` | AI HOT 中文 AI 资讯日报 |
| `content-marketing` | 内容营销策略框架 |
| `documentation-writer` | Diátaxis 技术文档写作 |
| `hot-topics` | 微博 / 知乎 / 百度 / 抖音热搜 |
| `hot_topics_selector` | 财经热点选题工具 |
| `md2wechat` | Markdown 转微信公众号 HTML |
| `frontend-design` | 高质量前端界面设计 |
| `cn-ppt-outline-writer` | PPT 大纲生成 |
| `简历优化师` | 简历诊断、改写、JD 匹配 |
| `skill-creator` | Skill 创建与优化 |
| `web-access` | 联网操作统一入口（浏览器） |

**微信公众号运营（aws-wechat）**

| Skill | 说明 |
|-------|------|
| `aws-wechat-article-main` | 公众号一条龙：选题→写→审→排→图→发 |
| `aws-wechat-article-writing` | 公众号写稿 / 改写 / 润色 |
| `aws-wechat-article-review` | 公众号审稿：敏感词、合规检查 |
| `aws-wechat-article-formatting` | Markdown 转公众号 HTML 排版 |
| `aws-wechat-article-images` | 公众号封面 / 配图 AI 生成 |
| `aws-wechat-article-topics` | 公众号选题与爆款标题 |
| `aws-wechat-article-publish` | 公众号 API 发布（草稿箱 / 群发） |
| `aws-wechat-article-assets` | 素材库与 .aws 预设包管理 |
| `aws-wechat-sticker` | 贴图 / 九宫格 / 多图推送 |

**开发 & 工具**

| Skill | 说明 |
|-------|------|
| `agent-development` | Claude Code Agent 开发指南 |
| `find-skills` | 发现和安装 Agent Skills |
| `writing-rules` | Hookify 写作规则配置 |
| `wemedia-spec-navigator` | 自媒体项目规范导航 |

---

## 仓库结构

```
.agents/
├── skill-archive/             # 所有 Skill 的存档（唯一源）
│   ├── anthropic/             #   Anthropic 官方
│   ├── hermes/                #   Hermes 生态
│   ├── lark/                  #   飞书集成
│   ├── heximao/               #   内容创作
│   ├── opencli/               #   OpenCLI 工具
│   ├── playwright-cli/        #   Playwright
│   └── web/                   #   社区 / 工具
├── skills/                    # 多 Agent 兼容目录（OpenCode / Codex 自动识别）
│   └── <symlink> → skill-archive/
├── CLAUDE.md                  # 维护指南
└── README.md                  # 本文件
```

---

**最后更新**：2026-06-11
