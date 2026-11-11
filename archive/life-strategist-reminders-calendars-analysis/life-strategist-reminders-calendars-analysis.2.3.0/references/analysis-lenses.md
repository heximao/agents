# Analysis Framework & Cross-Reference Checks

Eight diagnostic lenses applied in order, plus five bidirectional cross-reference checks. Load this after parsing both snapshots.

## Analysis Framework

After data is gathered and parsed, run these **six diagnostic lenses** in order. Each produces a finding that feeds the action instructions.

### Lens 1: System Health (quantitative baseline)

- Overdue count: 0 = healthy ✅; >0 = avoidance signal (accumulating overdue =回避模式的客观数据)
- Black hole count: real black holes (no dueDate, no recurrence, not meta-rules) should be 0
- Habit consistency trend: rising = recovery; flat/falling = disruption
- Completion rate: completed/total — contextual only (mechanically grows as daily habits complete)
- Duplicate titles: exact-title items sharing a due date with different IDs inflate due-today counts — count due items by unique title and flag exact duplicates for deletion

### Lens 2: System-Task Invasion (Tool Over-Investment Gate on calendar)

The user's primary avoidance mechanism is substituting system/tool work for income-producing action. Apply the gate directly to calendar events:

For each event on today's calendar, ask: **Does this produce income or advance job search within 2 weeks?**

- ✅ Income-track: resume writing, JD collection, direction exploration, interview prep, job application
- ⚠️ System-task (avoidance risk): Hermes config, profile.yaml, SOUL updates, cron development, personality updates, script optimization, AGENTS.md editing, gitignore cleanup
- ❌ Neither: meals, sleep, rest (neutral, not avoidance)

**Flag any ⚠️ event occupying prime work hours (09:00-12:00, 14:00-18:00).** System tasks are fine in evening/weekend slots; in prime hours they are avoidance dressed as productivity.

**Overlap detection**: overlapping events are NOT automatically errors (Principle 3 — concurrent agent-delegated work is legitimate). Only flag an overlap as a conflict when both events require the user's active simultaneous attention (e.g., two meetings, or coding while on a call). If one event is background/agent-delegated and the other is active focus work, the overlap is legitimate parallel work — do not flag it as an error.

**Past vs future weight**: a ⚠️ event in a PAST slot is confirmed avoidance behavior (prime hours actually consumed — strongest evidence); a ⚠️ event in a FUTURE slot is a planned risk that can still be cancelled — recommend moving it to evening/weekend before it consumes prime time.

**Isolation-loop check (income-track perfectionism)**: an income-track task that passes the 2-week gate can still be avoidance when it loops without external validation — the same artifact rewritten 3+ times (e.g., 修改简历 regenerating daily in the career list) while submissions/applications/human feedback stay at zero is perfectionism-as-avoidance. The gate must check the feedback loop, not just the task category: when the career list keeps rewriting one artifact while 投递/开聊 count is zero, the finding is the missing external milestone (define 投递/开聊 with a deadline), never more editing time blocks.

### Lens 3: Time-Gap Detection

Scan **future slots** (now → end of day) for unscheduled blocks **>2 hours during work hours** (09:00-22:00) where the user has no income-track or focus work planned. These are productivity cliffs where the day can stall. Note: gaps may legitimately contain short routine tasks (feeding cat, brewing tea) that are correctly NOT on the calendar (Principle 4) — only a gap with neither calendar events nor routine-task fill is a real cliff. Past gaps carry different semantics — unrecorded time (rest, meals, untracked activity), not automatically lost time; do not flag past gaps as cliffs.

The most critical gap pattern: **12:00-15:00 (post-lunch)**. **13:00 Apple Reminder 已退役（2026-10-21），午后启动由 cron job 54cff38091c1「每日-提醒事项-日历-跟踪」驱动**——该 cron 在 8/13/17/22 时点 10 分自动推送分析消息（含催行动 + 时间块 + 下一步动作），功能覆盖并升级了原触发器。不再需要在 Reminders 快照中检查 13:00 触发器项；分析运行本身即证明午后启动机制在工作。Post-lunch gap（12:00-15:00 无 focus work）仍需检查，但触发器缺失不再是 P1——触发器已迁移到 cron 层。

### Lens 4: Income-Path Coverage

Cross-reference the career list in reminders with calendar events:

- Are resume modules scheduled on calendar? (each career-list item should have a corresponding calendar time block)
- Is there time for the NEXT milestone after resume completion? (投递/面试/JD response)
- Are there calendar blocks for direction exploration (BOSS JD search, freelance search)?

If all calendar career blocks are "writing" with no "submitting/responding," the income path has a ceiling — flag it.

### Lens 5: Time Hygiene

- Sleep event start time: >01:00 = late sleep (compresses morning window)
- Breakfast time: >11:00 = late (delays productive start)
- These are trend signals, not single-day alarms — but 3+ consecutive late days warrant a flag

### Lens 6: Black-Hole and Stale-Item Scan

In the `no_due` bucket, separate:
- **Meta-rules** (titles starting with 【Agent请跳过】) — user's task classification reference, KEEP, do not flag
- **Real black holes** (open-ended titles like "寻找机会XXX", no deadline, no recurrence) — flag for downgrade to time-boxed review or deletion
- **System markers** (【Issues】【Plan】【Task】 in hermes list) — kanban/system markers, not real tasks; flag if they're competing with career work for attention

### Lens 7: Reminders ↔ Calendar Integrity（双向校验）

The two systems must cross-validate. A task in Reminders without a Calendar time block is at risk of never getting done; a completed task without a Calendar time record is a data integrity gap.

**Forward check (Reminders → Calendar): important/long-duration tasks without time allocation.**

For each incomplete Reminders item that is:
- In a project list (`career`, `clash-proxy`, `life`) or has high priority (≥5), AND
- Has a due date within the next 7 days, AND
- Its title suggests substantial work (resume, JD, 投递, 面试, 方向探索, 开发, etc.)

Check if a corresponding FUTURE calendar event exists (title keyword overlap + date on or before the due date). If NOT → flag: "task `{title}` due `{date}` has no calendar time block — it will not get done unless time is allocated. Allocate a block now."

**Backward check (Calendar → Reminders): completed tasks without time records.**

For each completed Reminders item with `completionDateLocal` in the last 7 days that is NOT a daily habit (habits are short routine tasks excluded from the calendar per Principle 4):

Check if a corresponding PAST calendar event exists on or near the completion date (title keyword overlap). If NOT → flag: "task `{title}` marked complete on `{date}` but no calendar time record exists — either 补建 a retroactive event to log actual time, or 纠错 the completion if it was wrongly marked done."

### Lens 8: Past/Future Event Semantics（过去/未来事件语义检查）

检查分析输出是否正确区分过去/未来事件（Principle 2）：

1. **过去的时间块**（endDateLocal < now）= 用户实际做了什么（行为日志）。分析输出时用“花了X时间做Y”而非“完成了Y”。是否完成以 Reminders isCompleted 为准——日历时间块存在 ≠ 任务完成。
2. **未来的时间块**（startDateLocal > now）= 用户计划做什么（计划分配）。分析输出时用“计划X做Y”而非“已排好Y”。用户随时会改 title/时间/删除——不要当作确定事实。
3. **跨边界事件**（start < now < end）= 正在做的事。分析输出时用“正在做Y”。

4. **交叉校验：日历过去时间块 + Reminders 未完成** — 当日历有过去的时间块（endDateLocal < now）且对应 Reminders 任务未勾选（isCompleted = false）时，这是状态不一致。报告结论：问用户“做完了没？”→ 完成了→提醒去 Reminders 勾选完成 / 没完成→提醒修改截止时间。不得同时放在“今日完成”和“今日到期未完成”两个矛盾位置。

错误模式（必须避免）：
- ❌ “今日完成 ✅：social项目（16:00-17:00）” — 把过去时间块等同于任务完成
- ❌ 同时放在“今日完成”和“今日到期未完成” — 自相矛盾
- ✅ “social 做完了没？完成了去 Reminders 勾选；没做完改截止时间” — 交叉校验行动指令
- ❌ “日历已经排好了：14:00-15:30 social” — 把未来计划当作确定事实
- ✅ “计划 14:00-15:30 做 social（可能调整）”

## Cross-Reference Checks

The analysis derives its power from cross-referencing data sources, not from any single source alone:

| Check | Source A | Source B | What to look for |
|-------|---------|---------|-------------------|
| Important tasks ↔ Calendar blocks (forward) | reminders incomplete items in project lists (career/clash-proxy/life) with deadlines ≤7d | calendar future events | Each important/long-duration task should have a future calendar time block; if not → flag for time allocation (Lens 7 forward) |
| Completed tasks ↔ Calendar history (backward) | reminders completed items (non-habit) with completionDateLocal ≤7d | calendar past events | Each completed non-habit task should have a past calendar event; if not → flag for 补建 or 纠错 (Lens 7 backward) |
| Career sprint ↔ Calendar blocks | reminders `career` list incomplete items | calendar `工作` events | Each career-list task should map to a calendar block; unscheduled career tasks are at risk |
| Habit consistency ↔ Weekly report | 7-day habit trend from snapshot | latest weekly_report_*.md (under reminders/) | Is the trend accelerating, stable, or degrading vs the weekly report's assessment |
| cron 54cff38091c1 状态 | cron output 目录 `~/.hermes/profiles/life-strategist/cron/output/54cff38091c1/` | 当日是否有分析输出文件 | 13:00 触发器已退役迁移至 cron；若当日无 cron 输出文件 = 午后启动机制失效，flag P1 |
