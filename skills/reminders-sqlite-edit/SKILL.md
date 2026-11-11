---
name: reminders-sqlite-edit
version: 1.9.0
display_name: 修改 Reminders 数据库数据
display_name_zh: 修改 Reminders 数据库数据（底层 SQLite 直改与时间校准）
description: 直接读写 macOS「提醒事项 / Apple Reminders」的底层 Core Data SQLite store，用于批量回填或校准历史数据的时间字段（创建时间、最后修改时间、截止时间、完成时间），以及清理闹钟、循环、横幅、全天标记等关联痕迹。当用户提到「修改 reminders 数据库数据」「改提醒事项的创建时间/修改时间/完成时间」「remindctl 不行」「EventKit 写不了 creationDate」「ZREMCDREMINDER」「Data-*.sqlite」「life 列表 / 喂猫 / 签到 / 铺床 / 铲猫砂」「分别找 7 个 X、Y、Z」「根据截止日期把创建时间改成当天 7 点」「只改创建和最后修改时间」「未完成的事项」「已完成的事项」「改成今天 2026-11-07 的 7 点」「固定日期而不是按截止日期」「全库统一创建时间」「整体平移 15 天 / 推后业务时间」「同时修正冲突 / ZSTARTDATE 冲突」「时间线归一化」「已完成但完成时间在未来」「库内痕迹时间错位 / 横幅 / 确认痕迹」「新建事项 ZSTARTDATE 默认是空还是等于创建时间」「把 ZSTARTDATE 有值的全部设为 NULL / 清空开始时间」「现在还有哪些时间逻辑问题」「横幅时间是什么逻辑 / 介于哪两个时间之间」「喂猫 11-06 补齐 4 条 / 截止 8 12 18 22 点 / 完成时间早 30 分钟」「从别的日期挪一条事项过来」「完成时间改为截止时间前 30 分钟 / 截止前半小时完成」「截止时间 8 点则 7:30 完成、22 点则 21:30 完成」「不能用有循环的」「闹钟时间应该与截止时间相同」「闹钟提醒时间是 21 点」「alarmDate 为空 / 对不上」「快照里闹钟与截止时间不一致」「去除循环」「让最后修改时间等于创建时间」「不要弄错时区与 UTC」「快照对不上 / 当天创建未再修改且截止前完成」时，务必使用本 skill；即使用户没说 skill 名字、只是描述想回填某批提醒事项的历史时间，也应触发。同样适用于只读场景：定位活跃 store、核对字段含义、体检一批事项的语义一致性、验证闹钟与截止时间是否对齐。不适用于单纯新建或勾选提醒事项（走 EventKit/UI 即可；但为回填历史时间而新建属于本 skill 范围），也不适用于 iOS 或 Windows 上的提醒事项。
agent_created: true
---

# 修改 Reminders 数据库数据

## 这个 skill 解决什么

Apple 不公开「提醒事项创建时间」的写入接口。`remindctl` 是 EventKit + 直读 SQLite 的混合实现，EventKit 层拿不到 `creationDate` 的 setter；`osascript` / JXA 同样只能读。所以当分析口径需要一批事项呈现「当天创建、之后没改过、截止前完成」这类历史状态时，唯一可行路径是直接改 `~/Library/Group Containers/group.com.apple.reminders/.../Data-*.sqlite`。

难点不在 `UPDATE` 本身，而在**只改一个字段会让数据在语义上自相矛盾**：创建时间挪到月初，闹钟还挂在月底，横幅展示时间晚于完成时间，循环规则还连着，`ZLASTMODIFIEDDATE` 停在今天——快照一采就露馅。所以本 skill 的核心是一套「主表 + 子对象一起改 → 十二项语义体检 → **导出层 `alarmDate` / `dueDate` 交叉验证** → 全量可回滚」的闭环，而不是一句 SQL。

### 「有没有闹钟」不矛盾：两类事项、两种形态

之前出现过看似冲突的两句结论，其实说的是**两批不同的事项**。先分清，再动手：

| | 「喂猫」类（20 条实测） | 「签到」类（28 条实测） |
|---|---|---|
| 事项形态 | 具体时刻（`ZALLDAY=0`，`ZTIMEZONE` 已设） | 全天（`ZALLDAY=1`，`ZTIMEZONE` 为 NULL） |
| `REMCDAlarm` 对象 | 每条 1 个，共 20 个 | **0 个** |
| 快照 `alarmDate` | 61/61 非空，且 == `dueDate` | 改动前 0/28 非空（全库仅 1 个签到项有） |
| 需要的动作 | 对齐既有 `ZDATECOMPONENTSDATA` | 新建 `REMCDAlarm` + `REMCDAlarmDateTrigger` |

「20/20 闹钟触发时间还是旧日期」讲的是前者需要**改既有闹钟**；「28 条都没有闹钟对象」讲的是后者需要**新建闹钟**。两句话不冲突，也不能互相推广成「事项都有闹钟」或「事项都没闹钟」。`rdb.py --find` 的输出有「闹钟」列，逐批查 `rdb.alarm_chain()` 才是唯一依据。

**`alarmDate` 是本 skill 的最终验收字段**：项目快照由 `scripts/scan-reminders/scan_reminders.py` 调用 `remindctl all --json` 后原样搬运 `alarmDate` / `dueDate` / `creationDate` 等字段；分析层只读快照，不读 SQLite。`alarmDate` 来自 EventKit `EKAlarm.absoluteDate`，真源就是 `ZREMCDOBJECT` 里 `REMCDAlarm → REMCDAlarmDateTrigger.ZDATECOMPONENTSDATA` 的 JSON（本机实测：`2026-11-09 12:30 Asia/Singapore` → `alarmDate=2026-11-09T04:30:00Z`）。没有 `REMCDAlarm` 对象时 `alarmDate` 为 `null`。**只跑 SQLite 层 `verify.py` 会给出假阳性**：库里全绿，快照里闹钟仍为空或 `dueDate` 差 8 小时。所以第 5 步的导出交叉验证是硬性步骤，不是可选补充。

**已修正的时区陷阱（2026-11-07）**：旧版对齐既有闹钟时只改日历组件、保留原 `timeZone`，本机实测存在 `America/Los_Angeles` 及无 `timeZone` 的闹钟，会写出「组件是北京时间、时区是洛杉矶」的 15 小时错位，且 dry-run 前置校验毫无提示。现在 `align_alarm_components()` 会把非 UTC+8 / 缺失 / 非法的时区标识统一归一到 `Asia/Shanghai`，`verify.py` 也改为按闹钟 JSON **自身时区**回算绝对时间戳，形成真正独立的双重校验。

## 职责边界

- 只操作**用户本机、用户明确点名**的那批数据。不扫描式全库改写，不猜目标。
- 单纯「新建一条提醒 / 勾选完成」不用本 skill，走 EventKit 或 UI 即可；新建伴随回填历史时间需求（例如「凑够 20 条历史记录」）时属于本 skill 范围。
- **先备份、先 dry-run、再写入**，顺序不可换。任何写入前把前后值打印给用户看。
- 不用 `remindctl` 写入（用户已验证无效；只读检查其实现是可以的）。
- 不改 `TCC.db`。权限授予只能在系统设置完成，执行环境无法自行取得。不伪造 `ACHANGE` 事务记录，不删 CloudKit 记录；这三类写入会把问题藏起来或引发同步冲突。
- 本 skill 的产出是**数据库状态的改变 + 一份验证报告**，不是新建文件类交付物。

涉及真实数据破坏风险，因此**不做自动端到端评测**：让子代理跑一遍测试 prompt 会真的改写用户数据库。改用脚本内置的 `--dry-run` 默认行为和 `verify.py` 只读体检来做验证，见 `evals/evals.json`。

## 0. 前置条件与权限自检

需要两个彼此独立的 macOS 权限，别混为一谈：

| 权限 | TCC service | 用途 |
|---|---|---|
| 完全磁盘访问 | `kTCCServiceSystemPolicyAllFiles` | 读到 Group Container 里的 `Data-*.sqlite`（**写入必需**） |
| 提醒事项 | `kTCCServiceReminders` | EventKit / `osascript` 读取（**仅用于事后交叉验证，不写入**） |

Full Disk Access 生效后仍可能看到 `kTCCServiceReminders` 为 Denied，这是正常的——不要试图用 SQL 改 TCC，让用户在「系统设置 → 隐私与安全性 → 提醒事项」里手动放行即可。

```bash
STORES="$HOME/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
ls -la "$STORES"          # Operation not permitted => 权限没给到当前进程，先停下问用户
```

后续步骤只在权限自检通过的同一个进程里执行。若被拒，在报告里写明阻塞原因「当前执行环境缺少完全磁盘访问，需在系统设置授予」，并停止本次操作；不反复重试。这是执行环境无法自行取得的系统权限。

## 1. 定位活跃 store

Stores 目录下通常有 4 个 `Data-<UUID>.sqlite`，只有一个是活跃主库，其余近乎空表。按 `ZREMCDREMINDER` 行数取最大的那个，别按文件修改时间猜。

```bash
python3 scripts/rdb.py --locate
```

本机的活跃库是 `Data-FD471186-91D3-4D36-AF3A-E0CFC882CA68.sqlite`（`ZREMCDREMINDER` 528 行）。**每次都要重新确认**，store UUID 会因账号/系统升级变化。

## 2. 先读数据模型再动手

`references/schema.md` 是字段与关联关系的完整清单。动手前至少确认这几条：

- 时间值是 **Core Data epoch**：2001-01-01 UTC 起的秒数，转北京时间用 `datetime(ts + 978307200, 'unixepoch', '+8 hours')`。
- `creationDate` / `lastModifiedDate` / `dueDate` / `completionDate` 的真源是子表 `ZREMCDREMINDER`；父表 `ZREMCDOBJECT.ZCREATIONDATE` 对提醒事项基本是 NULL，**不要去同步改它**。
- `ZDISPLAYDATEDATE` 是 `ZDUEDATE` 的显示镜像，必须一起改。
- UUID 映射：`hex(ZIDENTIFIER)` = 快照 `id` 去掉横线；`ZDACALENDARITEMUNIQUEIDENTIFIER` = 带横线形式。
- 具体时刻（`HH:MM`）的事项必须同时满足 5 列：`ZALLDAY=0` / `ZDISPLAYDATEISALLDAY=0` / `ZDISPLAYDATETIMEZONE='Asia/Singapore'` / **`ZTIMEZONE='Asia/Singapore'`** / `ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT=28800`。`ZTIMEZONE` 和 `ZDISPLAYDATETIMEZONE` 是**两个独立列**，漏掉前者时 `remindctl` 会把 `ZDUEDATE` 的绝对 epoch 秒当成 UTC+8 墙上时间再换算一次，导出的 `dueDate` 恰好早 8 小时，而同一事项的 `alarmDate` 仍正确，于是快照里「闹钟 ≠ 截止」。全库实测：`ZTIMEZONE` 已设 → 偏移 0 小时（227 条）；为 NULL → 偏移 -8 小时（286 条，其中全天事项的 -8 属正常日期锚点）。
- 关联链（子对象都在 `ZREMCDOBJECT` 里）：

```text
闹钟     Z_ENT=16 (REMCDAlarm) AND ZREMINDER=<rem.Z_PK>
           └─ ZTRIGGER → Z_ENT=18 (REMCDAlarmDateTrigger)
                          └─ ZDATECOMPONENTSDATA (JSON 日历组件)
循环     Z_ENT=35 (REMCDRecurrenceRule) AND ZREMINDER4=<rem.Z_PK>
列表     ZREMCDBASELIST.Z_PK ← ZREMCDREMINDER.ZLIST，名字在 ZNAME
对象主键 Z_PRIMARYKEY.Z_ENT=14 (REMCDObject).Z_MAX —— 新建子对象后必须推进
```

## 3. 标准流程（六步）

### 第 1 步：备份（写入前的硬性前置）

```bash
python3 scripts/rdb.py --backup --tag pre-my-edit
```

生成两份东西到 `/tmp/reminders-db-backup-<今天>/`：

- `pre-my-edit.sqlite` —— 用 SQLite 在线 backup API 拿的一致性快照（WAL 环境下比 `cp` 可靠），并校验行数。
- `pre-my-edit-original.json` —— 目标行整行原值，BLOB 字段用 hex 编码保存，用于精确回滚。

备份没成功就别往下走。

### 第 2 步：选目标

按 list 名 + 标题查主键，凑不够才考虑新建：

```bash
python3 scripts/rdb.py --find --list life --title 喂猫
# 多标题：一次查完，每个标题各自取前 N 条
python3 scripts/rdb.py --find --list life \
  --titles "modelscopecn签到,modelscopeai签到,trae签到,workbuddy签到" \
  --exclude-recurring --limit 7
```

`--titles` 接受逗号分隔的多个标题；`--limit` 是**每个标题**的上限；`--exclude-recurring` 在选目标阶段就跳过带活跃循环规则或循环母本的行，并继续往后补足数量（不能等写入后才发现）。输出里带「闹钟」列，`无` 表示该事项没有 `REMCDAlarm` 对象，需要走第 3 步的新建闹钟路径。

本机 `life` 是 `Z_PK=2`，库里有 57 个「喂猫」，取前 20 个即可，**不必新建**。若真需要新建，优先用 EventKit 创建再回填时间（直插 Core Data 表要补十几个非空字段和 `Z_PRIMARYKEY` 计数，风险高得多）。

把选中的主键写进计划 JSON，多标题计划给每个 `target` 各写一个 `title`。选完顺手查一下有没有循环母本（`ZPARENTREMINDER` / `Z15REMINDERS` / `ZMARKEDFORDELETION`），带这些的不要动。

### 第 3 步：写计划 + dry-run（默认）

计划格式见下一节。默认只打印、不写入：

```bash
python3 scripts/edit_times.py --plan /tmp/my-plan.json
```

逐条展示 `Z_PK`、旧值 → 新值（北京时间）、全天/时区校正条数、既有闹钟时区归一条数、需要新建的闹钟对象数。**写入前置条件由执行方自行核对：前置问题为 0、目标主键与 list/title 全部匹配、预计语句条数与计划一致；报告随交付一并展示，让改动可见。** 口径中途调整时（例如「循环我手动去掉了，只管最后修改时间」），改 `rules` 重跑 dry-run，不补写零散 SQL。

计划里凡是包含 `INSERT`（例如原本没有闹钟、需要新建 `REMCDAlarm`）或首次跑通新的联动路径时，先在**全库副本**上做一次端到端演练，再碰主库：

```bash
# 1. 用 SQLite 在线 backup API 拷一份副本
python3 -c "import sqlite3,sys;sys.path.insert(0,'scripts');import rdb;p,_,_=rdb.find_active_store();s=rdb.connect(p);d=sqlite3.connect('/tmp/sandbox.sqlite');s.backup(d)"
# 2. 在副本上写入并体检
python3 scripts/edit_times.py --plan /tmp/my-plan.json --store /tmp/sandbox.sqlite --apply --tag sandbox-pre
python3 scripts/verify.py      --plan /tmp/my-plan.json --store /tmp/sandbox.sqlite
# 3. 副本 0 未通过后，去掉 --store 再对主库执行
```

`--store` 让两个脚本都指向副本，`plan` 文件本身不需要改。副本演练能提前暴露主键冲突、唯一索引冲突和关联链错配。

### 第 4 步：单事务写入

```bash
python3 scripts/edit_times.py --plan /tmp/my-plan.json --apply
```

脚本内部：`PRAGMA busy_timeout=8000` → `BEGIN IMMEDIATE` → 主表 UPDATE → 闹钟 JSON UPDATE → alarm/trigger INSERT → `Z_PRIMARYKEY.Z_MAX` UPDATE → `COMMIT`；任一步异常 `ROLLBACK`。每条操作统一成 `{kind, sql, args}`，`apply()` 按序执行，不再假设「所有语句都是 `UPDATE ... WHERE Z_PK=?`」。不要手写多条裸 `UPDATE` 分开提交，中途失败会留下半截状态。

### 第 5 步：双层体检（SQLite 语义 + 导出层 alarmDate）

```bash
python3 scripts/verify.py        --plan /tmp/my-plan.json
python3 scripts/verify_export.py --plan /tmp/my-plan.json
# 离线核对 / 复用已有导出：
python3 scripts/verify_export.py --plan /tmp/my-plan.json --export /tmp/export.json
python3 scripts/verify_export.py --pks 12,19,24 --export /tmp/snapshot.json
```

两步都是纯只读，且**都要跑**：

- `verify.py` —— 十二项 SQLite 语义体检，目标是 0 未通过 + `integrity_check=ok` + 全库行数不变。
- `verify_export.py` —— 调用 `remindctl all --json`（默认 90 秒超时，只读）或读 `--export` 指定的导出/快照，按 `hex(ZIDENTIFIER)` ↔ 快照 `id` 映射，逐条核对 `alarmDate` / `dueDate` / `creationDate` / `lastModifiedDate` / `isCompleted` / `dueDateIsAllDay`，并在闹钟规则等于截止时刻时强制校验**快照层 `alarmDate == dueDate`**。

`verify_export.py` 专门拦截两类 `verify.py` 看不出的假阳性：库里有闹钟对象但导出 `alarmDate` 为 `null`；`ZTIMEZONE` 为空导致导出 `dueDate` 早 8 小时。`remindctl` 只读调用不算「用 remindctl 写入」，与职责边界不冲突。本机实测该调用能直接读到裸 SQL 改动后的新值，无需重启 `remindd`。

**但这条调用受 `kTCCServiceReminders` 约束，且权限按 client 记账**：2026-11-07 在 WorkBuddy 会话里 `remindctl all --json` 与 `remindctl export` 均返回 `Reminders access denied`（TCC 中 4 个相关 client 全是 `auth_value=2`），而 cron 由另一个有权限的 client 采集的项目快照正常。此时不要重试授权，把 **mtime 晚于写入时刻**的快照路径（如 `reminders/archive/2026/2026-11/2026-11-07/2026-11-07_1700_reminders.json`）喂给 `--export` 即可完成导出层验收；快照早于写入时只能作静态参考。

### 第 6 步：如实告知风险

见 `references/risks.md`。至少要说清三件事：裸 SQL 不写 `ACHANGE`（Reminders.app / 其它 EventKit 客户端的内存缓存可能仍显示旧值，但采集链路读到的是磁盘新值）、iCloud 云端旧记录可能覆盖、新建的闹钟对象是纯本地对象（`ZCKSERVERRECORDDATA` 为 NULL，系统未必上传）。`kTCCServiceReminders` 被拒会同时挡住 `remindctl` 的只读导出，需用写入后的快照替代（见上一段）。不要说「已经完全生效」。

## 4. 计划文件格式

单标题计划：

```json
{
  "list": "life",
  "title": "喂猫",
  "rules": {
    "last_modified": "creation",
    "alarm": "due",
    "display_date": "due",
    "completed": 1,
    "all_day": "off",
    "clear": ["ZSTARTDATE", "ZLASTBANNERPRESENTATIONDATE", "ZACKNOWLEDGEDDATE"]
  },
  "targets": [
    {"pk": 12, "date": "2026-11-01", "create": "07:00", "due": "08:00", "complete": "07:30"},
    {"pk": 19, "date": "2026-11-01", "create": "11:00", "due": "12:00", "complete": "11:30"}
  ]
}
```

多标题计划：每个 `target` 自带 `title`（缺省才回退到计划级 `title`），`verify.py` 也按同一优先级核对：

```json
{
  "list": "life",
  "rules": { "alarm": "21:00", "last_modified": "creation", "all_day": "off" },
  "targets": [
    {"pk": 37, "title": "modelscopecn签到", "date": "2026-11-01",
     "create": "07:00", "due": "21:00", "complete": "10:00"},
    {"pk": 98, "title": "modelscopeai签到", "date": "2026-11-01",
     "create": "07:00", "due": "21:00", "complete": "10:00"}
  ]
}
```

`rules` 的语义：

| 键 | 常用值 | 含义 |
|---|---|---|
| `last_modified` | `creation` / `completion` / `keep` | 目标语义选 `creation`（当天创建后未再修改）；系统默认行为是 `completion` |
| `alarm` | `due` / `"HH:MM"` / `keep` / `none` | **对话未提及闹钟时间时默认 `due`，即闹钟时间 = 截止时间**；用户显式给出时间时写 `"HH:MM"`（北京时间，日期取截止当天） |
| `display_date` | `due` / `keep` | 显示日期镜像，一般恒等于截止时间 |
| `completed` | `1` / `0` / `keep` | 有完成时间就必须为 1；写入与体检共用同一值域，`load_plan()` 会先校验 |
| `all_day` | `off`（默认）/ `keep` | `off` 会清掉全天标记并写入 UTC+8 显示时区；`HH:MM` 计划必须保持 `off` |
| `clear` | 列名数组 | 清掉与时间线矛盾的痕迹 |

`date/create/due/complete` 用北京时间 `HH:MM`。时区口径由 `rdb.py` 统一处理，别在计划里写带时区的时间戳。库里存的是**绝对 Core Data epoch 秒**：北京时间 `2026-11-01 07:00` 对应 `2026-10-31 23:00 UTC`，这是正常的，不是时区错误。反过来说，用 UTC 日界（`ts // 86400`）判断「同一天」一定是错的，必须用 `to_bj(ts).date()`。

### 闹钟规则与「原本没有闹钟」的事项

`alarm` 不在 `keep` / `none` 时，先由 `rdb.alarm_target_ts(due, rule)` 求出目标时刻，再分两条路：

- **已有 `REMCDAlarm`**：把 trigger 的 `ZDATECOMPONENTSDATA` 对齐到目标时刻（保留 `era`，秒与纳秒归零），**并把非 UTC+8 / 缺失 / 非法的 `timeZone` 归一到 `Asia/Shanghai`**，按需清 `ZACKNOWLEDGEDDATE`。dry-run 报告会打印「闹钟时区归一：N 个」。
- **没有 `REMCDAlarm`**：新建一对 `ZREMCDOBJECT` 行 —— `Z_ENT=16` 的 alarm + `Z_ENT=18` 的 date trigger，并把 `Z_PRIMARYKEY` 中 `Z_ENT=14` 的 `Z_MAX` 推到新最大主键。新对象只写最小必要字段、`ZMARKEDFORDELETION=0`，**不复制**任何既有对象的 `ZCKSERVERRECORDDATA`，让它们成为纯本地待同步对象。

`ZIDENTIFIER` 上有 UNIQUE 索引，所以每个新对象的 UUID 必须独立生成。`verify.py` 会额外核对 trigger 存在、`Z_ENT=18`、`Z17_TRIGGER=18`、`ZALARM` 反向指回 alarm。

### 最小改动模式：只回填创建 / 最后修改时间

`edit_times.py` 面向「回填一整套历史时间」，会连带改截止时间、完成时间、完成标记、全天/时区列、闹钟与痕迹。当用户只说「根据截止日期把创建和最后修改时间改成当天 7 点」且事项**仍未完成**时，用它会越过范围（把未完成改成已完成、清掉横幅痕迹）。这类需求走 `scripts/edit_creation.py`，只发一条两列 UPDATE：

```sql
UPDATE ZREMCDREMINDER SET ZCREATIONDATE=?, ZLASTMODIFIEDDATE=? WHERE Z_PK=?
```

计划 JSON（`targets` 省略时自动按 list + title + 未完成筛选）：

```json
{
  "list": "life",
  "title": "铺床",
  "time": "07:00",
  "incomplete_only": true
}
```

**用户点名固定日期**（例如「改成今天 2026-11-07 的 7 点」）时加 `date`，此时**不从 `ZDUEDATE` 取日**：

```json
{
  "list": "life",
  "title": "铲猫砂",
  "date": "2026-11-07",
  "time": "07:00",
  "incomplete_only": true
}
```

```bash
python3 scripts/edit_creation.py --plan /tmp/plan.json              # dry-run
python3 scripts/edit_creation.py --plan /tmp/plan.json --apply --tag pre-bed
python3 scripts/edit_creation.py --plan /tmp/plan.json --verify \
    --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
    --export /tmp/export.json
```

要点：

- **两种日期口径务必分清**（`target_creation()` 统一路由，写入与体检共用）：省略 `date` → 按 `to_bj(ZDUEDATE).date()`（**北京自然日**），时刻由 `time` 指定，纯函数 `rdb.creation_from_due()`；给出 `date` → 用这个固定日期，纯函数 `rdb.creation_on_date()`。全天事项的 `ZDUEDATE` 是「当天 08:00 北京 / 00:00 UTC」，用 `ts // 86400` 会退回前一天。用户说「今天 11-07」而截止日在 11-08~11-14 时，**不能**套用按截止日期推导，否则会写成 7 个不同日期。
- 固定日期模式下仍校验「目标创建时刻早于截止」，并保留 `ZSTARTDATE` 早于新创建时间的提示；报告同时打印「截止日期」与「目标日期」两列，避免把两种口径混在一起看。
- 前置校验：列表/标题匹配、未完成、（可选）无活跃循环、有截止日期、目标创建时刻早于截止。`ZCOMPLETED` / `ZCOMPLETIONDATE` / `ZDUEDATE` / 全天与时区 / 闹钟 / 痕迹**一律不动**。
- `ZSTARTDATE` 早于新创建时间会列入「提示」而非失败项，是否清理由用户另行决定；`--verify` 的差分审计会确认除两列外无任何变化。
- **闹钟规则同样适用**：对话未提闹钟时间时默认闹钟 = 截止时间。实测这批未完成「铺床」22/22 闹钟已等于截止，因此无需改动；若某批不一致，显式用 `edit_times.py` 对齐或另立计划，不在最小改动作业里夹带。
- 副本演练用 `--verify --no-export`（`remindctl` 永远读活跃主库，副本上的导出层数值必然对不上）；**主库验收必须跑完整导出层**，不能跳过。
- `verify.py` 的十二项体检针对「已完成、当天创建、截止前完成」语义，对未完成事项会误报「完成标记」「创建<完成<截止」，不要拿它验收本模式；用 `edit_creation.py --verify`。

### 已完成事项：按截止时间回填三列（创建 / 最后修改 / 完成）

当用户说「把已完成的 X 的创建和最后编辑时间改成当天 7 点，完成时间改成截止时间前 30 分钟」时，用 `scripts/edit_completion.py`。「当天」指**每条事项各自截止日期**的北京自然日（与 `creation_from_due()` 同口径），不是操作当天——否则截止日在往日的事项会出现「完成早于创建」。

计划 JSON（自动筛选 list + title + 已完成，也可显式给 `targets`）：

```json
{
  "list": "life",
  "title": "铲猫砂",
  "create_time": "07:00",
  "complete_offset_minutes": 30,
  "completed_only": true
}
```

```bash
python3 scripts/edit_completion.py --plan /tmp/plan.json --emit-plan /tmp/verify-plan.json  # dry-run
python3 scripts/edit_completion.py --plan /tmp/plan.json --apply --tag pre-litter
python3 scripts/edit_completion.py --plan /tmp/plan.json --verify \
    --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json
python3 scripts/verify.py --plan /tmp/verify-plan.json
python3 scripts/verify_export.py --plan /tmp/verify-plan.json
```

要点：

- 每条只发一条三列 UPDATE：`ZCREATIONDATE` / `ZLASTMODIFIEDDATE` / `ZCOMPLETIONDATE`；截止时间、完成标记、显示日期镜像、全天/时区、闹钟、`ZSTARTDATE`、横幅痕迹**一律不动**。`edit_times.py` 会连带改这些（越界），`edit_creation.py` 只改两列且限定未完成事项。
- 前置校验：列表/标题/已完成/无活跃循环/有截止日期/`创建 < 完成 < 截止`/三条同一北京自然日。`ZSTARTDATE` 早于新创建时间、横幅痕迹晚于新完成时间列为**提示**而非失败项，是否另行清理由用户决定。
- `--emit-plan` 生成 `verify.py` / `verify_export.py` 兼容的计划（`rules.clear=[]`，避免把「按用户要求保留的既有痕迹」误报为失败）。`remindctl all --json` 带 `completionDate`，导出层能端到端验证完成时间。
- 截止时刻可能既有 08:00 又有 22:00，完成时间相应为 07:30 / 21:30。若截止当天就是操作当天且截止时刻未到，完成时间会落在未来，这是用户口径的必然结果，须在报告里如实提示。

### 保持创建时间不变：只校准最后修改 / 完成时间

当用户说「把最后编辑时间改成等于创建时间，完成时间改成截止时间前半小时」，且**创建时间本来就正确、不需要跟着截止日期回填**时，用 `scripts/edit_lastmod_completion.py`。与 `edit_completion.py` 的关键差别：后者把创建时间一并改成截止当天 HH:MM 并要求三条时间同一天；本脚本保留创建时间，允许创建早于完成若干天（例如 11-01 创建、11-06 完成）。

```json
{
  "list": "life", "title": "做俯卧撑",
  "complete_offset_minutes": 30,
  "mark_completed": true, "clear_banner": true,
  "targets": [{"pk": 144, "due": "2026-11-01 10:00"}]
}
```

`targets` 必须显式点名主键；`due` 是可选的交叉校验，与库内 `ZDUEDATE` 不符直接判前置失败。写入列：`ZLASTMODIFIEDDATE=ZCREATIONDATE`、`ZCOMPLETIONDATE=ZDUEDATE-N*60`，可选 `ZCOMPLETED=1` 与 `ZLASTBANNERPRESENTATIONDATE=NULL`；创建/截止/显示镜像/全天与时区/闹钟/`ZSTARTDATE`/确认痕迹一律不动。

`clear_banner` 三档（v1.1.0 起）：`true` 整批清空（v1.0 原有行为）、`false` 不动（默认）、`"problematic"` **仅清空有问题的横幅**。判定口径：已完成事项横幅的合理区间是 `[创建, 完成]`，晚于完成时间或早于创建时间才算异常，NULL 不算问题。用户说「横幅如果有问题就清理」时必须用 `"problematic"`，否则整批清空会越过条件、抹掉本来就自洽的展示日志。dry-run 报告打印「异常 N 条 / 清空 N 条 / 保留 N 条」；纯函数 `banner_problematic()` / `wants_clear_banner()` 已纳入 `test_rdb.py` 回归（51 项）。

**两处口径要先问用户**：① 目标事项若仍是「未完成」，写完成时间必须联动 `ZCOMPLETED=1`，否则快照出现「有完成时间但未标记完成」；② 横幅痕迹若晚于新完成时间，是否清空（横幅是系统展示日志，默认按最小改动保留并列为提示）。2026-11-07 实测 13 条「做俯卧撑」两条都由用户拍板决定。

```bash
python3 scripts/edit_lastmod_completion.py --plan /tmp/plan.json                    # dry-run
python3 scripts/edit_lastmod_completion.py --plan /tmp/plan.json --apply --tag pre-x
python3 scripts/edit_lastmod_completion.py --plan /tmp/plan.json --verify \
    --changes  /tmp/reminders-db-backup-YYYYMMDD/<tag>-changes.json \
    --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
    --export   /Users/<u>/life/reminders/archive/.../YYYY-MM-DD_HHMM_reminders.json
python3 scripts/verify_export.py --pks 144,240,... --export <同一快照>
```

**不要用 `verify.py` 验收本口径**：它的十二项体检假定「当天创建」，本口径创建与完成常不在同一天，会误报「三条时间不同天」。用脚本自带 `--verify`（目标值 + 差分审计 + 导出层）与 `verify_export.py` 双层验收。

### 全库时间线归一化（创建时间统一 + 业务时间整体平移）

当用户说「把库里创建时间早于 X 的事项全部统一为 X，同时修正冲突」时，用 `scripts/normalize_timeline.py`。这是目前唯一面向**全库**（而非按 list/title 选目标）的写入脚本，风险最高，必须先做只读盘点、把冲突规模摊给用户选方案，再动手。

计划 JSON：

```json
{
  "target": "2026-11-01 07:00",
  "shift_days": 15,
  "align_aux_to_target": true,
  "clean_conflicts_outside": true
}
```

```bash
python3 scripts/normalize_timeline.py --plan /tmp/plan.json --detail /tmp/detail.json  # dry-run
python3 scripts/normalize_timeline.py --plan /tmp/plan.json --apply --tag pre-norm
python3 scripts/normalize_timeline.py --plan /tmp/plan.json --verify \
    --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
    --export /tmp/export.json
```

要点：

- **口径必须问清**：「修正冲突」有多种解释。全库实测（2026-11-07）把 418 条创建时间统一到 11-01 07:00 时，其中 150 条截止/完成在 10 月，会变成「未创建先截止/完成」。用户需在「排除这些 / 保留倒挂 / 推后业务时间」之间选择；推后时还要在「整体平移 N 天」与「折叠成统一模式」之间选择。不要猜。
- **整体平移**保留 HH:MM、日期序列与真实逾期关系；同时必须联动 `ZDISPLAYDATEDATE`（保持原有镜像差值）与 `REMCDAlarm` 的 `ZDATECOMPONENTSDATA`（对齐新截止，否则快照 `alarmDate != dueDate`）。
- **全天事项的显示日期不要强行对齐**：它与截止恒差 8 小时，是日期锚点。强行置为目标时刻会破坏镜像关系。
- `--verify` 必须用 `apply` 时落盘的 `<tag>-changes.json` 计划快照，**不能**基于写入后的库重算计划（重算只会看到残余差异，差分审计失真）。
- **导出层要按全天分流**：`check_export_row` 严格比较 `dueDate` 会把 231 条全天项（库内 08:00 锚点 vs 导出 00:00）全判失败。本脚本用 `shaped_for_export()` 在验收层做形态归一，不改公共验证器。全库核对前先跑一次「改前基线 vs 改后」对比，确认失败数差异为 0。
- **系统并发写入**：remindd / iCloud 会在裸 SQL 写入前后自行刷新 `Z_OPT`、`ZLASTMODIFIEDDATE`、横幅痕迹与 CloudKit 列。这些列为 `SYSTEM_VOLATILE`，差分审计只提示不判失败；若系统把目标列刷走（实测 4 条日常循环事项），需带备份补写一次并重新导出验证，且要如实告知用户可能被再次覆盖。
- 产物除数据库改动外还有三份：`--detail` 的完整前后对照、`<tag>-changes.json` 计划快照、一致性备份与原值。

### 时间逻辑异常修复（未来完成时间 + 痕迹倒挂）

当用户说「确保库内痕迹符合时间逻辑，把问题都修正」时，用 `scripts/fix_time_anomalies.py`。它会自动识别并修复三类**逻辑不可能**的状态：

| 类别 | 判定 | 修复 |
|---|---|---|
| A1 | 已完成但 `ZCOMPLETIONDATE > now` | 整体回移「截止 + 闹钟 + 显示日期 + 完成」，保持截止-完成相对关系（真实逾期量不变），按 PK 每条错开 30 分钟压到 now 之前 |
| A9 | `ZLASTBANNERPRESENTATIONDATE < ZCREATIONDATE` | 清空横幅痕迹 |
| A12 | `ZREMCDAlarm.ZACKNOWLEDGEDDATE < ZCREATIONDATE` | 清空确认痕迹 |

```json
{ "now": "2026-11-07 14:20", "safe_buffer_minutes": 60, "stagger_minutes": 30 }
```

```bash
python3 scripts/fix_time_anomalies.py --plan /tmp/plan.json                 # dry-run
python3 scripts/fix_time_anomalies.py --plan /tmp/plan.json --apply --tag pre-fix
python3 scripts/fix_time_anomalies.py --plan /tmp/plan.json --verify \
    --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
    --export /tmp/export.json
```

要点：

- **新时间必须整分钟对齐**（`int(ts)//60*60`）。闹钟 `ZDATECOMPONENTSDATA` 只写到分钟、秒归零；若库内 `ZDUEDATE` 带秒，快照层会出现 `alarmDate != dueDate`（2026-11-07 实测 6 条）。
- 回移后要检查横幅是否变成「晚于完成」，是则把横幅收敛到完成时刻。
- `--verify` 内置**全库语义复检**（未来完成、完成<创建、创建>截止、横幅<创建/横幅>完成、确认痕迹<创建、最后修改<创建、开始<创建、非全天显示镜像），每一项都应为 0。
- **不要修**这几类正常形态：全天事项 08:00 日期锚点；系统新建时写入的「横幅 = 创建时刻」；真实逾期；提前完成；用户没设闹钟的非全天项；无截止说明类事项的两个全天标记不一致。

### 新建事项的时间字段默认值（本机实测 2026-11-07）

用户手动新建 2 条测试事项（PK 529 无任何时间、PK 530 设全天日期）后实测：

- **`ZSTARTDATE` 默认是 NULL，不是创建时间**。它是用户显式设置的业务字段（`EKReminder.startDateComponents`），系统不会拿 `creationDate` 兜底。因此「创建 = 开始」不是天然成立的关系，之前几轮把 `ZSTARTDATE` 对齐到 T 都是人为写入。
- `ZCREATIONDATE` / `ZLASTMODIFIEDDATE` 由系统写入；真实编辑会把后者刷新到当前时间（PK 530 创建 14:14、修改 14:15）。
- 设了全天日期时：`ZDUEDATE` = 当天 08:00 北京锚点、`ZDISPLAYDATEDATE` = 当天 00:00（差 8 小时）、`ZALLDAY=1`、时区列为 NULL、GMT 偏移 28800、**没有 `REMCDAlarm` 对象**。
- **创建时系统就会写 `ZLASTBANNERPRESENTATIONDATE = 创建时刻`**（PK 530 为 14:14）。所以「横幅早于闹钟触发」是普遍的正常行为（全库 183 条中 160 条横幅 >= 创建），只有「横幅 < 创建」才是真倒挂。

**全库清空 `ZSTARTDATE`（2026-11-07 用户指令）**：把 131 条非空值全部置 NULL（122 条等于创建、9 条晚于创建、0 条早于创建），单列 UPDATE + 备份 + 副本演练 + 差分审计。`ZSTARTDATE` 不进导出层，清空后 530 条导出层仍 0 未通过。

**随后把 22 条「铺床」的创建/最后修改时间统一到今天 11-07 07:00**（PK 9,13,26,…,517；原值 = 各自截止日 07:00，落在 11-08 ~ 12-25，是早期「按各自截止日期回填」口径的产物）。幂等单事务写入（`WHERE ZCREATIONDATE > now`，避免命令重跑造成二次改动）；改后**全库时间逻辑检查全部归零**：创建/修改在未来 0、ZSTARTDATE 非空 0、未来完成 0、各类倒挂 0，530 条导出层 0 未通过。

写入命令若被环境重复执行，务必把**备份生成**与**写入**拆成两个独立命令，否则第二次会用「已写入后」的库覆盖备份；写入 SQL 加幂等条件也能防止重复改动。

**实测案例（2026-11-07 17:58，吃早餐 7 条）**：主库 `--apply` 带「Sandbox bypassed / escalation-approved」提示被环境执行了两次，第二次的 dry-run 报告显示「修改(旧)已等于创建、完成(旧)已等于目标、标记 1→1、横幅异常 0 条」——这就是幂等重跑的识别特征。此时 `<tag>.sqlite` / `<tag>-original.json` / `<tag>-changes.json` 已被覆盖成**写入后**状态，既不能回滚，差分审计也失真（`changes` 里连横幅列都没了）。处置：① 回滚点只用独立的 `pre-*-readonly.sqlite`（写入前生成，未被覆盖）；② 改用**副本演练前**落盘的 `sandbox-*-changes.json`（完整计划，含横幅列）与 `sandbox-*-original.json`（写入前整行原值）对主库跑 `--verify`，即可恢复完整目标值校验与差分审计；③ 在报告里如实说明，不要拿被覆盖的三件套当证据。

**校验踩坑**：直接拿 `backup_store` 导出的 `-original.json` 做差分时，BLOB 列以 `{"__hex__": ...}` 存储，必须先 `bytes.fromhex()` 还原，否则会把所有含 BLOB 的行误报为「额外变化」（本次一度误报 131 条）。

### 横幅时间（`ZLASTBANNERPRESENTATIONDATE`）的语义与区间

全库 530 条实测：397 条落在「其它时刻」（不等于任何业务锚点）、102 条 NULL、22 条 = 创建、8 条 = 闹钟触发、1 条 = 完成。有闹钟的项里**早于闹钟 160 条、晚于闹钟 21 条、等于闹钟仅 8 条**。结论：**它是系统「最近一次展示横幅通知」的行为日志，不是业务计划字段，不固定介于任何两个业务时间之间**。触发事件包括创建时写入（新建 PK 530 横幅 = 创建 +21 秒）、到期提醒弹出、用户查看/编辑、系统后台刷新。

能人为规定的只有两条自洽约束：**不早于创建时间**（还没创建不可能展示）；**对已完成事项不晚于完成时间**（完成后不该再弹提醒），未完成事项则是不晚于现在。即已完成事项的合理区间 `[创建, 完成]`、未完成 `[创建, 现在]`。当前全库 11 条已完成有横幅的全在前者、417 条未完成的全在后者。

闹钟确认痕迹 `ZREMCDOBJECT.ZACKNOWLEDGEDDATE` 语义是「用户确认/关闭了提醒」，必然在闹钟触发之后；当口径是「完成时间早于截止/闹钟」时，它取任何值都不自洽（早于完成＝确认了还没响的提醒，晚于完成＝完成后还在确认），**应清空**。

**单独清理确认痕迹**用 `scripts/clear_alarm_ack.py --pks <提醒主键>`，不要拿 `edit_times.py` / `complete_planned_batch.py` 代劳（它们会连带改主表一整套字段，越过范围），`fix_time_anomalies.py` 的 A12 也只覆盖「ack < 创建时间」，抓不到「ack 晚于完成」这种。注意这个字段在 `ZREMCDOBJECT` 的 `Z_ENT=16` 闹钟行上，**不在主表**，所以 `rdb.backup_store()` 默认导出的主表原值不含它——脚本会额外落一份 `<tag>-alarms-original.json` 供差分审计。用法：

```bash
python3 scripts/clear_alarm_ack.py --pks 175 --list life --title 做午餐          # dry-run
python3 scripts/clear_alarm_ack.py --pks 175 --apply --tag pre-ack-main
python3 scripts/clear_alarm_ack.py --pks 175 --verify \
    --changes /tmp/reminders-db-backup-YYYYMMDD/pre-ack-main-changes.json
```

2026-11-07 实测：只清 PK 175 的 alarm `Z_PK=3281`，全库 `ZREMCDOBJECT` 1319 行中仅该行一列变化，非空确认痕迹 27 → 26。

### 按计划回填一批事项的完整完成态

`scripts/complete_planned_batch.py`：计划 JSON 驱动，一次事务写主表时间/完成标记/全天时区 + 闹钟 JSON 对齐新截止 + 清空确认痕迹；支持 `banner` 策略（`creation` / `completion` / `null` / `keep`）、`--store` 副本演练、`--changes` 计划快照验收。适用于「某天某标题要凑够 N 条，截止/闹钟 8/12/18/22 点，完成 = 截止前 30 分钟」这类批量回填。

计划里的 `date` 可以改变一条事项的日期（例如把 11-05 12:00 的占位挪到 11-06 12:00），脚本同步改 `ZDUEDATE` / `ZDISPLAYDATEDATE` / 闹钟组件，不需要新建对象。**先确认目标条数**：不足时用户可选择新建、从其它日期挪一条、或只改现有条；挪动会让源日期少一条，需在报告里说明。

## 5. 自洽规则清单（体检项）

目标语义是「当天创建 → 后续未修改 → 截止前完成」。下列任何一条不满足，快照都会出现逻辑矛盾：

1. `ZLASTMODIFIEDDATE == ZCREATIONDATE`（未再修改）
2. `ZCREATIONDATE < ZCOMPLETIONDATE < ZDUEDATE`（创建后、截止前完成）
3. 三条时间落在同一天（当天创建）
4. `ZCOMPLETED == 1`
5. `ZDISPLAYDATEDATE == ZDUEDATE`
6. 闹钟触发 == 目标时刻（默认即截止时间；**组件一致 + 按闹钟 JSON 自身时区回算的绝对时间戳一致，双重校验**）
7. `ZSTARTDATE IS NULL`（否则出现「开始早于创建」）
8. `ZLASTBANNERPRESENTATIONDATE IS NULL`（否则出现「完成后还弹过横幅」）
9. 闹钟 `ZACKNOWLEDGEDDATE IS NULL`（否则出现「完成后还有确认痕迹」）
10. 无活跃循环规则关联（`Z_ENT=35 AND ZREMINDER4=<pk> AND ZMARKEDFORDELETION=0` 为 0 行）
11. 附加：`ZALLDAY` / `ZDISPLAYDATEISALLDAY` 为 0、`ZDISPLAYDATETIMEZONE` 与 **`ZTIMEZONE`** 均为 UTC+8 标识、`ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT=28800`，标题与 list 未被误改
12. 附加：闹钟关联链完整（trigger 实体类型是 18、`Z17_TRIGGER=18`、反向外键指回 alarm）
13. **导出层**：`alarmDate` 非空且等于目标绝对时刻；闹钟规则等于截止时刻时 `alarmDate == dueDate`；`dueDate` / `creationDate` / `lastModifiedDate` 与库内 epoch 秒一致（`verify_export.py`）

闹钟那条最容易漏。触发时间存在 JSON 日历组件里而不是时间戳，所以只比格式化字符串不够——`verify.py` 会**按 `timeZone.identifier` 指向的真实时区**把组件回算成 Core Data epoch 秒去和目标时刻比（旧版硬编码 UTC+8，等于把时区错位的可能性绕过去了）。`align_alarm_components()` 写入时会把非 UTC+8 / 缺失 / 非法的时区归一到 `Asia/Shanghai`，已有 UTC+8 标识（`Asia/Singapore` 等）保留原值；新建闹钟也写 `Asia/Shanghai`。两者都把 `second`/`nanosecond` 归零。`alarm_ok` 只有在组件、绝对时间、时区、秒归零、关联链、确认痕迹六项全通过时才计数，不会再出现「时区错位仍被汇总成 N/N 对齐」。

循环检查在选目标、写入、体检三处统一为「只算 `ZMARKEDFORDELETION=0` 的活跃规则」。已标记删除的待同步循环行是标准残留态，按 `references/schema.md` 不该删，也不该被体检误报。

## 6. 决策与常见坑

- **全天事项 + 具体时刻 = 8 小时错位**：库里大量「签到」类事项是 `ZALLDAY=1` 且 `ZDISPLAYDATETIMEZONE` / `ZTIMEZONE` 均为 NULL，它们的 `ZDUEDATE` 是「当天 00:00 UTC / 08:00 北京」。直接把 `ZDUEDATE` 写成 21:00 却保留全天标记或漏写 `ZTIMEZONE`，EventKit 会按日期 / 墙上时间重新解释。`rules.all_day="off"` 会一并清标记、写两个时区列与 `28800`；`verify.py` 逐列检查，`verify_export.py` 用导出的 `dueDate` 做端到端兜底。
- **「有没有闹钟」按批次实测，不要按印象推断**：具体时刻类事项通常带 `REMCDAlarm`，全天类事项通常不带。看到「都没有闹钟」与「都有闹钟」两种结论时，先确认是不是两批不同事项（见开头对照表）。「闹钟提醒时间是 21 点」对没有对象的事项意味着要新建对象，只改 `ZDUEDATE` 会让快照 `alarmDate` 仍是 `null`。新建前先在全库副本演练，确认主键推进与唯一索引都不冲突。
- **只跑 SQLite 体检会假阳性**：2026-11-07 实测 28 条签到事项 `verify.py` 报 0 未通过，但导出的 `dueDate` 早 8 小时、`alarmDate ≠ dueDate`，快照口径全错。根因是 `ZTIMEZONE` 为 NULL。第 5 步两个脚本缺一不可。
- **循环**：用户可能自己手动去除。去除后 `ZREMINDER4` 会被系统清空、行本身可能保留并打 `ZMARKEDFORDELETION=1`，这是标准的「待同步删除」状态，不算残留，别去删那一行。用户说「我手动处理了」就别再碰循环；用户说「不能用有循环的」则在选目标阶段用 `--exclude-recurring` 过滤。
- **最后修改时间**：系统在你改数据时会自动把它刷成当前时间。所以要么最后一步统一 `SET ZLASTMODIFIEDDATE=ZCREATIONDATE`，要么在写入事务里一起带上；不要用「完成时刻」去凑目标语义。
- **`Z_OPT` / `ACHANGE`**：内部版本号和变更追踪链，快照不读，清理反而破坏事务完整性，别动。
- **`ZCKSERVERRECORDDATA` 非空**说明有 iCloud 记录，本地改动理论上会被云端旧值覆盖。这是已知不可消除的风险，如实告知即可。
- **「库里对」不等于「快照对」**：`integrity_check` 和逐条读回只证明磁盘落盘；`alarmDate` / `dueDate` 最终由 `remindctl all --json` 决定，必须用 `verify_export.py` 复核。**注意权限按 client 记账**：当前会话若 `remindctl` 被 `kTCCServiceReminders` 拒绝，改用 cron 采集且 mtime 晚于写入时刻的项目快照喂给 `--export`（见第 5 步），不要反复请求授权（见 risks.md 第 1、2、5 节）。
- **本 skill 的写入流程不包含重启 `remindd`。** 缓存刷新是独立的系统层动作，会中断正在运行的 Reminders.app，且不改变磁盘真值。任务明确要求系统 UI 立即显示新值时，按 `risks.md` 第 2 节执行并把结果写进报告。

## 7. 脚本速查

| 脚本 | 作用 | 默认是否写入 |
|---|---|---|
| `scripts/rdb.py` | 定位 store、权限自检、备份、导出原值、按 list/title 找目标、查关联链 | `--backup` 只写 /tmp 备份文件；其余只读 |
| `scripts/edit_times.py` | 按计划批量改时间 + 联动闹钟/全天/痕迹，支持多标题、循环前置校验、新建闹钟对象 | **dry-run，需 `--apply` 才写库** |
| `scripts/edit_creation.py` | 最小改动模式：只回填创建/最后修改两列，日期可按各自截止日期推导或用 `date` 指定固定日期，自带 `--verify`（目标值 + 差分审计 + 导出层） | **dry-run，需 `--apply` 才写库** |
| `scripts/edit_completion.py` | 已完成事项最小改动模式：按各自截止日期回填创建/最后修改/完成三列（创建=当天 HH:MM、完成=截止前 N 分钟），截止/闹钟/痕迹一律不动，自带 `--verify` 与 `--emit-plan` | **dry-run，需 `--apply` 才写库** |
| `scripts/normalize_timeline.py` | 全库时间线归一化：统一创建时间 + 业务时间整体平移 + 闹钟/显示镜像联动 + 全库冲突清理；自带计划快照与 `--verify` | **dry-run，需 `--apply` 才写库** |
| `scripts/fix_time_anomalies.py` | 全库时间逻辑异常修复：未来完成时间整体回移、横幅/确认痕迹倒挂清理，自带 `--verify` 全库语义复检 | **dry-run，需 `--apply` 才写库** |
| `scripts/complete_planned_batch.py` | 按计划把一批事项回填成「当天创建→截止前完成」：主表时间/完成标记/全天时区 + 闹钟 JSON 对齐 + 确认痕迹清空，支持 `banner` 策略与计划快照验收 | **dry-run，需 `--apply` 才写库** |
| `scripts/edit_lastmod_completion.py` | 保持创建时间不变，只把最后修改时间改成创建时间、完成时间改成截止前 N 分钟；可选联动完成标记与横幅清空，`targets` 显式点名主键，自带 `--verify` 差分审计与导出层 | **dry-run，需 `--apply` 才写库** |
| `scripts/clear_alarm_ack.py` | 只清空指定提醒事项的 `REMCDAlarm.ZACKNOWLEDGEDDATE`（确认痕迹）；带 `Z_ENT`/`ZREMINDER`/非空 三重条件，主表与 trigger 不动；自带全库备份、闹钟行原值、计划快照、差分审计与 `--store` 副本演练 | **dry-run，需 `--apply` 才写库** |
| `scripts/verify.py` | 十二项 SQLite 语义体检 + 完整性 + 行数，支持显式 `HH:MM` 闹钟规则与新建对象链校验 | 纯只读 |
| `scripts/verify_export.py` | 导出层交叉验证：调用 `remindctl all --json` 或读 `--export`，逐条核对 `alarmDate` / `dueDate` | 纯只读 |
| `scripts/test_rdb.py` | 51 项确定性单测：epoch 换算、北京时间日界、闹钟规则、新建对象、全天/时区、闹钟时区归一、按自身时区回算、导出层 8 小时偏移与缺 `alarmDate` 回归、按截止日推导创建时间、固定日期与两种日期口径分流、最小改动两列约束 | 不连数据库 |

十二个脚本共用 `rdb.py` 里的常量与换算函数（含 `UTC8_TZ_IDS`），改口径时只改一处。**改动任何换算或联动逻辑后，先跑 `python3 scripts/test_rdb.py`（51 项断言），再跑副本端到端演练、dry-run 与双层体检回归**；换算规则是纯函数，不依赖运行时推断。

`~/.workbuddy-ai/skills` 是 `~/.agents/skills` 的符号链接（本机 inode 相同），两处路径指向同一份文件，不需要分别同步。

## 8. 参考资料

- `references/schema.md` —— 表、字段、epoch、UUID、关联链、可直接复用的 SQL
- `references/risks.md` —— TCC 两种权限、ACHANGE、CloudKit、remindd 缓存、回滚步骤、EventKit 交叉验证
- `references/time-fields-audit.md` —— 全库 26 张表时间字段盘点（五层框架 + 528 条实测 + 全天锚点定性 + 处理决策矩阵）。**做全库体检或想「一次性弄清所有时间字段」时先读这份**，避免把全天事项的 08:00 日期锚点误判为异常
- `evals/evals.json` —— 触发与 dry-run 验证用的测试 prompt（不含会真改库的用例）
