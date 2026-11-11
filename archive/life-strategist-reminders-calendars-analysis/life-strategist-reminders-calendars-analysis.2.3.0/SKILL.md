---
name: life-strategist-reminders-calendars-analysis
description: "Use when analyzing reminders+calendars to drive goals."
version: 2.3.0
author: life-strategist
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [life-strategy, reminders, calendars, analysis, diagnosis, execution]
---

# Reminders + Calendars Execution Analysis

The standing procedure for analyzing Apple Reminders + Calendar snapshot data to diagnose the user's execution state, detect avoidance-pattern intrusions, and issue prioritized action instructions. For the overall operating model see `life-strategy-operations`, for remindctl CLI see `apple-reminders`, for field specs see `SPEC/REMINDERS.md` and `SPEC/CALENDARS.md`.

## When to Use

- User asks to analyze reminders/calendar data to "push goal achievement"
- Weekly/monthly review or periodic self-diagnosis
- Saturday decision report needs a reminders+calendars input
- User asks "我的执行情况怎么样" or similar status questions
- Any session where the strategist needs situational awareness before issuing priorities

## Prerequisites

This skill reads **ONLY** from `~/life/reminders/` and `~/life/calendars/`. No external files (task_state.json, changelog.md, daily reports) — those belong to `life-strategy-operations`.

1. **Reminders snapshots**: `~/life/reminders/archive/YYYY/YYYY-MM/YYYY-MM-DD/YYYY-MM-DD_HHMM_reminders.json`
2. **Calendar snapshots**: `~/life/calendars/archive/YYYY/YYYY-MM/YYYY-MM-DD/YYYY-MM-DD_HHMM_calendars.json`
3. **Weekly analysis report** (optional): `~/life/reminders/analysis/weekly/YYYY/YYYY-MM/weekly_report_*.md`

**All data from archive only — no live app queries.** Do NOT call `remindctl` or read `Calendar.sqlitedb`. The 4-slot cron (8/13/17/22) ensures data is never more than ~5 hours stale.

## Data Gathering Sequence

**Batch independent reads** in ONE tool-call turn:

1. `date` — current time
2. Glob latest reminders snapshot: `ls -t ~/life/reminders/archive/YYYY/YYYY-MM/*/*.json | head -5`
3. Glob latest calendars snapshot: `ls -t ~/life/calendars/archive/YYYY/YYYY-MM/*/*.json | head -5`

Second round (with paths from steps 2-3):

4. Parse latest reminders snapshot JSON → see `references/parsing-logic.md`
5. Parse latest calendars snapshot JSON → see `references/parsing-logic.md`
6. `read_file` latest weekly analysis report (under `~/life/reminders/analysis/weekly/`)

## Calendar Time Semantics

Four principles govern how calendar durations must be interpreted. **Load `references/calendar-time-semantics.md` before parsing calendar data.**

1. **30-min quantization** — granularity 30 min, minimum 30 min, durations = ceil(need/30)×30
2. **Plan/log duality** — past events = actual time log; future events = planned allocation; boundary = now
3. **Concurrent events legitimate** — overlapping is NOT automatically an error; only flag when both require active simultaneous attention
4. **Short routine tasks NOT on calendar** — 喂猫/泡茶/签到 live in Reminders; absence from calendar is correct

## Core Purpose

**This skill exists to help the user spend time on important things — not to maintain a tidy schedule.**

The goal cycle: **设定目标 → 推进目标 → 完成目标 → 设定新目标 → 循环**. Every analysis must answer this first: "Is the user's time being spent on goal-advancing work?"

Everything else — habit consistency, schedule neatness, time hygiene, system health — is **secondary infrastructure**. It exists to serve goal advancement, not to replace it. A perfectly maintained habit system with zero goal-advancing work is a RED FLAG, not a success:

- 24/24 habits completed but no career/income work done → the system is running perfectly and serving no purpose
- 0 overdue, 0 black holes, calendar neatly packed → tidy but empty if no time went to goals
- System tasks filling prime hours → infrastructure maintenance masquerading as productivity

**Always check the goal cycle before running any lens:**

1. Is there a **current goal** in the Reminders career/project lists with a deadline?
2. Is time **allocated** to it on the calendar (Lens 7 forward check)?
3. Is the goal being **advanced** — completed items showing progress (Lens 7 backward check)?
4. What happens **after** the current goal completes — is the next milestone defined and time-blocked?

If any of these is missing, that's the #1 finding — ahead of any system-health or time-hygiene issue. Schedule neatness and habit consistency are reported as secondary status, never as the headline.

**The analysis report is a DECISION artifact, not an observation report.** The user invests heavily in data collection (4-slot cron, archive normalization, scan scripts) — the return on that investment is decision quality, not more analysis. The strategist decides (what to do, in what order, by when), the user executes. A report that presents findings without deciding is incomplete.

## Analysis Framework

Eight diagnostic lenses, applied in order. **Load `references/analysis-lenses.md` for full detail and the cross-reference table.**

1. **System Health** — overdue/black-hole/habit-trend baseline
2. **System-Task Invasion** — Tool Over-Investment Gate on calendar; past = confirmed avoidance, future = cancellable risk; income-track task looping 3+ times with zero external validation (投递/开聊/反馈) = perfectionism-as-avoidance
3. **Time-Gap Detection** — future slots >2h with no income-track/focus work = cliff; past gaps = unrecorded (not a problem)
4. **Income-Path Coverage** — career list ↔ calendar blocks; is there time for投递/面试 after resume?
5. **Time Hygiene** — sleep >01:00, breakfast >11:00 = late; 3+ consecutive days = flag
6. **Black-Hole Scan** — meta-rules (keep), real black holes (flag), system markers (flag if competing)
7. **Reminders ↔ Calendar Integrity** — forward: important tasks without calendar blocks; backward: completed tasks without calendar records (补建/纠错)
8. **Past/Future Event Semantics** — past block = behavior log (spent time doing X ≠ task done); future block = plan (changeable); past block + Reminders unchecked → ask the user done-or-not, never place the same item in both 今日完成 and 今日到期未完成

## Output Structure

```
# 📊 提醒事项 + 日历日程分析 | YYYY-MM-DD 周X HH:MM

## 结论先行
<1-2 sentence assessment: is the user's time being spent on goal-advancing work? State the goal-cycle status (set/advancing/complete/next-defined) before any system-health observation.>

## 一、数据全景
### Reminders（snapshot time）
<table: key metrics with ✅/⚠️/🔴>
### Calendar（today's events）
<table: time | event | calendar | nature(✅/⚠️/❌)>
### Career 列表冲刺进度
<table: status | module | deadline>

## 二、问题诊断
### 🔴 P1: <most critical>
### 🔴/🟡 P2: <second>
### 🟡 P3+: <lower priority>

## 三、行动指令
### 今天（date, current time）
### 本周
### 系统清理（不占工作时段）

## 下一步动作
<ONE concrete next action, time-bounded>
```

### Priority classification

- **🔴 P1**: Actively blocking goal achievement THIS WEEK
- **🟡 P2**: Structural risk that will block if unaddressed
- **🟢 P3**: Background improvement

### Time Discipline check (before any "do this today" instruction)

1. Actual deadline? (from Reminders snapshot `dueDateLocal`)
2. What time is it now? (from `date`)
3. What has the user already done today? (from snapshot `completionDateLocal`)
4. Is urgency real (≤24h and unfinished) or manufactured (days away)?

Acknowledge completed work before pushing new items.

## Report Output

- **Path**: `~/life/report/YYYY/YYYY-MM/YYYY-MM-DD/YYYY-MM-DD_HHMM_reminders-calendars-analysis.md`
- **HHMM**: actual run time from `date`; consumers glob for latest
- **Structure**: three-level `YYYY/YYYY-MM/YYYY-MM-DD/`, mirroring archive layout
- **Atomic write**: `<file>.tmp` → `os.replace()`; `os.makedirs(..., exist_ok=True)`
- **Content**: full analysis output per the Output Structure above
- **Verify** file exists and is non-empty before claiming complete

## Pitfalls

**Load `references/pitfalls.md` before executing** — 17 pitfalls covering: priority field type crash, camelCase calendar fields, UTC/Beijing time, stale dueDate, completed-habit recurrenceRule stripping, empty-group key omission, snapshot point-in-time semantics, meta-rules not black holes, 13:00 trigger retirement (replaced by cron 54cff38091c1), system tasks = avoidance evidence, overlapping duration overstatement, and completed-task-without-calendar-event integrity gap, in-progress event endDate conflated with activity-chain completion time, calendar past/future event semantics (behavior log vs plan, completion ≠ time block), user-quote temporal attribution (cite feedback with its recorded date or no time pointer — never an invented relative period).

## Skill Self-Update（自我更新）

When the user reports a serious error or omission in an analysis report, the response must be two-level — never only the instance fix:

1. **Immediate fix**: correct the specific report finding in the current session; acknowledge the error explicitly.
2. **System-level root cause**: ask which layer of the skill's procedure allowed the error — a missing principle, a missing pitfall, a missing lens, a missing cross-reference check, or an existing rule that wasn't followed. The reported error is a symptom; the procedure gap is the cause.
3. **Patch the skill**: update the relevant section (principle / pitfall / lens / reference file) so the entire error CLASS is prevented, not just the instance. Bump the skill version. **Every example recorded below must carry its actual date — `← user (YYYY-MM-DD HH:MM): …` —** future analysis runs cite these examples, and an undated quote invites a run to invent a time period ("上周") for feedback that may be hours old. Legacy undated examples are 日期未知: cite them with no time pointer, never a relative period.
4. **Recurrence escalation**: if the same error class recurs after a patch, the patch was at the wrong abstraction level — escalate the fix one level up (e.g., overlap misjudged again after Principle 3 means the classification criteria are too fuzzy, not that another example is needed).

Examples from this skill's own error-driven evolution:

- Overlap misjudged as "scheduling error" ← user: "同时段做2件事是正常的（agent并行）" → root cause: missing principle → fix: Principle 3 + Lens 2 rewrite (v1.2)
- Short tasks expected on calendar ← user: "不耗时的事不进日历" → root cause: missing semantic → fix: Principle 4 + Lens 3 gap semantics (v1.2)
- Completed tasks not cross-checked against calendar ← user: "标记完成但日历没有也要校验" → root cause: missing lens → fix: Lens 7 backward check (v1.3)
- Live remindctl queries bypassing archive ← user: "数据源只有两个目录" → root cause: violated collection-analysis separation → fix: all live queries removed, data source narrowed (v1.1)
- Analysis prioritized system health over goal advancement ← user: "核心目标是把时间花在重要事情上，按部就班是次要的" → root cause: missing north-star principle → fix: Core Purpose section, goal-cycle check before lenses (v1.7.0)
- Analysis said "13:30吃完" for in-progress "做午餐" event ← user: "吃午餐是13:30-14:00，14:00才吃完" → root cause: missing pitfall — in-progress event endDate conflated with activity-chain completion, no event-chain tracking → fix: Pitfall 16, event-chain tracking rule (v1.8.0)
- 13:00 饭后触发器 pitfall 退役 ← user: "13:00的午后触发器已经被每日-提醒事项-日历-分析替代了" → root cause: 机制已迁移至 cron，pitfall 描述的检查对象（Reminders 13:00 项）已不存在 → fix: Pitfall 11 改写为退役说明，检查逻辑移除 (v1.9.0)
- Calendar title/time changes frequent, snapshot data stale at delivery ← user: "日程调整的频率非常高" → 误诊为快照过时 → user 纠正: "不是快照的问题，每次运行时最新快照就在前10分钟" → root cause: 误诊。真正问题是分析 JSON 时未区分过去/未来事件语义 → user: "对于已经过去的时间，日程中代表实际做的事情。未来未来的时间，才是计划做的事情" → fix: Pitfall 17 改为过去/未来语义规则, Lens 8 改为过去/未来事件语义检查 (v2.0.0)
- Analysis put social in both “今日完成” and “今日到期未完成” ← user: "日历有16:00-17:00 social，提醒没勾，结论应该是问我做完了没——完成了去勾选/没完成改截止时间" → root cause: Lens 8 缺少交叉校验行动指令——检测到过去时间块+Reminders未完成但不给明确结论 → fix: Pitfall 17 加规则⑤交叉校验, Lens 8 加第4点交叉校验场景+行动指令 (v2.1.0)
- Analysis passed 4 rounds of 修改简历 as income-track while applications stayed at zero ← user (2026-10-23 12:09): "现在每天为了写简历而写简历，让我内心有点抗拒" → root cause: Lens 2 gate checked task CATEGORY only, not the feedback LOOP — an income-track artifact iterating 3+ times with no external validation is perfectionism-as-avoidance → fix: Lens 2 isolation-loop check, Lens 1 duplicate-title scan (v2.2.0)
- Report cited same-day user feedback as "你上周自己说过" ← user (2026-10-23, via issues file 2026-10-23_issues.md): "暴露了时间周期错位" → root cause: Self-Update examples carried no dates and no rule prohibited invented temporal attribution — the analysis run pattern-matched the example list as "historical" and fabricated "上周" for a quote that was 5 hours old → fix: date-stamped examples + mandatory date-stamping rule in step 3 + Pitfall 17 (temporal anchoring of user-feedback citations) (v2.3.0)

