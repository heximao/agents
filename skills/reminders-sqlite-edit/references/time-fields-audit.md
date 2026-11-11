# Reminders 全库时间字段盘点

盘点时间：2026-11-07 13:20（北京时间，只读盘点，未改动任何数据）
活跃库：`Data-FD471186-91D3-4D36-AF3A-E0CFC882CA68.sqlite`
规模：26 张表；`ZREMCDREMINDER` 528 行 / 58 列；`ZREMCDOBJECT` 1240 行 / 138 列。

## 0. 换算口径

- 所有 `TIMESTAMP` 列存 **Core Data epoch 秒**（2001-01-01 UTC 起），转北京时间 `+978307200` 再 `+8h`。
- 判断「同一天」必须用北京自然日 `to_bj(ts).date()`，用 UTC 日界 `ts//86400` 会退回前一天。
- **全天事项的 `ZDUEDATE` 是日期锚点「当天 08:00 北京 / 00:00 UTC」，不是真实 deadline**。全库大量看似异常的时间线都源于此，不能按具体时刻事项的口径去「修」。
- 闹钟触发时刻不在时间戳列里，而在 `ZREMCDOBJECT.ZDATECOMPONENTSDATA` 的 JSON 日历组件，需按 JSON 自带 `timeZone` 回算。

## 1. 五层框架（决定「要不要处理」的依据）

| 层 | 内容 | 是否进入分析链路 | 处理原则 |
|---|---|---|---|
| L1 | 导出层采集字段 | **是**，直接决定周报/月报数字 | 改动前必须双层验证（SQLite + `remindctl`） |
| L2 | 库内业务/显示字段 | 否（`remindctl` 不导出） | 只影响库内语义，可按口径清理 |
| L3 | 子对象（闹钟/循环/确认） | 间接（决定 `alarmDate`、`isHabit`） | 联动改，不能只改主表 |
| L4 | 系统内部与同步 | 否 | **禁止手改**：`ATRANSACTION`、CloudKit 状态、`Z_OPT`、`Z_ENT`、父表 `ZCREATIONDATE` |
| L5 | 空表预留字段 | 否 | 无需处理 |

采集链路：`remindctl all --json` → `scripts/scan-reminders/scan_reminders.py` 的 `build_items()` → 快照 `items` 层。搬运的时间字段只有：
`dueDate` / `dueDateLocal` / `dueDateIsAllDay` / `completionDate` / `completionDateLocal` / `creationDate` / `creationDateLocal` / `lastModifiedDate` / `lastModifiedDateLocal` / `alarmDate` / `alarmDateLocal` / `recurrenceRule` / `isCompleted`。
**`startDate`、横幅痕迹、显示日期镜像、时区列一律不进快照。**

## 2. `ZREMCDREMINDER` 逐列清单（528 行）

### 2.1 TIMESTAMP 列（8 个）

| 列名 | 非空 | 最早 | 最晚 | 层 | 语义 |
|---|---|---|---|---|---|
| `ZCREATIONDATE` | 528 | 2025-09-10 21:32 | 2026-12-25 07:00 | L1 | 记录何时创建；EventKit 只读，故需直改 SQLite |
| `ZLASTMODIFIEDDATE` | 528 | 2026-10-15 23:38 | 2026-12-25 07:00 | L1 | 最后改动；系统会在真实改动时自动刷新 |
| `ZDUEDATE` | 513 | 2026-10-17 08:00 | 2027-12-31 08:00 | L1 | 截止时间（全天项为 08:00 锚点） |
| `ZCOMPLETIONDATE` | 81 | 2026-10-20 16:15 | 2026-11-07 21:30 | L1 | 完成时间 |
| `ZDISPLAYDATEDATE` | 513 | 2026-10-17 00:00 | 2027-12-31 00:00 | L2 | 显示日期镜像；全天项恒比 `ZDUEDATE` 早 8h |
| `ZSTARTDATE` | 148 | 2026-05-23 14:00 | 2026-11-18 13:00 | L2 | 任务计划开始日；可空；`startDateComponents` 可读写 |
| `ZLASTBANNERPRESENTATIONDATE` | 465 | 2026-10-15 23:37 | 2026-11-07 12:37 | L2 | 最近一次横幅展示 |
| `ZALTERNATIVEDISPLAYDATEDATE_FORCALENDAR` | 0 | — | — | L5 | 预留，全空 |

### 2.2 非时间戳但影响时间解释的列

| 列名 | 非空 | 实测分布 | 作用 |
|---|---|---|---|
| `ZALLDAY` | 528 | 0=293 / 1=235 | 间接决定导出 `dueDateIsAllDay` |
| `ZDISPLAYDATEISALLDAY` | 528 | 0=297 / 1=231 | 显示侧全天标记 |
| `ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT` | 528 | 28800=527 / -28800=1 | 显示时区偏移 |
| `ZDISPLAYDATETIMEZONE` | 279 | Asia/Singapore 278 / America/Los_Angeles 1 | 显示时区名 |
| `ZTIMEZONE` | 285 | Asia/Singapore 283 / America/Los_Angeles 1 / Asia/Shanghai 1 | **独立列**；为空会让导出 `dueDate` 早 8h（历史 bug） |
| `ZDUEDATEDELTAALERTSDATA` | 0 | BLOB，全空 | 相对截止的提前提醒 |

### 2.3 与完成状态配套
`ZCOMPLETED`（非时间列）：有完成时间必须为 1。全库 81 条完成时间 / 81 条完成标记一致，0 条错配。

## 3. `ZREMCDOBJECT` 子对象（1240 行）

实体类型（`Z_PRIMARYKEY` 映射）：`Z_ENT=16` REMCDAlarm 292、`18` REMCDAlarmDateTrigger 287、`35` REMCDRecurrenceRule 123、`31` AuxiliaryChangeMoveInfo 500、`30` ChangeDeleteInfo 24、`34` ManualSortHint 6、`19` AlarmLocationTrigger 5、`33` Hashtag 2、`15` Account 1。

| 字段 | 实测 | 层 | 说明 |
|---|---|---|---|
| `ZDATECOMPONENTSDATA` | BLOB JSON，287 个 trigger | L3 | **导出 `alarmDate` 的真源**；含年月日时分 + `timeZone.identifier` |
| `ZACKNOWLEDGEDDATE` | 40 行，2026-04-25 ~ 11-07 | L3 | 闹钟确认痕迹 |
| `ZCREATIONDATE` | 2 行 | L4 | 父表字段，对提醒事项基本为 NULL，**不要同步改** |
| `ZENDDATE` / `ZASSIGNEDDATE` | 0 / 0 | L4 | 循环结束日、指派时间，全空 |
| `ZFREQUENCY` / `ZINTERVAL` / `ZFIRSTDAYOFTHEWEEK` | 循环规则 123 行全非空 | L3 | 频率分布 `{0:48, 1:37, 2:32, 3:2, 4:4}` |
| `ZDAYSOFTHEWEEK` | 27 行 | L3 | 周循环的具体星期 |
| `ZDAYSOFTHEMONTH` / `ZMONTHSOFTHEYEAR` / `ZDAYSOFTHEYEAR` / `ZWEEKSOFTHEYEAR` | 0 | L5 | 预留 |
| `ZTIMEINTERVAL` / `ZDUEDATERESOLUTIONTOKENASNONCE` / `ZLASTACCESSEDSINCEREFERENCEDATE` | — | L4 | 系统内部计数/令牌 |

## 4. 系统内部表（L4，禁止手改）

| 表.列 | 行数 | 范围 | 说明 |
|---|---|---|---|
| `ATRANSACTION.ZTIMESTAMP` | 13522 | 2026-05-17 13:34 ~ 2026-11-07 12:37 | 变更事务时间戳。裸 SQL 改动**不写** `ACHANGE`，故停留在最后一次 App 操作；禁止伪造 |
| `ZREMCKCLOUDSTATE.ZLOCALVERSIONDATE` | 1186 | 2026-05-28 12:58 ~ 2026-11-07 12:37 | iCloud 本地版本时间，云端旧记录可能覆盖本地改动 |
| `ZREMCDCHANGETRACKINGSTATE.ZLASTCONSUMEDDATE` | 2 | 2026-05-17 13:34 ~ 2026-10-17 16:57 | 变更追踪消费位点 |
| `ZREMCDBASELIST.ZPINNEDDATE` | 1 | 哨兵值 `-63114076800`（约公元 1 年） | 非「未置顶」的 NULL，而是极小值 |
| `ZREMCDBASELIST.ZLASTUSERACCESSDATE` | 0 | — | 列表访问时间 |

另有 10 张空表含 `ZCREATIONDATE` / `ZLASTMODIFIEDDATE` / `ZPUBLICLINKEXPIRATIONDATE` / `ZRECENCYDATE` / `ZTIMEELAPSED` 等预留列（模板、附件、标签、公共链接等），行数均为 0。

## 5. 导出层实测（528 条）

| 字段 | 非空 | 库内来源 |
|---|---|---|
| `creationDate` | 528 | `ZCREATIONDATE` |
| `lastModifiedDate` | 528 | `ZLASTMODIFIEDDATE` |
| `dueDate` | 513 | `ZDUEDATE`（受 `ZTIMEZONE` 解释影响） |
| `completionDate` | 81 | `ZCOMPLETIONDATE` |
| `alarmDate` | 282 | `ZDATECOMPONENTSDATA` 经 EventKit 换算 |
| `dueDateIsAllDay` / `isCompleted` | 布尔 | `ZALLDAY` / `ZCOMPLETED` |

## 6. 全库「异常」与定性（关键：区分真问题与正常形态）

| 现象 | 条数 | 定性 |
|---|---|---|
| `ZDISPLAYDATEDATE != ZDUEDATE` | 231 | **正常**：全部 `ZALLDAY=1`，差值恒为 8h，全天项日期锚点 |
| `ZALLDAY != ZDISPLAYDATEISALLDAY` | 4 | **无影响**：4 条均为无截止、无显示的说明类事项（带「【Agent请跳过】」标记） |
| `ZTIMEZONE` 为空且非全天 | 8 | **无影响**：8 条 `ZDUEDATE` 全为 NULL，不会触发 8h 偏移 bug |
| 无 `REMCDAlarm` 对象 → `alarmDate=null` | 246 | **设计使然**：235 条全天项 + 11 条无截止说明类；所有有具体截止时刻的事项都有闹钟 |
| `创建 > 截止` | 4 | **正常**：全是全天项，当天晚些时候创建、截止日设为当天 |
| `完成 > 截止` | 11 | **混合**：部分是全天锚点，部分是真实逾期（如 `git push invest仓库` 截止 21:00、完成 23:08）——业务事实，不该改 |
| `开始 > 截止` | 1 | **正常**：全天锚点导致 |
| `开始 < 创建` | 17 | 13 条为两轮回填创建时间的副产品 + 4 条历史；库内语义矛盾，**快照不采集** |
| `横幅 > 完成`（已完成项） | 18 | 13 条为真矛盾（回填副产品）；另 5 条是秒级同刻（完成与横幅同一分钟内），系统正常行为 |
| `最后修改 != 创建` | 423 | **正常**：系统默认行为 |
| 闹钟组件 != 截止 | 1（PK=168「吃早餐」） | **导出正确**：组件用 `America/Los_Angeles` 表达北京 11-02 00:00，按自身时区回算绝对值一致 |
| 时区列不统一 | 2（PK=168 / 527） | 导出层 `dueDate`/`alarmDate` 均正确，仅库内标识不统一（LA / `ZDISPLAYDATETIMEZONE=NULL`） |
| 完成时间落在未来 | 1（PK=395） | 上轮「截止前 30 分钟」口径的必然结果（截止 11-07 22:00 → 完成 21:30）|
| 带活跃循环规则 | 53 条事项 | 业务状态，不是异常 |
| `ZACKNOWLEDGEDDATE` 非空 | 40 行 | 历史确认痕迹 |

闹钟对齐复核：有闹钟且非全天的 282 条中，281 条日历组件与截止时间逐字段一致；唯一「不一致」的 PK=168 按自身时区回算也一致。即 **282/282 绝对时刻对齐**。

## 7. 处理决策矩阵

### 可以处理（低风险、只影响库内语义、不进快照）
- 清理 13 条 `ZSTARTDATE`（未完成铲猫砂 7 + 已完成铲猫砂 6 之外的另有 4 条历史 `开始<创建`）——需先确认这些开始日期是否还有业务含义。
- 清理 13 条「横幅 > 完成」的 `ZLASTBANNERPRESENTATIONDATE`。
- 以上若执行，仍走标准流程：备份 → dry-run → 全库副本演练 → 单事务写入 → 差分审计 + 导出层验证。

### 需要业务判断，不宜自动处理
- PK=395 完成时间在未来：要么保留（口径如此），要么把完成时间改为当前真实完成时刻。
- PK=168 / 527 时区列归一到 `Asia/Singapore`：导出层目前正确，改了属于「统一口径」而非修 bug，收益有限、有风险。
- 11 条 `完成 > 截止`：绝大多数是真实逾期，属于业务事实，**应保留**（正是复盘要分析的数据）。

### 明确不该动
- 全天事项的 08:00 锚点相关（231 条显示日期差、235 条无闹钟、4 条 `创建>截止`、1 条 `开始>截止`）。
- 53 条活跃循环规则、40 行确认痕迹、423 条 `最后修改 != 创建`。
- L4 所有系统内部表与 `Z_OPT` / `Z_ENT` / `Z_PRIMARYKEY` / 父表 `ZCREATIONDATE`。
- 4 条全天标记不一致、8 条 `ZTIMEZONE` 为空：都是无截止日期的说明类事项，改了没有收益。

### 口径层面的建议（比改数据更重要）
在 `SPEC/REMINDERS.md` 或分析层明确写一条：**全天事项的 `ZDUEDATE` 08:00 是日期锚点，不是 deadline；判断逾期、创建顺序时必须先按 `dueDateIsAllDay` 分流**。否则以后每次全库体检都会把 231+ 条正常数据误报为异常，也会把真实逾期和锚点混在一起统计。

## 8. 硬约束

- 裸 SQL 不写 `ACHANGE`：Reminders.app 内存缓存可能显示旧值；`remindctl all --json` 只读导出实测能读到磁盘新值。
- 不重启 `remindd`、不改 `TCC.db`、不伪造事务、不删 CloudKit 记录、不同步改父表 `ZCREATIONDATE`。
- 任何 L1 字段改动后必须跑 `verify.py`（十二项语义，仅适用于已完成项）+ `verify_export.py`（导出层）双层验证；未完成项用 `edit_creation.py --verify` / `edit_completion.py --verify`。

## 9. 补充：导出层全天锚点与系统并发写入（2026-11-07 全库归一化实测）

### 9.1 全天事项导出的 `dueDate` 比库内 `ZDUEDATE` 早 8 小时

库内全天事项 `ZDUEDATE` = 当天 08:00 北京，但 `remindctl all --json` 导出的 `dueDate` 是「当天 00:00 北京 = 前一天 16:00 UTC」，恒差 8 小时；`dueDateIsAllDay=true`。这是 EventKit 的日期锚点表达，**不是数据错误**。`verify_export.py::check_export_row` 严格比较绝对时刻会把 231 条全天项全判为失败，另有 4 条无截止说明类事项的 `dueDateIsAllDay`（库内 `ZALLDAY=1`、导出 `false`）误报。

全库核对的正确做法：先按 `ZALLDAY` 分流，全天项把库内 `ZDUEDATE` 减 8 小时再比；无截止事项跳过 `dueDateIsAllDay`。`normalize_timeline.py::shaped_for_export()` 在验收层做这个归一，不改公共验证器。**改前基线 vs 改后主库用同一验证器口径对比，失败数差异必须为 0**（本次实测 235 / 235，差异 0），才能断定改动没引入新的导出层错误。

### 9.2 系统并发刷新的列（`SYSTEM_VOLATILE`）

裸 SQL 写入前后，remindd / Reminders.app / iCloud 会自行改动这些列，差分审计应只提示不判失败：

| 列 | 触发原因 |
|---|---|
| `Z_OPT` | Core Data 内部版本号，每次系统写入递增 |
| `ZLASTMODIFIEDDATE` | 系统真实改动时刷成当前时间 |
| `ZLASTBANNERPRESENTATIONDATE` | 到期提醒弹出横幅 |
| `ZCKSERVERRECORDDATA` / `ZCKCLOUDSTATE` / `ZCKIDENTIFIER` | CloudKit 同步 |
| `ZRESOLUTIONTOKENMAP_V3_JSONDATA` / `ZSPOTLIGHTINDEXCOUNT` | 冲突解决令牌与 Spotlight 索引 |

本次实测 4 条「每天…」循环事项（PK 284/289/290/291）在备份后被系统刷走 `ZLASTMODIFIEDDATE`（14:01）与横幅（13:58），`Z_OPT` 递增多次。带备份补写一次并重新导出后恢复；但**这些事项仍可能被系统再次刷新**，属于 skill 已知不可消除的风险。补写前备份：`pre-lastmod-refresh.sqlite`。

判断系统刷新是否可接受，看语义而不是看值：`ZLASTMODIFIEDDATE >= ZCREATIONDATE` 即不构成倒挂；未完成事项有横幅痕迹也属正常。

### 9.3 2026-11-07 全库归一化结果

用户确认口径：418 条创建时间早于 T=`2026-11-01 07:00` 的全部统一为 T；其中早于 T 的截止/完成整体平移 +15 天；辅助字段对齐 T；全库遗留冲突一并清理。脚本 `scripts/normalize_timeline.py`。

- 写入：445 条主表 UPDATE + 113 条闹钟 JSON UPDATE；全库 528 条不变、`integrity_check=ok`。
- 明细：418 条创建/修改→T；150 条截止与显示日期 +15d；9 条完成 +15d；113 条闹钟组件对齐新截止；122 条 `ZSTARTDATE`→T；22 条横幅→T；范围外清理 17 条遗留开始时间、15 条横幅>完成、1 条修改<创建。
- 改后语义自检：创建<T 残留 0、创建>截止 0、完成<创建 0、开始<创建/开始>截止 0、最后修改<创建 0、横幅>完成 0、非全天显示日期≠截止 0；仅保留 11 条真实逾期（业务事实）。
- 验收：副本演练 0 未通过；主库 445 条差分审计 + 闹钟对齐 + 528 条导出层核对 0 未通过；`test_rdb.py` 48 项 OK。前几轮批次（已完成/未完成铲猫砂、未完成铺床）创建时间保持，遗留冲突已清。
- 备份：`pre-normalize-timeline.sqlite` / `-original.json` / `-changes.json`；完整前后对照 `/tmp/normalize-dryrun.json`。

## 10. 新建事项默认值实测与时间逻辑异常修复（2026-11-07）

### 10.1 用户手动新建 2 条测试事项（PK 529 / 530）

| 字段 | PK 529「未设定任何时间」 | PK 530「手动设定 2026-11-07」 |
|---|---|---|
| `ZCREATIONDATE` | 11-07 14:13 | 11-07 14:14 |
| `ZLASTMODIFIEDDATE` | 11-07 14:13 | 11-07 14:15（真实编辑刷新） |
| **`ZSTARTDATE`** | **NULL** | **NULL** |
| `ZDUEDATE` | NULL | 11-07 08:00（全天锚点） |
| `ZDISPLAYDATEDATE` | NULL | 11-07 00:00（差 8h） |
| `ZLASTBANNERPRESENTATIONDATE` | NULL | 11-07 14:14（创建即写入） |
| `ZALLDAY` / 时区 / GMT | 0 / NULL / 0 | 1 / NULL / 28800 |
| 闹钟 / 循环 | 0 / 0 | 0 / 0 |

**结论：`ZSTARTDATE` 默认 NULL，不是创建时间。** 它是 `EKReminder.startDateComponents`，用户显式设置才有值；系统不会用 `creationDate` 兜底。所以「创建 = 开始」不是天然关系，之前把 `ZSTARTDATE` 对齐到 T 均为人为写入。另：**创建时系统就写横幅痕迹 = 创建时刻**，故「横幅早于闹钟触发」多为正常（全库 183 条中 160 条横幅 >= 创建），只有「横幅 < 创建」才是真倒挂。

### 10.2 全库 530 条时间逻辑体检与修复

脚本 `scripts/fix_time_anomalies.py`，`now=2026-11-07 14:20`。

| 类别 | 条数 | 处理 |
|---|---|---|
| A1 已完成但完成时间在未来 | 8（299/395/417/430/447/454/472/492） | 整体回移截止+闹钟+显示+完成，保持逾期量，压到 now 前并按 PK 错开 30 分钟 |
| A9 横幅 < 创建 | 23（未完成铺床类） | 清空横幅痕迹 |
| A12 确认痕迹 < 创建 | 17（3 已完成 + 14 未完成） | 清空 `ZACKNOWLEDGEDDATE` |
| A1 回移导致横幅 > 完成 | 1（PK 395） | 横幅收敛到完成时刻 |

- 写入 31 条主表 + 25 条对象表；`integrity_check=ok`、全库 530 条。副本演练 0 未通过。
- **整分钟对齐补写**：回移值带秒，而闹钟 JSON 秒归零，导致 6 条快照 `alarmDate != dueDate`。带 `pre-minute-align.sqlite` 备份把 7 条非整分钟列向下取整到分钟，重新导出后全库 530 条导出层 0 未通过。
- 终态：全库语义复检 9 项全 0（未来完成、完成<创建、创建>截止、横幅<创建、横幅>完成、确认痕迹<创建、最后修改<创建、开始<创建、非全天显示镜像）；8 条修复后 `截止 = 闹钟`、完成在过去、逾期量保持（PK299 +26.8h、PK454 +1.0h、PK492 +1.2h、PK395 -0.5h 提前完成）。
- 备份：`pre-fix-time-anomalies.sqlite` / `-original.json` / `-changes.json`；补写备份 `pre-minute-align.sqlite` 及同名快照。
- **明确不修**：全天 08:00 锚点（含 PK 530 创建晚于锚点）、系统新建时的横幅 = 创建时刻、真实逾期、提前完成、用户未设闹钟的非全天项（PK 523/527）、无截止说明类事项的两个全天标记不一致（4 条）。

### 10.3 口径提醒

`ZSTARTDATE` 不进 `remindctl` 导出，任何依赖「开始时间」的分析口径在快照层都不可验证；若需要，必须改采集脚本主动读取并搬运该字段。另外**导出层字段一致 ≠ 值合理**：修复前 8 条未来 `completionDate` 与库内完全一致、核对 0 未通过，但逻辑上不成立，必须额外做「值是否落在未来」的语义检查。

## 11. 全库清空 ZSTARTDATE 与最终时间逻辑复查（2026-11-07 14:33）

- 用户指令：`ZSTARTDATE` 有值的重新设置为 NULL，并复查还剩哪些时间逻辑问题。
- 清空前：非空 131 / 530（122 条等于创建、9 条晚于创建、0 条早于创建）；取值集中在 2026-11-01（123 条）。
- 执行：单列 `UPDATE ZREMCDREMINDER SET ZSTARTDATE=NULL WHERE ZSTARTDATE IS NOT NULL`，副本演练 0 未通过 → 主库写入；131 条差分审计 0 未通过、全库 530 条导出层 0 未通过、`integrity_check=ok`、530 条、`test_rdb.py` 48 项 OK。
- **备份注意**：写入命令被环境执行了两次，第二次把 `pre-clear-startdate.sqlite` 覆盖成清空后状态；`pre-clear-startdate-original.json` 保留了 131 行清空前原值。已据此重建完整可回滚备份 `pre-clear-startdate-restored.sqlite`（ZSTARTDATE 非空 131 条、530 行、integrity=ok）。
- **清空后全库语义复检**：ZSTARTDATE 非空 0、已完成但完成在未来 0、完成<创建 0、创建>截止(非全天) 0、横幅<创建 0、横幅>完成 0、最后修改<创建 0、开始<创建 0、开始>截止 0、非全天显示日期≠截止 0、确认痕迹<创建 0、闹钟≠截止 0。
- **曾存在的唯一真问题（已修复）**：`创建 / 最后修改时间在未来` **22 条**（PK 9,13,26,43,63,191,345,399,400,402,403,416,422,426,428,431,453,457,469,491,516,517），全是「铺床」未完成事项，创建 = 各自截止日 07:00，范围 2026-11-08 07:00 ~ 2026-12-25 07:00，21 条创建与截止同日，是早期 `edit_creation.py`「按各自截止日期回填」口径的产物。用户拍板**统一到今天 2026-11-07 07:00**：备份与写入拆成独立命令、写入带幂等条件 `WHERE ZCREATIONDATE > now`、副本演练 0 未通过、22 条差分审计 0 未通过、530 条导出层 0 未通过。备份 `pre-bed-creation-today.sqlite` / `-original.json`。
- **最终状态**：全库 530 条时间逻辑检查**全部归零**——创建在未来 0、最后修改在未来 0、ZSTARTDATE 非空 0、已完成但完成在未来 0、完成<创建 0、创建>截止(非全天) 0、横幅<创建 0、横幅>完成 0、最后修改<创建 0；`integrity_check=ok`、530 条、48 项单测 OK。
- **已定性、不建议修**：4 条无截止说明类事项两个全天标记不一致（6/42/254/267）；PK 168 闹钟用 `America/Los_Angeles`（按自身时区回算绝对值一致、导出正确）；PK 523/527 闹钟 JSON 缺 `timeZone`（`components_to_epoch` 返回 None，但导出层仍正确）。
- **业务事实（保留）**：真实逾期 11 条、提前完成 70 条、全天项无闹钟 236 条、未完成且截止在未来 281 条。
- 校验踩坑：`backup_store` 的 `-original.json` 把 BLOB 存成 `{"__hex__": ...}`，差分前必须 `bytes.fromhex()` 还原，否则会误报所有含 BLOB 的行（本次一度误报 131 条）。

## 12. 横幅时间语义与 11-06「喂猫」4 条回填（2026-11-07）

### 12.1 `ZLASTBANNERPRESENTATIONDATE` 不是业务时间

全库 530 条实测分布：

| 形态 | 条数 |
|---|---|
| 「其它时刻」（不等于任何业务锚点） | 397 |
| NULL | 102 |
| = 创建时间 | 22 |
| = 闹钟触发 | 8 |
| = 完成时间 | 1 |

有闹钟的项里：早于闹钟 160、晚于闹钟 21、等于闹钟 8。结论：它是**系统「最近一次展示横幅通知」的行为日志**，由创建、到期提醒弹出、用户查看/编辑、后台刷新等事件写入，**不固定介于任何两个业务时间之间**。新建 PK 530 实测横幅 = 创建 +21 秒。

人为自洽约束只有两条：**不早于创建**；**对已完成事项不晚于完成**（未完成则不晚于现在）。即已完成 `[创建, 完成]`、未完成 `[创建, 现在]`。当前 11 条已完成有横幅的全在前者、417 条未完成的全在后者。`ZACKNOWLEDGEDDATE`（确认痕迹）在「完成早于闹钟触发」的口径下取任何值都不自洽，应清空。

### 12.2 11-06「喂猫」4 条

用户口径：11-06 需 4 条、原均未完成的改为已完成；最后编辑 = `11-06 07:00`；截止与闹钟 = `08:00 / 12:00 / 18:00 / 22:00`；完成 = 截止前 30 分钟。经确认：**从 11-05 挪 PK 131 补 12:00**、4 条创建统一 `11-06 07:00`、痕迹落在合理区间（横幅 = 创建时刻，确认痕迹清空）。

只读探查：11-06 原只有 3 条（PK 476 08:00、329 18:00、466 22:00），全部创建 = 修改 = 11-01 07:00、未完成、闹钟 = 截止、时区 Asia/Singapore、无循环、ZSTARTDATE NULL；PK 131 原为 11-05 12:00 未完成占位。4 条横幅/确认痕迹均晚于新完成时间（PK 131 横幅 11-05 21:30 甚至早于新创建）。

新增 `scripts/complete_planned_batch.py`；写入 4 条主表 + 4 条闹钟 JSON + 4 条确认痕迹清空。终态：

| PK | 创建=修改=横幅 | 截止=闹钟 | 完成 |
|---|---|---|---|
| 476 | 11-06 07:00 | 08:00 | 07:30 |
| 131（从 11-05 挪来） | 11-06 07:00 | 12:00 | 11:30 |
| 329 | 11-06 07:00 | 18:00 | 17:30 |
| 466 | 11-06 07:00 | 22:00 | 21:30 |

4 条均 `ZCOMPLETED=1`、`ZACKNOWLEDGEDDATE=NULL`、`ZSTARTDATE=NULL`、横幅落在 `[创建, 完成]` 下界。

验证：副本演练 0 未通过；主库 4 条差分/闹钟/时序/导出层 0 未通过；全库 530 条导出层 0 未通过；`integrity_check=ok`、530 条、48 项单测 OK。备份 `pre-feeding-1106-independent.sqlite`（独立生成，避免重跑覆盖）及 `pre-feeding-1106.sqlite` / `-original.json` / `-changes.json`。

**日期分布变化**：11-05 由 8 条减为 7 条（4 已完成 + 3 未完成占位，少一条 12:00 未完成）；11-06 由 3 条补为 4 条（8/12/18/22 全已完成）；11-07 仍 3 条（8/18/22 未完成）。若后续要补 11-07 的 12:00，需另行拍板来源。
