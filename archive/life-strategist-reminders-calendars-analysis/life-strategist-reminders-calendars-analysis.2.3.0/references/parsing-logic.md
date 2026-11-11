# Parsing Logic

Reusable Python parsing code for both snapshot types. Load this before parsing snapshot JSONs.

### Reminders snapshot

The snapshot is `{scan_time_utc, scan_time_local, total, completed, incomplete, lists, items}`. The `items` array carries 19 fields per item (see `SPEC/REMINDERS.md`); the list-name field is **`list`** — filtering project lists with `listName` silently matches zero items (no KeyError). Parse with Python:

```python
import json
with open('<snapshot_path>') as f:
    r = json.load(f)

# CRITICAL: priority field can be int OR string — always coerce
def safe_pri(x):
    try: return int(x.get('priority', 0))
    except (ValueError, TypeError): return 0

def pri_mark(p):
    return '🔴' if p >= 9 else ('🟡' if p >= 5 else '')

incomplete = [i for i in r['items'] if not i.get('isCompleted')]
today = '2026-10-21'  # from date command

# Classify incomplete items into 5 buckets
habits_daily = []   # recurrenceRule.frequency == 'daily'
overdue = []        # dueDateLocal < today (excluding daily habits)
due_today = []      # dueDateLocal == today
due_future = []     # dueDateLocal > today
no_due = []         # no dueDate AND no recurrenceRule (black hole candidates)

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

**Habit consistency** (last 7 days): for each of the last 7 dates, count items where `completionDateLocal[:10] == date` AND `title` is in the active daily-habit title set. This reveals the trend (e.g., 19→20→21→22→23 is an upward trend; a sudden drop signals a disruption). Counts can exceed the denominator (e.g., 26/25): Apple spawns a new incomplete instance the moment a daily habit is completed, so completing it twice in one day logs two same-title completions — annotate any count > denominator as double-completion, not >100% health.

### Calendar snapshot

The snapshot is `{scan_time_utc, scan_time_local, window, total, calendars, items}`. Fields are **camelCase** (`startDate`, `startDateLocal`, `endDateLocal`, `allDay`, `hasRecurrences`, `recurrenceRule`) — never use snake_case lookups or you get silent None.

```python
with open('<snapshot_path>') as f:
    c = json.load(f)

today = '2026-10-21'  # from date command
today_events = [i for i in c['items'] if i.get('startDateLocal', '')[:10] == today]
```

Extract three views:
1. **Today's events** — sorted by `startDateLocal`, show time range + title + calendar source; split at the analysis time: ended slots are actual, upcoming slots are plan
2. **Next 7 days** — events from tomorrow to +7d — pure planned allocation, not behavior
3. **Past 7 days time accounting** — event count per day + titles — actual time log of how time was really spent
