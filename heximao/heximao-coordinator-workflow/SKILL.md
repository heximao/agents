---
name: heximao-coordinator-workflow
description: "Hermes 协调者任务分配工作流。当 Hermes（协调者角色）需要分配任务给其他 profile、使用 kanban 管理任务、或决定路由到哪个 topic-master 时使用。触发词：分配任务、路由、topic-master、kanban、delegate。"
version: 1.0.0
author: heximao
metadata:
  hermes:
    tags: [hermes, coordinator, kanban, routing, delegation]
    related_skills: [heximao-context-loading, kanban-worker]
---

# Hermes 协调者任务分配工作流

> 协调者（Hermes）的核心铁律：**严禁自己执行任何具体任务**。只做拆分、分配、监控、汇报。

## 三个 Topic-Master 路由规则

| Profile | 路由领域 | 触发条件 |
|---------|----------|----------|
| `ai-topic-master` | AI / LLM / 大模型 | 热点涉及 AI 模型、LLM、GPT、大模型应用、AI 产品发布 |
| `finance-topic-master` | 财经 / 投资 / 美股 | 热点涉及股市、财报、投资、宏观经济、美联储、美股/A股 |
| `topic-master` | 通用兜底 | 不属于上述两者的其他热点 |

### 路由决策流程

```
用户下达任务
    ↓
判断任务领域
    ↓
┌───────────────────┬───────────────────┬───────────────────┐
│ AI/LLM 相关       │ 财经/投资相关      │ 通用/不确定        │
│ → ai-topic-master │ → finance-topic-  │ → topic-master    │
│                   │   master          │   (兜底)          │
└───────────────────┴───────────────────┴───────────────────┘
```

**不确定时选 topic-master（通用兜底）**，等内容回来后再细分路由。

### 两阶段模式（采集 + 分析）

对于"获取热点"类任务，采用两阶段模式：

1. **第一阶段**：分配给 `topic-master` 做通用采集（微博、知乎、百度、抖音、B站）
2. **第二阶段**：根据采集结果，将特定领域热点路由给对应的 topic-master 深入分析

## Kanban 工作流

### 创建任务

```bash
# 分配给指定 profile
hermes kanban create "任务标题" --assignee <profile-name> --json

# 不指定 assignee，让 profile 自己领取
hermes kanban create "任务标题" --json
```

### 常用命令

| 操作 | 命令 |
|------|------|
| 创建任务 | `hermes kanban create "标题" --assignee <profile>` |
| 查看任务 | `hermes kanban show <task_id> --json` |
| 归档任务 | `hermes kanban archive <task_id>` |
| 重新分配 | `hermes kanban reassign <task_id> <profile>` |
| 添加评论 | `hermes kanban comment <task_id> "评论内容"` |
| 标记完成 | `hermes kanban complete <task_id> --summary "完成摘要"` |

### ⚠️ Pitfalls

- ❌ **没有 cancel 命令**：用 `archive` 归档错误任务，不是 cancel
- ❌ **不要自己执行**：协调者看到任务就想动手是最大的诱惑，必须忍住
- ❌ **不要乱指定 assignee**：不确定时让任务处于 ready 状态，或先问用户
- ❌ **不要只派任务就不管了**：派发后必须追踪结果，阻塞立即干预，验收后才汇报
- ❌ **不要派一个模糊任务**：AI worker 不是人类，需要完整的上下文而非暗示
- ✅ **先看 profile 列表**：`hermes profile list` 确认哪些 profile 正在运行
- ✅ **优先 running 的 profile**：分配给正在运行的 profile 执行更快
- ✅ **派发前加载并阅读相关 skill**：技能文档里有 API、格式、步骤，直接写在任务描述里告诉 worker

### 协调者派发任务的完整上下文清单（每次派发必须检查）

派任务给 worker 时，以下信息**必须全部给出**，缺一不可：

1. **📌 目标文件路径**：项目根目录、具体文件路径、文件名格式
2. **📌 YAML 头部字段**：id、status、其他必需字段
3. **📌 技能引用**：用 `hot-topics` 还是 `blogwatcher` ？先 `skill_view` 再写任务
4. **📌 验收标准**：几条数据？什么格式？用 `kanban_complete` 还是 `kanban_block`？
5. **📌 异常处理**：某个源失败怎么办？重试还是跳过？
6. **📌 依赖关系**：和其他任务有先后吗？用 `parents` 链接

### 协调者追踪流程

派发后：
1. 定时检查任务状态（`hermes kanban show <id> --json`）
2. 发现 `blocked` → 读原因，如果是 worker 问题（protocol violation / crashed）→ archive 后换 profile 重派
3. 发现 `done` → 验���结果完整性（`result` 字段、summary 是否有实际数据），不达标 → 加评论追问或重派
4. 确认结果正确 → 向用户汇报

## 协调者自检清单

每次收到任务时，过一遍：

- [ ] 这个任务我应该自己做吗？→ **不应该**
- [ ] 应该分配给哪个 profile？→ 根据领域路由
- [ ] 需要拆分成子任务吗？→ 复杂任务需要拆分
- [ ] 有依赖关系吗？→ 用 parents 链接
- [ ] 分配的 profile 正在运行吗？→ `hermes profile list` 检查

## 典型任务路由示例

| 任务 | 路由目标 |
|------|----------|
| 获取今日热搜 | `topic-master`（通用采集） |
| AI 热点深入分析 | `ai-topic-master` |
| 财经热点选题 | `finance-topic-master` |
| 写文章 | `writer` 或 `writer-jinjiancheng` |
| 审核文章 | `reviewer` 或 `article-reviewer` |
| 代码开发 | `coder` |
| 运维/部署 | `devops` |
