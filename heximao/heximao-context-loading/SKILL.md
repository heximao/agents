---
name: heximao-context-loading
description: "Hermes 项目上下文文件加载规则：CLAUDE.md/AGENTS.md/HERMES.md/SOUL.md 的优先级、作用域和适用场景。当需要决定跨项目规则、路由规则、全局配置放在哪个文件时使用。"
version: 1.0.0
author: heximao
metadata:
  hermes:
    tags: [hermes, configuration, context-files, profiles]
---

# Hermes Context File Loading

Hermes 在启动时加载项目上下文文件注入系统 prompt。理解加载规则对于决定"规则放哪个文件"至关重要。

## 加载优先级（first found wins，只加载一个类型）

```
1. HERMES.md / .hermes.md   ← 向上遍历到 git root
2. AGENTS.md / agents.md    ← 只看 cwd
3. CLAUDE.md / claude.md    ← 只看 cwd
4. .cursorrules             ← 只看 cwd
```

**关键：只会加载第一个命中的文件类型。** 如果 cwd 有 CLAUDE.md 就不会加载 AGENTS.md。

## 独立加载的文件

- **SOUL.md** — 从 `$HERMES_HOME`（profile 目录）加载，**始终生效**，不受 cwd 影响
- **MEMORY** — 注入系统 prompt，始终生效

## 与 Claude Code 的关键区别

| 行为 | Claude Code | Hermes |
|------|------------|--------|
| CLAUDE.md 向上遍历 | ✅ 加载父目录直到根 | ❌ 只看 cwd |
| AGENTS.md 向上遍历 | ✅ | ❌ 只看 cwd |
| HERMES.md | 不支持 | ✅ 向上到 git root |
| 多个文件类型共存 | ✅ 都加载 | ❌ 只加载第一个命中的类型 |
| SOUL.md | 不支持 | ✅ 始终加载 |

## 适用场景指南

> **任务路由规则**详见 `heximao-coordinator-workflow` skill（topic-master 路由、kanban 工作流）。

### 跨项目规则（所有项目都需要）
→ 放 **SOUL.md**（profile 目录下），因为它是唯一"不受 cwd 影响、始终加载"的文件

示例：profile 路由规则、全局行为偏好、协调者职责定义

### 项目级规则（特定项目）
→ 放 **CLAUDE.md**（项目根目录）

示例：项目架构、代码规范、测试要求

### 需要向上遍历的项目规则
→ 放 **HERMES.md**（唯一支持向上遍历到 git root 的文件）

### 协调者的全局路由规则
→ 放 **SOUL.md** 而非 MEMORY，原因：
1. MEMORY 有 2200 字符限制，空间宝贵
2. SOUL.md 始终加载，不受启动目录影响
3. SOUL.md 可以承载更详细的规则说明

## Pitfalls

- ❌ 把路由规则放 `~/.hermes/CLAUDE.md` — 从项目目录启动时不会加载
- ❌ 把路由规则放 `~/.hermes/profiles/default/CLAUDE.md` — 同上
- ❌ 在 MEMORY 里放大量规则 — 2200 字符很快用完
- ✅ 跨项目的规则放 SOUL.md — 唯一可靠的选择
