# 解析逻辑

两类快照的可复用 Python 解析代码。**解析快照 JSON 之前先加载本文件**；查字段中文名与易错点见 `field-map.md`。

> ⚠️ **日历侧不写循环分支。** 用户规则「不创建任何循环日历日程」，`recurrenceRule` 恒为 `null`、`hasRecurrences` 恒为 `0`。字段定义上日历 `frequency` 是整数、提醒事项是字符串，但**这是理论差异，实际永不触发**——不要写兼容逻辑，把它当断言：非空即违规，标记并建议删除。提醒事项侧 `frequency` 是字符串 `'daily'`/`'weekly'`/`'monthly'`/`'yearly'`。

### 提醒事项快照

快照结构为 `{scan_time_utc, scan_time_local, total, completed, incomplete, lists, items}`。`items` 数组中每个条目携带 19 个字段（见 `SPEC/REMINDERS.md`）；列表名字段是 **`list`**——用 `listName` 过滤项目列表会静默匹配到零条（不报 KeyError）。用 Python 解析：

```python
import json
with open('<snapshot_path>') as f:
    r = json.load(f)

# 关键：priority 字段可能是 int 也可能是 str —— 一律强制转换
def safe_pri(x):
    try: return int(x.get('priority', 0))
    except (ValueError, TypeError): return 0

def pri_mark(p):
    return '🔴' if p >= 9 else ('🟡' if p >= 5 else '')

incomplete = [i for i in r['items'] if not i.get('isCompleted')]
today = '2026-10-21'  # 来自 date 命令

# 把未完成条目归入 5 个桶
habits_daily = []   # recurrenceRule.frequency == 'daily'
overdue = []        # dueDateLocal < today（排除每日习惯）
due_today = []      # dueDateLocal == today
due_future = []     # dueDateLocal > today
no_due = []         # 无 dueDate 且无 recurrenceRule（黑洞候选）

for i in incomplete:
    rec = i.get('recurrenceRule')
    if rec and rec.get('frequency') == 'daily':
        habits_daily.append(i); continue
    due_local = i.get('dueDateLocal', '')
    if not i.get('dueDate') and not rec:
        no_due.append(i)
    elif due_local and due_local[:10] < today:
        overdue.append(i)
    elif due_local and due_local[:10] == today:
        due_today.append(i)
    elif due_local and due_local[:10] > today:
        due_future.append(i)
```

**习惯一致性**（最近 7 天）：对最近 7 个日期中的每一天，统计满足 `completionDateLocal[:10] == 该日期` 且 `title` 属于活跃每日习惯标题集合的条目数。这揭示趋势（例如 19→20→21→22→23 是上升趋势；突然下跌预示中断）。计数可能超过分母（例如 26/25）：每日习惯一旦完成，Apple 会立刻生成一个新的未完成实例，所以一天内完成两次会记录两条同标题完成——把任何超过分母的计数标注为「重复完成」，而不是「>100% 健康度」。

### 日历快照

快照结构为 `{scan_time_utc, scan_time_local, window, total, calendars, items}`。字段是**驼峰命名**（`startDate`、`startDateLocal`、`endDateLocal`、`allDay`、`hasRecurrences`、`recurrenceRule`）——绝不要用蛇形命名查找，否则只会静默返回 None。

```python
with open('<snapshot_path>') as f:
    c = json.load(f)

today = '2026-10-21'  # 来自 date 命令
today_events = [i for i in c['items'] if i.get('startDateLocal', '')[:10] == today]
```

提取三个视图：

1. **今日事件** — 按 `startDateLocal` 排序，展示时间段 + 标题 + 所属日历；以分析时刻为界切分：已结束槽位 = 实际，未开始槽位 = 计划
2. **未来 7 天** — 明天到 +7d 的事件 — 纯计划分配，不是行为
3. **过去 7 天时间账** — 每天事件数 + 标题 — 时间真实花在哪里的实际日志
