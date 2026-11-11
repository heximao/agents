# Calendar Time Semantics

Four principles that govern how calendar durations must be interpreted. Load this before parsing calendar data — analysis that ignores them misreads every duration.

## Calendar time semantics（日历时间语义）

The user's calendar obeys two principles that determine how every duration must be interpreted. Analysis that ignores them misreads the data.

**Principle 1: 30-minute quantization.** Event granularity is 30 minutes. The minimum event is 30 min — a task shorter than 30 min still occupies a 30-min slot. When needed time exceeds the current block, allocation grows by another 30-min block: durations are always ceil(need/30) × 30 min (estimated 25 min → 30; 35-60 min → 60; 70-90 min → 90).

- A duration NOT on the 30-min grid is a data anomaly (created before the rule, or an odd edit) — flag it.
- Calendar time-sums overstate short tasks: a 5-min actual task logs as 30 min. The calendar is a truthful but quantized log, not a stopwatch — use durations for allocation/rhythm analysis, not stopwatch-precision totals.

**Principle 2: plan/log duality（过去=实际用时，未来=计划分配）.** The same calendar carries two different semantics depending on where the slot sits relative to NOW:

- **Past slots (end time < analysis time)** = actual time used — a time log of what really happened; the user edits these to reflect real usage on the 30-min grid.
- **Future slots (end time ≥ analysis time)** = planned allocation — intention, not yet reality.
- An in-progress event (started, not ended) is "actual-so-far" — its duration may still be adjusted when done.

What this means for analysis:

- **Past 7-day accounting = actual behavior.** A system-task event in a past slot is CONFIRMED avoidance behavior — prime hours were actually consumed. This is the strongest possible evidence for Lens 2.
- **Today's remaining slots and next 7 days = plan.** A system-task event there is a RISK that can still be cancelled — flag it preemptively. Never claim a future event as something the user "did".
- **Plan-vs-actual audit (advanced)**: snapshots run 4×/day, so the archive preserves a day's plan→actual evolution — an earlier snapshot (e.g., yesterday 08:00) holds yesterday's plan, a later snapshot holds the final actual state. Diffing the same date across snapshots reveals reschedules, duration edits, renames, dropped/added events: an estimation-accuracy and plan-adherence signal no single view can give.
- **Why no recurring events**: past slots must be standalone records of each day's actual usage — a recurring master row cannot encode per-day variation. This is the rationale of the 2026-10-20 decision to delete all recurring master events and log every occurrence manually.
- **Gap semantics differ past vs future**: a gap in past slots = unrecorded time (rest, meals, untracked activity — not necessarily lost time); a gap in future slots = unplanned time, a planning hole where the day can stall (what Lens 3 flags).

**Principle 3: concurrent events are legitimate（同时段并行是正常的）.** The user can remotely guide one or more AI agents to do tasks while simultaneously doing manual focus work — the calendar may carry two or more events on the same time slot, and that is NOT a scheduling error. Overlap is only a conflict when both events require the user's active simultaneous attention (e.g., two meetings at once, or writing code while on a call). An event like "Cron 跟踪功能通过 Agent 实现" can run in the background while the user writes a resume — both are on the calendar, both are real, neither is an error.

**Principle 4: short routine tasks are NOT on the calendar（不耗时的事不进日历）.** Items that must be done but take negligible time (feeding the cat, brewing tea, signing in to a platform) live in Reminders, not the calendar — a 2-min task would inflate to a 30-min calendar slot (see Principle 1), producing a misleading time record. Their absence from the calendar is correct, not a gap. When scanning for time gaps (Lens 3), remember the gap may contain these short routine tasks — only a gap with no income-track or focus work AND no routine-task fill is a real cliff.
