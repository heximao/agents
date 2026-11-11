# Apple Reminders 底层 SQLite 数据模型

> 基于 macOS 本机实测（2026-11-07）。Core Data 是私有 schema，系统升级可能改列名；
> 每次操作前用 `PRAGMA table_info(...)` 复核，脚本里也已做动态列检查。

## 1. Store 位置与活跃库

```
~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-<UUID>.sqlite
```

同目录通常有 4 个 store，只有一个是活跃主库，其余接近空表。按 `ZREMCDREMINDER` 行数取最大值，不要按文件修改时间判断。

本机实测：

| store | ZREMCDREMINDER | 说明 |
|---|---|---|
| `Data-FD471186-91D3-4D36-AF3A-E0CFC882CA68.sqlite` | 528 | 活跃主库 |
| 其余 3 个 | ~0 | 基本为空 |

关联文件 `-wal` / `-shm`，库处于 WAL 模式。备份要用 SQLite 在线 backup API，不要 `cp`。

## 2. 时间值：Core Data epoch

所有 TIMESTAMP 列是 **2001-01-01 UTC 起算的秒数**（可为浮点），与 Unix epoch 相差 `978307200`。

```sql
-- 转成北京时间
SELECT datetime(ZDUEDATE + 978307200, 'unixepoch', '+8 hours') FROM ZREMCDREMINDER;
```

```python
EPOCH = 978307200
TZ = timezone(timedelta(hours=8))
to_bj = lambda ts: datetime.fromtimestamp(ts + EPOCH, TZ)
to_cd = lambda d:  int(d.timestamp()) - EPOCH   # d 为 UTC+8 aware datetime
```

**日界陷阱**：`ts // 86400` 是 UTC 日界（北京 08:00 换日），不能用它判断「同一天」。必须用 `to_bj(ts).date()`。07:00 创建、08:00 截止在正常计划里是同一天，用 UTC 日界会误判。

**绝对时刻 vs 人类可读时间**：库里只存绝对 epoch 秒，不带时区。北京时间 `2026-11-01 07:00` 落盘后对应的 UTC 是 `2026-10-31 23:00`，这是正确结果而非时区错误。校验时统一用 `rdb.cd(y,m,d,h,mi)` 生成期望值再逐列比对，别拿 UTC 字符串去对北京时间。

**全天事项的陷阱**：`ZALLDAY=1` 的事项没有时区，`ZDUEDATE` 是「当天 00:00 UTC / 08:00 北京」的日期锚点，`ZDISPLAYDATEDATE` 是当天 00:00 北京。把 `HH:MM` 时刻写进这类行而不关全天标记，系统会按日期重新解释，造成 8 小时错位。改为具体时刻时同时写：

```sql
ZALLDAY=0, ZDISPLAYDATEISALLDAY=0,
ZDISPLAYDATETIMEZONE='Asia/Singapore',
ZTIMEZONE='Asia/Singapore',
ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT=28800
```

**两个时区列不是一回事**：`ZDISPLAYDATETIMEZONE` 管「显示」，独立列 `ZTIMEZONE` 管 `ZDUEDATE` 如何被解释成绝对时刻。2026-11-07 用 `remindctl all --json` 对全库 528 条做实测：

| `ZTIMEZONE` | `ZALLDAY` | 导出 `dueDate` 相对库内绝对时刻的偏移 | 条数 |
|---|---|---|---|
| 已设（Asia/Singapore 等） | 0 | 0 小时 | 227 |
| NULL | 0 | **-8 小时** | 35 |
| NULL | 1 | -8 小时（全天日期锚点，属正常） | 251 |

漏写 `ZTIMEZONE` 时，EventKit 把 `ZDUEDATE` 的绝对 epoch 秒当成 UTC+8 墙上时间再换算一次（例：库内 `2026-11-01 21:00 北京 / 13:00Z` 导出成 `2026-11-01T05:00:00Z`），而同一事项的 `alarmDate` 仍正确，于是快照里出现「闹钟 ≠ 截止」。**SQLite 层任何体检都看不出这个错误**，必须用 `verify_export.py` 对照导出。

**按截止日期推导其他时间**：需求常写成「根据截止日期把创建/最后修改时间改成当天 7 点」。日期必须取 `to_bj(ZDUEDATE).date()`（北京自然日），时刻由需求指定，用 `rdb.creation_from_due(due_ts, "07:00")` 生成绝对 epoch 秒。全天事项的 `ZDUEDATE` 是「当天 08:00 北京 / 00:00 UTC」，用 `ts // 86400` 会退回前一天；具体时刻事项同理不能按 UTC 日界切。这类「只改两列」的需求用 `edit_creation.py`，不要用会连带改完成标记与闹钟的 `edit_times.py`。

## 3. `ZREMCDREMINDER` 关键字段

EventKit 快照里的 `creationDateLocal` / `lastModifiedDateLocal` / `dueDateLocal` / `completionDateLocal` 都来自这张表。

| 字段 | 含义 / 注意 |
|---|---|
| `Z_PK` | 主键，脚本里所有「事项标识」都指它 |
| `ZTITLE` `ZLIST` | 标题；列表外键 → `ZREMCDBASELIST.Z_PK` |
| `ZCREATIONDATE` | 创建时间（真源） |
| `ZLASTMODIFIEDDATE` | 最后修改时间（真源） |
| `ZDUEDATE` | 截止时间的绝对时间点 |
| `ZDISPLAYDATEDATE` | `ZDUEDATE` 的显示镜像，必须一起改 |
| `ZCOMPLETIONDATE` | 完成时间 |
| `ZCOMPLETED` | 有完成时间必须为 1 |
| `ZSTARTDATE` | 开始时间；若早于创建时间会破坏时间线 |
| `ZLASTBANNERPRESENTATIONDATE` | 最近一次横幅展示时间；完成后还有值不合理 |
| `ZALLDAY` `ZDISPLAYDATEISALLDAY` | 全天标记。写 `HH:MM` 具体时刻必须置 0 |
| `ZDISPLAYDATETIMEZONE` | 显示时区名。全天事项为 NULL；有时间的事项本机用 `Asia/Singapore`（UTC+8） |
| `ZTIMEZONE` | **独立列**，决定 `ZDUEDATE` 的绝对时刻如何被 EventKit 解释；为 NULL 时导出 `dueDate` 早 8 小时。具体时刻事项必须写 UTC+8 标识 |
| `ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT` | 与显示时区配套，UTC+8 为 `28800` |
| `ZIDENTIFIER` | BLOB；`hex()` 后等于快照 `id` UUID 去横线 |
| `ZDACALENDARITEMUNIQUEIDENTIFIER` | 带横线 UUID 字符串 |
| `ZPARENTREMINDER` `Z15REMINDERS` | 循环/父子母本关联，带这些的不要直接改 |
| `ZMARKEDFORDELETION` | 软删除标记 |
| `ZCKSERVERRECORDDATA` | CloudKit 服务端记录快照，非空说明有 iCloud 同步 |
| `Z_OPT` | Core Data 乐观锁版本号，快照不读，不要清 |

**父子实体**：`ZREMCDOBJECT` 是 Core Data 父实体表，`ZREMCDOBJECT.ZCREATIONDATE` 对提醒事项基本为 NULL，EventKit 暴露的时间来自 `ZREMCDREMINDER`。不要去同步改父表的时间列。

## 4. 列表

```sql
SELECT Z_PK, ZNAME FROM ZREMCDBASELIST
WHERE ZNAME='life' AND COALESCE(ZMARKEDFORDELETION,0)=0;
-- 本机 life => Z_PK=2
```

`ZIDENTIFIER` 是 BLOB UUID，名字列是 `ZNAME`（不是 `ZTITLE`）。

## 5. 子对象关联链（都在 `ZREMCDOBJECT` 里）

实体类型由 `Z_ENT` 区分，名称查 `Z_PRIMARYKEY`：

```sql
SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY WHERE Z_ENT IN (16,18,35);
-- 16 REMCDAlarm | 18 REMCDAlarmDateTrigger | 35 REMCDRecurrenceRule
```

### 闹钟

```
ZREMCDOBJECT a  (Z_ENT=16, ZREMINDER = <rem.Z_PK>)
    └─ a.ZTRIGGER ──> ZREMCDOBJECT t (Z_ENT=18, ZALARM = a.Z_PK 反向指回)
                          └─ t.ZDATECOMPONENTSDATA : JSON 日历组件
```

```sql
SELECT a.Z_PK AS alarm_pk, a.ZTRIGGER AS trigger_pk,
       a.ZACKNOWLEDGEDDATE, t.ZDATECOMPONENTSDATA
FROM ZREMCDOBJECT a
LEFT JOIN ZREMCDOBJECT t ON t.Z_PK = a.ZTRIGGER
WHERE a.Z_ENT=16 AND a.ZREMINDER = ?;
```

`ZDATECOMPONENTSDATA` 示例（BLOB 存 JSON 文本）：

```json
{"timeZone":{"identifier":"Asia/Singapore"},"era":1,"day":1,
 "minute":0,"year":2026,"second":0,"hour":8,"nanosecond":0,"month":11}
```

要点：

- 这是**日历组件**不是时间戳。`Asia/Singapore` 与 `Asia/Shanghai` 均为 UTC+8，与北京时间同偏移。
- 改的时候覆盖 `year/month/day/hour/minute`，把 `second`/`nanosecond` 归零，保留 `era` 等其它键；**`timeZone` 必须归一**：非 UTC+8 / 缺失 / 非法的标识一律替换为 `Asia/Shanghai`，已有 UTC+8 标识保留。本机 267 个 trigger 实测分布为 `Asia/Singapore` 227、`Asia/Shanghai` 36、无 `timeZone` 3、`America/Los_Angeles` 1——只改组件不改时区会让那条 LA 闹钟产生 15 小时错位。
- 校验要做两遍且相互独立：组件与目标时刻一致，**且组件按 `timeZone.identifier` 指向的真实时区回算成 epoch 秒后等于目标时刻**。旧版硬编码 UTC+8 回算，等于把时区错位的可能性绕过去了；只比格式化字符串会漏掉 8 小时偏差。
- `ZACKNOWLEDGEDDATE` 在 alarm 行上，不为空表示「用户确认过闹钟」，完成后还有值不合理。
- `ZIDENTIFIER` 上有 **UNIQUE 索引** `Z_REMCDObject_UNIQUE_identifier`；`ZCKIDENTIFIER` 只有普通索引。
- `Z17_TRIGGER` 是 trigger 实体类型的冗余列：date trigger 为 18，location trigger 为 19。
- `Z_FOK_REMINDER=2048` 是外键排序键，现存 alarm 行固定该值。
- `ZMARKEDFORDELETION` 现存行均为 0 或 1（无 NULL），且有 `Z_REMCDObject_byConcealed` 索引以它打头，新对象要显式写 0。

### 没有闹钟时新建一对对象

库里「签到」类事项常常完全没有 `REMCDAlarm`。要补一个时间闹钟，需要在 `ZREMCDOBJECT` 里插入两行（单表继承，`Z_ENT` 区分类型）：

```sql
-- alarm_pk / trigger_pk 来自 next_object_pk()，且必须同步推进 Z_MAX
INSERT INTO ZREMCDOBJECT
 (Z_PK,Z_ENT,Z_OPT,ZACCOUNT,ZREMINDER,ZTRIGGER,Z17_TRIGGER,
  Z_FOK_REMINDER,ZMARKEDFORDELETION,ZCKIDENTIFIER,ZALARMUID,ZIDENTIFIER)
VALUES (?,16,1,?,?,?,18,2048,0,?,?,?);
--              ^ ZREMINDER=提醒事项 Z_PK, ZTRIGGER=trigger_pk
INSERT INTO ZREMCDOBJECT
 (Z_PK,Z_ENT,Z_OPT,ZACCOUNT,ZALARM,ZMARKEDFORDELETION,
  ZCKIDENTIFIER,ZIDENTIFIER,ZDATECOMPONENTSDATA)
VALUES (?,18,1,?,?,0,?,?,?);
--              ^ ZALARM=alarm_pk
UPDATE Z_PRIMARYKEY SET Z_MAX=<最大新主键> WHERE Z_ENT=14;
```

要点：

- `ZIDENTIFIER` 是 16 字节 BLOB（`uuid.UUID(s).bytes`）；`ZCKIDENTIFIER` / `ZALARMUID` 是同一 UUID 的带横线大写字符串形式。每个对象用**新的随机 UUID**，否则撞唯一索引。
- 主键由 `Z_PRIMARYKEY` 中父实体 `Z_ENT=14 / REMCDObject` 的 `Z_MAX` 统一分配；子实体 `Z_ENT=16`、`18` 的 `Z_MAX` 都是 0。取 `MAX(ZREMCDOBJECT.Z_PK)` 与 `Z_MAX` 的较大者再加 1。
- 新对象**不写** `ZCKSERVERRECORDDATA` / `ZCKCLOUDSTATE` / `ZCKDIRTYFLAGS`，做纯本地待同步对象；复制别的对象的云端记录会造成错配。
- 全部 INSERT 与主表 UPDATE 放在同一事务里。事务失败一并回滚，不会留下「有 alarm 没 trigger」的半截状态。

### 循环规则

```
ZREMCDOBJECT (Z_ENT=35, ZREMINDER4 = <rem.Z_PK>)
    ├─ ZFREQUENCY / ZINTERVAL / ZOCCURRENCECOUNT
    └─ ZMARKEDFORDELETION
```

```sql
SELECT Z_PK, ZREMINDER4, ZMARKEDFORDELETION, ZFREQUENCY, ZINTERVAL
FROM ZREMCDOBJECT WHERE Z_ENT=35 AND ZREMINDER4=?;
```

用户在 UI 里手动去掉循环后，系统会把 `ZREMINDER4` 清空、行本身保留并打 `ZMARKEDFORDELETION=1`。这是标准的「待同步删除」状态，不算残留，不要删行。此时 `ZREMINDER4 IN (...)` 查询返回 0 行。

## 6. 常用只读 SQL

```sql
-- 挑活跃库 / 计数
SELECT COUNT(*) FROM ZREMCDREMINDER;
SELECT COUNT(*) FROM ZREMCDOBJECT WHERE Z_ENT=16;

-- 按列表 + 标题找目标
SELECT Z_PK, ZTITLE,
       datetime(ZCREATIONDATE       + 978307200,'unixepoch','+8 hours') AS created,
       datetime(ZLASTMODIFIEDDATE   + 978307200,'unixepoch','+8 hours') AS modified,
       datetime(ZDUEDATE            + 978307200,'unixepoch','+8 hours') AS due,
       datetime(ZCOMPLETIONDATE     + 978307200,'unixepoch','+8 hours') AS completed
FROM ZREMCDREMINDER
WHERE ZLIST=2 AND ZTITLE='喂猫' AND COALESCE(ZMARKEDFORDELETION,0)=0
ORDER BY Z_PK;

-- 完整性 / 全库规模
PRAGMA integrity_check;
SELECT COUNT(*) FROM ZREMCDREMINDER;
```

## 7. 写入模板

```sql
PRAGMA busy_timeout=8000;
BEGIN IMMEDIATE;
UPDATE ZREMCDREMINDER
   SET ZCREATIONDATE=?, ZDUEDATE=?, ZCOMPLETIONDATE=?,
       ZLASTMODIFIEDDATE=?, ZCOMPLETED=1,
       ZDISPLAYDATEDATE=?,
       ZALLDAY=0, ZDISPLAYDATEISALLDAY=0,
       ZDISPLAYDATETIMEZONE='Asia/Singapore',
       ZTIMEZONE='Asia/Singapore',
       ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT=28800,
       ZSTARTDATE=NULL, ZLASTBANNERPRESENTATIONDATE=NULL
 WHERE Z_PK=?;
-- 已有闹钟：对齐 JSON；没有闹钟：改为上一节的 INSERT 两行
UPDATE ZREMCDOBJECT SET ZDATECOMPONENTSDATA=?     WHERE Z_PK=?;  -- trigger
UPDATE ZREMCDOBJECT SET ZACKNOWLEDGEDDATE=NULL    WHERE Z_PK=?;  -- alarm
UPDATE Z_PRIMARYKEY   SET Z_MAX=?                 WHERE Z_ENT=14; -- 仅新建对象时
COMMIT;
```

所有语句放在同一个事务里，中途失败 `ROLLBACK`。分开提交会留下半截状态。

## 8. 快照字段 `alarmDate` 的真源

项目快照由 `scripts/scan-reminders/scan_reminders.py` 调用 `remindctl all --json` 后原样搬运字段，分析层只读快照。映射关系（2026-11-07 本机实测）：

| 快照字段 | 底层真源 |
|---|---|
| `id` | `hex(ZREMCDREMINDER.ZIDENTIFIER)`，加横线即 UUID |
| `creationDate` / `lastModifiedDate` | `ZCREATIONDATE` / `ZLASTMODIFIEDDATE` 的绝对 epoch 秒 |
| `dueDate` | `ZDUEDATE`，**但解释方式受 `ZTIMEZONE` 与 `ZALLDAY` 影响**（见第 2 节） |
| `alarmDate` | EventKit `EKAlarm.absoluteDate` ← `ZREMCDOBJECT` 中 `Z_ENT=16 → ZTRIGGER → Z_ENT=18.ZDATECOMPONENTSDATA` 的 JSON；**没有该对象时为 `null`** |
| `dueDateIsAllDay` | `ZALLDAY` / `ZDISPLAYDATEISALLDAY` |
| `isCompleted` | `ZCOMPLETED` |

实例：`ZDATECOMPONENTSDATA` 为 `{"year":2026,"month":11,"day":9,"hour":12,"minute":30,"timeZone":{"identifier":"Asia/Singapore"}}` → `alarmDate="2026-11-09T04:30:00Z"`，与同条 `dueDate` 相同。

两类事项的实测形态，说明「都有闹钟」与「都没闹钟」不是矛盾而是不同批次：

| | 具体时刻事项（喂猫，20 条） | 全天事项（签到，28 条） |
|---|---|---|
| `ZALLDAY` / `ZTIMEZONE` | 0 / `Asia/Singapore` | 1 / NULL（改前） |
| `REMCDAlarm` 数量 | 20 | 0 |
| 快照 `alarmDate` 非空 | 61/61（该标题全部） | 0/28（改前） |

因此「闹钟规则」要验证到导出层：`verify_export.py` 按 `hex(ZIDENTIFIER)` 找到导出条目，核对 `alarmDate` 非空、等于目标绝对时刻、且闹钟规则等于截止时刻时 `alarmDate == dueDate`。只跑 SQLite 层检查会漏掉「库里对、快照里错」的情况。

## 9. 变更追踪表

`ACHANGE` / `ATRANSACTION` 是 Core Data persistent history。裸 SQL `UPDATE` **不会**写这些表（实测事务号只随系统自身活动自然增长）。`ZREMCDCHANGETRACKINGSTATE` 存客户端消费位点。不伪造这些记录；手工拼接事务链会破坏 Core Data 的一致性，见 `risks.md`。
