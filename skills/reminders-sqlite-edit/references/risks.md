# 风险、限制与回滚

直接改系统应用的私有 Core Data 库绕过了 Apple 的所有一致性保障。这份清单来自 2026-11-07 的实测，操作前读一遍，交付时如实告知用户。

## 1. 两种 TCC 权限不是一回事

| 权限 | TCC service | 能做什么 |
|---|---|---|
| 完全磁盘访问 | `kTCCServiceSystemPolicyAllFiles` | 读写 `Data-*.sqlite`（**写入必需**）、读 TCC.db、读 Calendar.sqlitedb |
| 提醒事项 | `kTCCServiceReminders` | EventKit / `osascript` 读取（**只用于交叉验证**） |

未给 Full Disk Access 时会看到 `Operation not permitted` / `authorization denied`，连 `ls` Stores 目录都失败。给用户加权限的是**当前执行环境**（终端 / IDE 进程），不是给某个脚本文件。

权限检查：

```bash
sqlite3 "$HOME/Library/Application Support/com.apple.TCC/TCC.db" \
  "SELECT service,client,auth_value FROM access WHERE service LIKE '%remind%';"
sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" \
  "SELECT client,auth_value FROM access WHERE service='kTCCServiceSystemPolicyAllFiles';"
```

`auth_value=2` 表示 Denied。实测 `kTCCServiceReminders` 对 `/usr/bin/osascript` 和 uv python3.11 都是 2，导致 Swift 请求 `requestFullAccessToReminders` 无弹窗直接超时。

**不改 TCC.db。** 权限授予只能在「系统设置 → 隐私与安全性 → 提醒事项」完成。Full Disk Access 已给、Reminders 仍 Denied 是正常状态，不影响磁盘写入。

## 2. 裸 SQL 不写 `ACHANGE`

`ACHANGE` / `ATRANSACTION` 是 Core Data persistent history，`ZREMCDCHANGETRACKINGSTATE` 是客户端消费位点。实测：

- 改一条记录前后，`max(ZTRANSACTIONID)` 和行数都不变；
- 批量改 20 条后，事务号只随系统自身活动从 12748 自然涨到 12752。

后果：`remindd` / Reminders.app 的内存缓存不知道磁盘变了，可能继续显示旧值。

**但采集链路不受影响**：2026-11-07 实测 `remindctl all --json` 能直接读到裸 SQL 改动后的新值（`creationDate` / `lastModifiedDate` / `dueDate` / `isCompleted` 全部与库内一致，无需重启 `remindd`），项目每天 8/13/17/22 点的快照由该命令生成。因此「自动采集快照一定读旧值」的旧表述不准确；需要区分「采集链路读到磁盘新值」与「Reminders.app UI / 其它 EventKit 客户端可能仍用内存缓存」。新建的 `REMCDAlarm` 对象也已被 `remindctl` 识别，28/28 条导出 `alarmDate` 非空。

处理顺序：

1. 先用 `PRAGMA integrity_check` + 逐条读回确认**磁盘真值已落**，这已经能证明写入成功；
2. 磁盘值验证完成后，任务明确要求系统 UI 立即显示新值时，执行 `killall remindd` 或重开 Reminders.app，并把执行结果写进报告；这一步只释放旧缓存，不改变磁盘真值；
3. 不要伪造 `ACHANGE` 记录。事务链被手工拼坏比缓存旧值严重得多。

## 3. iCloud / CloudKit 可能覆盖本地改动

`ZCKSERVERRECORDDATA` 全库非空说明事项已同步到 iCloud。本地裸改不会更新服务端的修改标记，云端旧记录理论上可能在下次同步时把值盖回来。

- 这是**已知且不可通过本地 SQL 消除**的风险，如实告知即可；
- 不删 `ZCKSERVERRECORDDATA`，不改 `ZCKDIRTYFLAGS`：这两类写入容易触发同步冲突或产生重复项；
- 为「原本没有闹钟」的事项新建的 alarm / trigger 是**纯本地对象**（`ZCKSERVERRECORDDATA` 为 NULL，不写云端标记），系统未必会把它们上传到 iCloud；下次同步时也可能被服务端版本覆盖。交付时把这一点和「主表时间可能被覆盖」一起说明；
- 若必须长期稳定，操作后观察一次同步，必要时在 UI 里做一次无害编辑让系统接管。

## 3.1 只验 SQLite 会给出假阳性

2026-11-07 的实测事故：28 条签到事项在 SQLite 层 `verify.py` 报「0 未通过、闹钟 28/28 对齐」，但 `remindctl all --json` 导出的 `dueDate` 是 `05:00Z` 而库内绝对时刻是 `13:00Z`，`alarmDate` 却是 `13:00Z` —— 快照里 `alarmDate ≠ dueDate`，与用户「闹钟 = 截止时间」的语义直接冲突。

根因：`ZDISPLAYDATETIMEZONE` 已写、`ZTIMEZONE` 仍为 NULL。两个独立列缺一不可；为 NULL 时 EventKit 把 `ZDUEDATE` 的绝对 epoch 秒当成 UTC+8 墙上时间再换算一次，早 8 小时。全库统计：`ZTIMEZONE` 已设 → 偏移 0（227 条）；NULL 且非全天 → 偏移 -8（35 条，其中 28 条是本轮写入）。

同类假阳性还有：事项没有 `REMCDAlarm` 对象时导出 `alarmDate` 为 `null`，而 SQLite 层若规则写成 `keep` 就完全不检查闹钟。

**结论**：`verify.py` 与 `verify_export.py` 必须成对执行。`verify_export.py` 只读，调用 `remindctl all --json` 或读 `--export`，按 `hex(ZIDENTIFIER)` 映射逐条核对 `alarmDate` / `dueDate`。写入时用 `rdb.time_specific_columns()` 一次性取全部 5 列，别手拼 SQL 漏列。

## 4. `Z_OPT` / 内部字段

`Z_OPT` 是 Core Data 乐观锁版本号（实测 8~264），`ACHANGE` 每条事项有 9~298 笔历史。快照不读这些字段，清理它们不会让数据「更干净」，只会破坏事务完整性。别动。

## 5. EventKit 交叉验证

**首选路径（无需放行提醒事项权限）**：`remindctl all --json` 是只读命令，本机实测可直接读到裸 SQL 改动后的磁盘值，且输出 `alarmDate` / `dueDate` 等快照原始字段。`verify_export.py` 已封装这一步并带超时。它同时是 EventKit + 直读 SQLite 混合实现，能反映采集链路真实所见，比手写 Swift 更贴近项目口径。

Swift / EventKit 是补充路径，受第 1 条限制。若用户放行了提醒事项权限，用 Swift 读取：

```swift
import EventKit
let store = EKEventStore()
store.requestFullAccessToReminders { ok, err in /* ... */ }
let pred = store.predicateForReminders(in: nil)   // 注意是 in:，不是 inCalendars:
store.fetchReminders(matching: pred) { rems in /* 打印 creationDate / dueDate / completionDate */ }
```

编译坑：旧写法 `predicateForReminders(inCalendars: nil)` 在 Swift 6 会报 `incorrect argument label in call`。

权限没放行时不要反复重试请求授权，会一直超时。直接说明阻塞原因。

## 6. 为什么不用 `remindctl`

`/usr/local/bin/remindctl` 0.3.8 是 **EventKit + 直读 SQLite 混合实现**（`strings` 可见 `EventKitStore.swift`、`SELECT COUNT(*) FROM ZREMCDREMINDER`、`Library/Group Containers/.../Stores`）。EventKit 层不暴露 `creationDate` 的写入接口，所以用户此前测试「改创建时间」不成功。**禁止用它写入**；但 `remindctl all --json` 是只读导出，既是项目采集脚本的数据源，也是 `verify_export.py` 的交叉验证依据，两者都不属于「用 remindctl 写入」。

## 7. 回滚

每轮写入前 `rdb.py --backup --tag <tag> --pks <...>` 会生成两份东西：

```
/tmp/reminders-db-backup-YYYYMMDD/<tag>.sqlite            一致性全库快照
/tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json     目标行整行原值（BLOB 用 hex）
```

按范围选一种：

- **精确回滚几行**：从 `-original.json` 读回原值，用 `UPDATE ... WHERE Z_PK=?` 逐列还原；BLOB 字段用 `bytes.fromhex(v['__hex__'])`。
- **回滚本轮新建的闹钟对象**：备份里 `ZREMCDOBJECT.MAX(Z_PK)` 记为 `old_max`。删掉 `Z_PK > old_max` 且 `Z_ENT IN (16,18)`、由本轮生成的行，再把 `Z_PRIMARYKEY` 中 `Z_ENT=14` 的 `Z_MAX` 还原成 `old_max`。三个动作放同一事务。UUID 是随机的，只能按主键区间识别，所以动手前先确认这段区间内没有其它来源的新对象。
- **整库回滚**：停掉 `remindd`，把 `<tag>.sqlite`（连同 `-wal`/`-shm` 若存在）拷回 Stores 目录覆盖原文件，再重启。整库回滚会把这之后系统自身产生的变更也一起丢掉，因此只在精确逐行回滚不可行时采用，并在报告里写明被覆盖的时间窗口。

新建对象这类写入**先在全库副本上跑一遍 `--apply` + `verify.py`**，再对主库执行；副本演练能提前暴露 `ZIDENTIFIER` 唯一索引冲突和主键推进错误。

回滚后重跑 `rdb.py --check` 和 `verify.py` 确认状态。

## 8. 交付时必须说清的话

不要说「已经完全生效」。准确表述是：

> 磁盘上的 SQLite 值已改并逐条读回验证，`integrity_check=ok`；但裸 SQL 不写 Core Data 变更历史，系统缓存与自动采集快照可能仍读旧值，iCloud 云端记录也可能覆盖本地。若 EventKit 权限被拒，系统层交叉验证尚未完成。

## 9. 已知不该做的事

- 不直接 `INSERT` 进 `ZREMCDREMINDER`：新建提醒事项要补 `Z_ENT`、`Z_OPT`、`Z_PRIMARYKEY` 计数、UUID、CloudKit 标记等十几个字段，极易产生脏数据。需要新事项时用 EventKit 创建再回填时间。
- `INSERT` 进 `ZREMCDOBJECT` 只允许最小 alarm + date trigger 对象，且必须同时推进 `Z_PRIMARYKEY.Z_MAX`、给每个对象独立随机 UUID、显式写 `ZMARKEDFORDELETION=0`、先做副本演练。不要手工拼其它实体类型的对象。
- 不改带 `ZPARENTREMINDER` / `Z15REMINDERS` 的循环母本。
- 不做全库扫描式批量 `UPDATE`，只动计划里点名的主键。
- 不删循环规则行（系统标记删除的行应保留待同步）。
- 不用 UTC 日界判断北京时间的「同一天」，不把北京 07:00 对应的「前一天 23:00 UTC」当成错误。
- 不用 `edit_times.py` 处理「只改创建/最后修改时间」的需求：它会连带写完成标记、完成时间、截止镜像、全天/时区列、闹钟与痕迹，把未完成事项改成已完成。用 `edit_creation.py` 的两列 UPDATE，并用 `--original` 做差分审计确认没有夹带改动。
- 不拿 `verify.py` 验收未完成事项：它的十二项体检假定「已完成、创建<完成<截止」，对未完成项会误报。用 `edit_creation.py --verify` 与 `verify_export.py`。
- 副本演练时用 `--no-export` 跳过导出层（`remindctl` 永远读活跃主库）；主库验收不允许跳过导出层。
