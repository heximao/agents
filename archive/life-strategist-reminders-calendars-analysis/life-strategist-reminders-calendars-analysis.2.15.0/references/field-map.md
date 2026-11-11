# 字段中英对照（分析速查）

> **定位**：分析时查字段用。只收分析实际会碰的字段，不复制采集规格。
> **采集层权威定义**见 `SPEC/REMINDERS.md`、`SPEC/CALENDARS.md`、`scripts/scan-calendars/README.md`——三者与本节冲突时以它们为准。

## 一、提醒事项快照（`items` 每项 19 字段）

| 字段 | 中文 | 分析用途 | 注意 |
|---|---|---|---|
| `id` | 唯一标识 | 记录身份 | 每日习惯完成即生成**新 ID** |
| `title` | 标题 | **聚合身份**（习惯一致性） | 会被改写，实测 13 个 ID 变过 |
| `list` | 列表名 | 项目列表过滤 | **不是 `listName`**——用错静默匹配 0 条，不报错 |
| `listID` | 列表 ID | — | |
| `priority` | 优先级 | P1 分级 | **可能是 int 也可能是 string**，必须强制转换 |
| `notes` | 备注 | 耗时线索 | |
| `dueDate` | 截止时间（UTC） | — | 需 +8h 转换 |
| `dueDateLocal` | 截止时间（北京时间） | 到期 / 逾期判定 | **一律用它** |
| `dueDateIsAllDay` | 是否全天 | — | |
| `recurrenceRule` | 循环规则 | 习惯识别 | `frequency` 是**字符串**：`daily`/`weekly`/`monthly`/`yearly` |
| `isCompleted` | 是否完成 | **完成判定的唯一依据** | 日历块不回答完成与否 |
| `completionDate` | 完成时间（UTC） | — | |
| `completionDateLocal` | 完成时间（北京时间） | 完成日期归属、7 天趋势 | **一律用它**，用 UTC 会跨日 |
| `creationDate` / `creationDateLocal` | 创建时间 | 记录年龄 | |
| `lastModifiedDate` / `lastModifiedDateLocal` | 最后修改时间 | **变更检测** | 判断「被改过」的唯一字段 |
| `alarmDate` / `alarmDateLocal` | 闹钟时间 | — | |

## 二、日历快照（`items` 每项 26 字段）

| 字段 | 中文 | 分析用途 | 注意 |
|---|---|---|---|
| `id` | 唯一标识 | **对齐身份** | 跨快照稳定；标题不可靠 |
| `title` | 标题 | 内容 | 会被改写，甚至整条换掉（槽位复用） |
| `calendar` | 日历名 | 归属 | `life` / `career` / `打卡` / `hermes` |
| `calendarID` | 日历 ID | — | |
| `calendarType` | 日历类型 | — | `Local` / `CalDAV` / `Subscribed` |
| `startDate` / `startDateLocal` | 开始（UTC / 北京时间） | 时段、日期归属 | **一律用 `startDateLocal`** |
| `endDate` / `endDateLocal` | 结束 | 时长、过去/未来判定 | **一律用 `endDateLocal`** |
| `startTz` / `endTz` | 原始时区串 | — | |
| `allDay` | 是否全天 | 时间账排除 | |
| `hasRecurrences` | 是否循环 | **规则校验** | 用户规则「不建循环日历」，本库**恒为 0**；非 0 即违规 |
| `recurrenceRule` | 循环规则 | **规则校验** | 本库**恒为 `null`**。字段定义上 `frequency` 是整数 1/2/3/4，但实际不会出现（见第三节） |
| `entityType` | 实体类型 | — | 本库恒为 2（事件） |
| `status` | 状态 | — | 整型原样记录 |
| `priority` | 优先级 | — | 整型原样记录 |
| `location` / `locationAddress` | 地点 | — | |
| `description` | 描述 | — | |
| `url` / `UUID` | — | — | |
| `creationDate` / `creationDateLocal` | 创建时间 | 记录年龄 | |
| `lastModifiedDate` / `lastModifiedDateLocal` | 最后修改时间 | **变更检测、计划变更率** | |

## 三、三个必记的坑

1. **日历侧根本不存在循环日程，所以别为「类型不同」写兼容逻辑。** 用户规则明确「不创建任何循环日历日程」，`recurrenceRule` 恒为 `null`、`hasRecurrences` 恒为 `0`。字段定义上日历 `frequency` 是整数 1/2/3/4、提醒事项是字符串 `daily`，知道即可——**这是理论差异，实际永不触发**。正确做法是把它当**断言**：一旦某条日历事件 `hasRecurrences != 0` 或 `recurrenceRule != null`，那是**违反用户规则**，标记为规则违规并建议删除，而不是去解析它的 frequency。
2. **列表名字段是 `list`，不是 `listName`。** 用错不报 KeyError，静默返回 0 条。项目列表过滤失效时先查这个。
3. **UTC 与 Local 成对存在。** 所有日期比较用 `*Local`。用 `*Date` 会差 8 小时，且 22:00 之后的记录会跨到第二天。

## 四、字段 → 透镜映射

| 要回答的问题 | 用哪些字段 |
|---|---|
| 今天到期 / 逾期 | `dueDateLocal` + `isCompleted` + `recurrenceRule.frequency` |
| 习惯一致性（7 天趋势） | `completionDateLocal` + `title`（**按标题聚合**，不按 ID） |
| 今天/某天做了什么 | `startDateLocal` / `endDateLocal` + `title`（按 **ID** 对齐） |
| 任务有没有排时间（透镜 7 正向） | 提醒 `title`/`dueDateLocal` ↔ 日历 `title`/`startDateLocal`/`endDateLocal` |
| 做完了没有（透镜 7 反向） | `isCompleted` + `completionDateLocal` ↔ 日历过去块 |
| 改过几次 / 计划变更率 | `lastModifiedDateLocal` + `id` + `title` |
| 是否循环任务 | 提醒 `recurrenceRule.frequency`；日历 `hasRecurrences`（应恒 0） |
