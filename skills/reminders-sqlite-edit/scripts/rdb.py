#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apple Reminders 底层 SQLite 公共库。

被 edit_times.py / verify.py 复用，也可单独当 CLI 用：
  python3 rdb.py --locate
  python3 rdb.py --check
  python3 rdb.py --find --list life --title 喂猫 --limit 20
  python3 rdb.py --chain --pks 12,19,24
  python3 rdb.py --backup --tag pre-my-edit --pks 12,19,24
"""
import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys
import uuid
from datetime import timezone, timedelta

# Core Data 以 2001-01-01 UTC 为纪元；与 Unix epoch 相差 978307200 秒
EPOCH = 978307200
# 本项目所有时间口径为北京时间（UTC+8）
TZ = timezone(timedelta(hours=8))
# 新建闹钟时写入的时区标识。Asia/Shanghai 与库内既有的 Asia/Singapore 同为 UTC+8
DEFAULT_ALARM_TZ = "Asia/Shanghai"
# UTC+8 时区标识白名单：闹钟 JSON 的 timeZone 与 ZDISPLAYDATETIMEZONE 共用。
# 放在这里统一维护，避免 edit_times / verify 各处硬编码后口径漂移。
# 实测本机库内存在 America/Los_Angeles 与无 timeZone 的闹钟，不能假设全是 UTC+8。
UTC8_TZ_IDS = frozenset({
    "Asia/Singapore", "Asia/Shanghai", "Asia/Hong_Kong",
    "Asia/Macau", "Asia/Taipei", "GMT+0800", "Asia/Chongqing",
})
# 有时间（HH:MM）的提醒事项必须关掉全天标记，并显式写上显示时区。
# 库内已有的非全天事项统一用 Asia/Singapore + 28800（UTC+8）。全天事项的
# ZDUEDATE 是「当天 08:00 北京 / 00:00 UTC」，保留 ZALLDAY=1 又写 21:00
# 会被系统按日重新解释，是典型的 8 小时时区错位。
DISPLAY_TZ_NAME = "Asia/Singapore"
DISPLAY_TZ_SECONDS_FROM_GMT = 28800

ALARM_ENT = 16              # REMCDAlarm
TRIGGER_ENT = 18            # REMCDAlarmDateTrigger
RECURRENCE_ENT = 35         # REMCDRecurrenceRule
OBJECT_ROOT_ENT = 14        # REMCDObject：Z_PRIMARYKEY 里管理全局对象主键的父实体

STORES_DIR = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.reminders/"
    "Container_v1/Stores"
)
BACKUP_ROOT = "/tmp/reminders-db-backup-" + dt.date.today().strftime("%Y%m%d")

MAIN_TABLE = "ZREMCDREMINDER"
OBJECT_TABLE = "ZREMCDOBJECT"


# ---------------------------------------------------------------- 基础换算
def to_bj(ts):
    """Core Data epoch 秒 -> 北京时间 aware datetime"""
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(float(ts) + EPOCH, TZ)


def to_cd(d):
    """aware/naive(北京) datetime -> Core Data epoch 秒（整数）"""
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return int(d.timestamp()) - EPOCH


def cd(y, m, day, h=0, mi=0):
    """按北京时间构造 Core Data epoch 秒"""
    return to_cd(dt.datetime(y, m, day, h, mi, 0, tzinfo=TZ))


def fmt(ts):
    """Core Data epoch 秒 -> 'YYYY-MM-DD HH:MM'（北京时间），空值返回 NULL"""
    d = to_bj(ts)
    return d.strftime("%Y-%m-%d %H:%M") if d else "NULL"


def parse_hm(s):
    h, mi = s.split(":")
    return int(h), int(mi)


def alarm_target_ts(due_ts, rule):
    """按规则求闹钟应有的北京时间点。纯函数。

    rule='due'  -> 等于截止时间（**对话未提闹钟时间时的默认值**）
    rule='HH:MM' -> 截止当天北京时间的指定时刻（用户显式给出的闹钟时间）
    """
    if rule == "due":
        return due_ts
    h, mi = parse_hm(rule)
    d = to_bj(due_ts)
    return cd(d.year, d.month, d.day, h, mi)


def creation_from_due(due_ts, hm="07:00"):
    """按截止日期的**北京自然日**生成当天指定时刻的 Core Data epoch 秒。纯函数。

    用于「根据截止日期把创建/最后修改时间回填到当天 HH:MM」这类需求：
    截止只提供日期，时刻由调用方指定。不能用 UTC 日界切日期——全天事项的
    ZDUEDATE 是「当天 08:00 北京 / 00:00 UTC」，用 ts//86400 会退回前一天。

    due_ts 为 None 时返回 None（调用方应跳过无截止日期的事项）。
    """
    if due_ts is None:
        return None
    d = to_bj(due_ts)
    h, mi = parse_hm(hm)
    return cd(d.year, d.month, d.day, h, mi)


def creation_on_date(date_str, hm="07:00"):
    """按**显式给定**的北京自然日 YYYY-MM-DD 与 HH:MM 生成 Core Data epoch 秒。

    与 creation_from_due() 互补：后者从 ZDUEDATE 推导日期，用于「按各自截止
    日期回填当天 07:00」；本函数用于用户直接点名**固定日期**的口径，例如
    「把创建时间改成今天 2026-11-07 的 7 点」——此时一批事项的截止日期可能
    各不相同，不能从 ZDUEDATE 取日。非法日期由 date.fromisoformat 抛
    ValueError，落到调用方的前置校验里。
    """
    d = dt.date.fromisoformat(date_str)
    h, mi = parse_hm(hm)
    return cd(d.year, d.month, d.day, h, mi)


def time_specific_columns(display_tz=DISPLAY_TZ_NAME):
    """北京时间 HH:MM 计划所需的「非全天 + 显式时区」列。纯函数。

    全天事项没有时区，只有「日期」；把 21:00 这种具体时刻写进
    ZALLDAY=1 的行会让 EventKit 按系统时区重新解释，产生 8 小时偏差。

    `ZTIMEZONE` 与 `ZDISPLAYDATETIMEZONE` 是**两个不同列**，缺一不可。
    2026-11-07 实测：只写显示时区、漏掉 `ZTIMEZONE` 时，`remindctl all --json`
    导出的 `dueDate` 恰好比库内绝对时刻早 8 小时（把 epoch 秒当成 UTC+8
    墙上时间再换算一次），而同一事项的 `alarmDate` 仍正确，于是快照里出现
    「闹钟 ≠ 截止时间」。全库 528 条统计：`ZTIMEZONE` 已设 → 偏移 0 小时
    （227 条）；`ZTIMEZONE` 为 NULL → 偏移 -8 小时（286 条）。
    """
    return {
        "ZALLDAY": 0,
        "ZDISPLAYDATEISALLDAY": 0,
        "ZDISPLAYDATETIMEZONE": display_tz,
        "ZTIMEZONE": display_tz,
        "ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT": DISPLAY_TZ_SECONDS_FROM_GMT,
    }


def new_alarm_components(target_ts, tz=DEFAULT_ALARM_TZ):
    """为一个原本没有闹钟的事项构造全新的 ZDATECOMPONENTSDATA 组件。纯函数。

    用北京时间的年月日时分，时区固定为 UTC+8；不复制任何既有对象的
    CloudKit 服务端记录（ZCKSERVERRECORDDATA），避免旧记录与新对象错配。
    """
    d = to_bj(target_ts)
    return {
        "timeZone": {"identifier": tz}, "era": 1,
        "year": d.year, "month": d.month, "day": d.day,
        "hour": d.hour, "minute": d.minute,
        "second": 0, "nanosecond": 0,
    }


def align_alarm_components(components, target_ts):
    """把闹钟 JSON 的日历组件对齐到目标时刻。纯函数，不修改入参。

    returns (新 dict, 可写入 ZDATECOMPONENTSDATA 的 UTF-8 bytes)
    保留 era 等原有键，覆盖年月日时分并把秒/纳秒归零。

    **时区必须一起归一**：日历组件是按北京时间写入的，若沿用原 JSON 里
    非 UTC+8 的 timeZone（本机实测存在 America/Los_Angeles 以及无 timeZone
    的闹钟），系统会按那个时区解释组件，产生 15~16 小时错位。已有 UTC+8
    标识（Asia/Singapore / Asia/Shanghai 等）保留原值，其余一律替换为
    DEFAULT_ALARM_TZ。只改组件不改时区是旧版本的缺陷。
    """
    d = to_bj(target_ts)
    out = dict(components)
    out.update(year=d.year, month=d.month, day=d.day,
               hour=d.hour, minute=d.minute, second=0, nanosecond=0)
    tz = out.get("timeZone")
    tzid = tz.get("identifier") if isinstance(tz, dict) else None
    if tzid not in UTC8_TZ_IDS:
        out["timeZone"] = {"identifier": DEFAULT_ALARM_TZ}
    return out, json.dumps(out, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------- 连接与定位
def has_col(conn, table, col):
    return any(r[1].upper() == col.upper()
               for r in conn.execute("PRAGMA table_info(%s)" % table))


def connect(path, readonly=True):
    """只读连接用 URI mode=ro，避免意外创建 -wal/-shm 或写库"""
    uri = "file:" + path + ("?mode=ro" if readonly else "")
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def list_stores():
    return sorted(glob.glob(os.path.join(STORES_DIR, "Data-*.sqlite")))


def find_active_store(explicit=None):
    """按 ZREMCDREMINDER 行数挑活跃主库，别按文件 mtime 猜。

    returns (path, row_count, candidates)
    """
    if explicit:
        c = connect(explicit)
        n = c.execute("SELECT COUNT(*) FROM %s" % MAIN_TABLE).fetchone()[0]
        c.close()
        return explicit, n, [(explicit, n)]

    candidates = []
    for p in list_stores():
        try:
            c = connect(p)
            n = c.execute("SELECT COUNT(*) FROM %s" % MAIN_TABLE).fetchone()[0]
            c.close()
            candidates.append((p, n))
        except sqlite3.Error as e:
            candidates.append((p, "ERR: %s" % e))

    if not candidates:
        raise RuntimeError(
            "找不到 Data-*.sqlite。检查目录是否存在、以及当前进程是否有"
            "「完全磁盘访问权限」(kTCCServiceSystemPolicyAllFiles)：%s" % STORES_DIR
        )
    ok = [x for x in candidates if isinstance(x[1], int)]
    if not ok:
        raise RuntimeError("所有 store 都读失败：%s" % candidates)
    best = max(ok, key=lambda x: x[1])
    return best[0], best[1], candidates


# ---------------------------------------------------------------- 查询辅助
def find_list_pk(conn, name):
    row = conn.execute(
        "SELECT Z_PK FROM ZREMCDBASELIST WHERE ZNAME=? "
        "AND COALESCE(ZMARKEDFORDELETION,0)=0", (name,)
    ).fetchone()
    return row[0] if row else None


def find_reminders(conn, list_pk, title, limit=None):
    """按 list + 标题找目标主键，返回只读行（含关键时间字段）"""
    where = "ZLIST=? AND ZTITLE=?"
    args = [list_pk, title]
    if has_col(conn, MAIN_TABLE, "ZMARKEDFORDELETION"):
        where += " AND COALESCE(ZMARKEDFORDELETION,0)=0"
    sql = ("SELECT Z_PK, ZTITLE, ZLIST, ZCREATIONDATE, ZLASTMODIFIEDDATE, "
           "ZDUEDATE, ZDISPLAYDATEDATE, ZCOMPLETIONDATE, ZCOMPLETED, "
           "ZSTARTDATE, ZLASTBANNERPRESENTATIONDATE, ZALLDAY, "
           "ZDISPLAYDATEISALLDAY "
           "FROM %s WHERE %s ORDER BY Z_PK" % (MAIN_TABLE, where))
    if limit:
        sql += " LIMIT %d" % int(limit)
    return conn.execute(sql, args).fetchall()


def active_recurrence(conn, rem_pk):
    """返回仍生效的循环规则行（已标记删除的不算）。"""
    return [r for r in recurrence_rows(conn, rem_pk)
            if not r["ZMARKEDFORDELETION"]]


def find_clean_reminders(conn, list_pk, title, limit=None):
    """找不带循环、不带循环母本、未软删除的事项主键行。

    用户明确要求「不能用有循环的」时，选目标阶段就要排除，不能等写入后
    再报错。逐条查子对象关联，命中的直接跳过并继续往后取。
    """
    out = []
    parent_cols = [c for c in ("ZPARENTREMINDER", "Z15REMINDERS")
                   if has_col(conn, MAIN_TABLE, c)]
    for r in find_reminders(conn, list_pk, title):
        pk = r["Z_PK"]
        if active_recurrence(conn, pk):
            continue
        if parent_cols:
            full = conn.execute(
                "SELECT %s FROM %s WHERE Z_PK=?" %
                (",".join(parent_cols), MAIN_TABLE), (pk,)
            ).fetchone()
            if full and any(full[c] for c in parent_cols):
                continue
        out.append(r)
        if limit and len(out) >= limit:
            break
    return out


def alarm_chain(conn, rem_pk):
    """闹钟关联链：Z_ENT=16 (REMCDAlarm) -> ZTRIGGER -> Z_ENT=18 的 JSON。

    返回 [{alarm_pk, trigger_pk, ack, trigger_json(可解析对象), raw}]
    """
    for col in ("ZREMINDER", "ZTRIGGER", "ZDATECOMPONENTSDATA",
                "ZACKNOWLEDGEDDATE"):
        if not has_col(conn, OBJECT_TABLE, col):
            raise RuntimeError(
                "ZREMCDOBJECT 缺少列 %s —— 系统版本可能不同，"
                "先跑 PRAGMA table_info(ZREMCDOBJECT) 找新的外键名" % col
            )
    rows = conn.execute(
        "SELECT a.Z_PK AS alarm_pk, a.ZTRIGGER AS trigger_pk, "
        "       a.ZACKNOWLEDGEDDATE AS ack, a.Z17_TRIGGER AS trigger_ent, "
        "       t.Z_PK AS resolved_trigger_pk, t.Z_ENT AS resolved_trigger_ent, "
        "       t.ZALARM AS trigger_back, t.ZDATECOMPONENTSDATA AS raw "
        "FROM %s a LEFT JOIN %s t ON t.Z_PK=a.ZTRIGGER "
        "WHERE a.Z_ENT=16 AND a.ZREMINDER=?" % (OBJECT_TABLE, OBJECT_TABLE),
        (rem_pk,),
    ).fetchall()
    out = []
    for r in rows:
        raw = r["raw"]
        if isinstance(raw, (bytes, memoryview)):
            s = bytes(raw).decode("utf-8", "replace")
        else:
            s = raw
        try:
            obj = json.loads(s) if s else None
        except (ValueError, TypeError):
            obj = None
        out.append({
            "alarm_pk": r["alarm_pk"],
            "trigger_pk": r["trigger_pk"],
            "trigger_ent": r["trigger_ent"],
            "resolved_trigger_pk": r["resolved_trigger_pk"],
            "resolved_trigger_ent": r["resolved_trigger_ent"],
            "trigger_back": r["trigger_back"],
            "ack": r["ack"],
            "trigger_json": obj,
            "raw": s,
        })
    return out


def recurrence_rows(conn, rem_pk):
    """循环规则行：Z_ENT=35 且 ZREMINDER4 指向该提醒事项"""
    if not has_col(conn, OBJECT_TABLE, "ZREMINDER4"):
        return []
    return conn.execute(
        "SELECT Z_PK, ZREMINDER4, ZMARKEDFORDELETION, ZFREQUENCY, ZINTERVAL "
        "FROM %s WHERE Z_ENT=35 AND ZREMINDER4=?" % OBJECT_TABLE,
        (rem_pk,),
    ).fetchall()


def next_object_pk(conn):
    """ZREMCDOBJECT 是单表继承，主键由 Z_PRIMARYKEY 中父实体 Z_ENT=14 的
    Z_MAX 统一分配。取「实际最大主键」与「计数器」的较大者再加 1。"""
    a = conn.execute("SELECT COALESCE(MAX(Z_PK),0) FROM %s" % OBJECT_TABLE).fetchone()[0]
    row = conn.execute("SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_ENT=?",
                       (OBJECT_ROOT_ENT,)).fetchone()
    b = row[0] if row else 0
    return max(a, b or 0) + 1


def build_alarm_inserts(rem_pk, target_ts, alarm_pk, trigger_pk,
                        account=1, tz=DEFAULT_ALARM_TZ):
    """为原本没有闹钟的事项构造一对 Core Data 对象行。纯函数，不写库。

    returns (inserts, pk_update)
      inserts   : [(sql, args), ...] —— alarm 行 + date trigger 行
      pk_update : (sql, args)        —— 把 Z_PRIMARYKEY.Z_MAX 推到新最大值

    只写最小必要字段；不设置 ZCKSERVERRECORDDATA / ZCKCLOUDSTATE，让新对象
    成为纯本地待同步对象，避免复制别的对象的云端记录造成错配。
    """
    comp = new_alarm_components(target_ts, tz)
    blob = json.dumps(comp, separators=(",", ":")).encode("utf-8")
    u_alarm = str(uuid.uuid4()).upper()
    u_trigger = str(uuid.uuid4()).upper()

    # Z_FOK_REMINDER=2048 与 Z17_TRIGGER=18 在本库所有现存 alarm 行里是固定值，
    # 分别是外键排序键与 trigger 的实体类型冗余列。
    # ZMARKEDFORDELETION 必须显式给 0：库内有 Z_REMCDObject_byConcealed 索引
    # 以该列打头，现存 alarm / trigger 行也全部是 0 或 1，没有 NULL。
    alarm_sql = (
        "INSERT INTO %s (Z_PK,Z_ENT,Z_OPT,ZACCOUNT,ZREMINDER,ZTRIGGER,"
        "Z17_TRIGGER,Z_FOK_REMINDER,ZMARKEDFORDELETION,ZCKIDENTIFIER,"
        "ZALARMUID,ZIDENTIFIER) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)" % OBJECT_TABLE
    )
    alarm_args = (alarm_pk, ALARM_ENT, 1, account, rem_pk, trigger_pk,
                  TRIGGER_ENT, 2048, 0, u_alarm, u_alarm,
                  uuid.UUID(u_alarm).bytes)

    trigger_sql = (
        "INSERT INTO %s (Z_PK,Z_ENT,Z_OPT,ZACCOUNT,ZALARM,ZMARKEDFORDELETION,"
        "ZCKIDENTIFIER,ZIDENTIFIER,ZDATECOMPONENTSDATA) "
        "VALUES (?,?,?,?,?,?,?,?,?)" % OBJECT_TABLE
    )
    trigger_args = (trigger_pk, TRIGGER_ENT, 1, account, alarm_pk, 0,
                    u_trigger, uuid.UUID(u_trigger).bytes, blob)

    pk_sql = "UPDATE Z_PRIMARYKEY SET Z_MAX=? WHERE Z_ENT=?"
    return [(alarm_sql, alarm_args), (trigger_sql, trigger_args)], \
           (pk_sql, (trigger_pk, OBJECT_ROOT_ENT))


def integrity(conn):
    return conn.execute("PRAGMA integrity_check").fetchone()[0]


def total_rows(conn):
    return conn.execute("SELECT COUNT(*) FROM %s" % MAIN_TABLE).fetchone()[0]


# ---------------------------------------------------------------- 备份与回滚
def _json_default(o):
    if isinstance(o, (bytes, memoryview)):
        return {"__hex__": bytes(o).hex()}
    return str(o)


def backup_store(path, tag, backup_dir=None, pks=None):
    """用 SQLite 在线 backup API 取一致性快照（WAL 下比 cp 可靠）。

    另导出目标行整行原值 JSON，用于精确回滚。
    returns dict(db=..., original=..., rows=...)
    """
    root = backup_dir or BACKUP_ROOT
    os.makedirs(root, exist_ok=True)
    db_out = os.path.join(root, tag + ".sqlite")
    orig_out = os.path.join(root, tag + "-original.json")

    src = connect(path, readonly=True)
    dst = sqlite3.connect(db_out)
    try:
        src.backup(dst)          # 一致性在线备份，自动处理 WAL
    finally:
        dst.close()
    n = src.execute("SELECT COUNT(*) FROM %s" % MAIN_TABLE).fetchone()[0]
    chk = integrity(src)

    result = {"db": db_out, "original": None, "rows": n, "integrity": chk}
    if pks:
        ph = ",".join("?" * len(pks))
        rows = src.execute(
            "SELECT * FROM %s WHERE Z_PK IN (%s)" % (MAIN_TABLE, ph), pks
        ).fetchall()
        with open(orig_out, "w", encoding="utf-8") as f:
            json.dump([dict(r) for r in rows], f, ensure_ascii=False,
                      indent=2, default=_json_default)
        result["original"] = orig_out
    src.close()

    if chk != "ok":
        raise RuntimeError("备份完整性检查失败：%s" % chk)
    return result


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="Apple Reminders 底层 SQLite 工具")
    ap.add_argument("--store", help="显式指定 store 路径（默认自动定位活跃库）")
    ap.add_argument("--locate", action="store_true", help="列出所有 store 与行数")
    ap.add_argument("--check", action="store_true", help="权限与完整性自检")
    ap.add_argument("--find", action="store_true", help="按 list/title 查目标")
    ap.add_argument("--list", dest="list_name", help="列表名，如 life")
    ap.add_argument("--title", help="提醒事项标题")
    ap.add_argument("--titles", help="逗号分隔的多个标题（与 --title 二选一）")
    ap.add_argument("--exclude-recurring", action="store_true",
                    help="排除带循环规则或循环母本的事项")
    ap.add_argument("--limit", type=int, help="每个标题最多取几条")
    ap.add_argument("--chain", action="store_true", help="查看闹钟/循环关联链")
    ap.add_argument("--pks", help="逗号分隔的 Z_PK")
    ap.add_argument("--backup", action="store_true", help="生成一致性备份")
    ap.add_argument("--tag", help="备份文件名标签")
    ap.add_argument("--backup-dir", help="备份目录")
    a = ap.parse_args()

    pks = [int(x) for x in a.pks.split(",")] if a.pks else None

    if a.locate or a.check:
        path, n, cand = find_active_store(a.store)
        print("Stores 目录：%s" % STORES_DIR)
        for p, cnt in cand:
            mark = "  <== 活跃主库" if p == path else ""
            print("  %-92s %8s%s" % (os.path.basename(p), cnt, mark))
        if a.check:
            c = connect(path)
            print("integrity_check : %s" % integrity(c))
            print("全库提醒条数   : %d" % total_rows(c))
            print("主表关键列     : %s" % ", ".join(
                r[1] for r in c.execute("PRAGMA table_info(%s)" % MAIN_TABLE)
                if "DATE" in r[1].upper() and r[1].upper().startswith("Z")))
            c.close()
        return

    if a.backup:
        if not a.tag:
            ap.error("--backup 需要 --tag")
        path, _, _ = find_active_store(a.store)
        r = backup_store(path, a.tag, a.backup_dir, pks)
        print("一致性备份 : %s" % r["db"])
        print("原值快照   : %s" % (r["original"] or "(未指定 --pks)"))
        print("备份行数   : %d" % r["rows"])
        print("完整性     : %s" % r["integrity"])
        return

    if a.find:
        titles = ([x.strip() for x in a.titles.split(",") if x.strip()]
                  if a.titles else ([a.title] if a.title else []))
        if not a.list_name or not titles:
            ap.error("--find 需要 --list 与 (--title 或 --titles)")
        path, _, _ = find_active_store(a.store)
        c = connect(path)
        lpk = find_list_pk(c, a.list_name)
        if lpk is None:
            print("找不到列表 %r" % a.list_name)
            return
        print("list=%r Z_PK=%d  过滤循环=%s  每标题上限=%s" %
              (a.list_name, lpk, a.exclude_recurring, a.limit or "不限"))
        for t in titles:
            total = len(find_reminders(c, lpk, t))
            rows = (find_clean_reminders(c, lpk, t, a.limit)
                    if a.exclude_recurring else find_reminders(c, lpk, t, a.limit))
            print("\n标题 %r：库中 %d 条，本次取 %d 条" % (t, total, len(rows)))
            print("%5s %-17s %-17s %-17s %-17s %-6s %s" %
                  ("PK", "创建", "修改", "截止", "完成", "状态", "闹钟"))
            for r in rows:
                na = len(alarm_chain(c, r["Z_PK"]))
                print("%5d %-17s %-17s %-17s %-17s %-6s %s" %
                      (r["Z_PK"], fmt(r["ZCREATIONDATE"]),
                       fmt(r["ZLASTMODIFIEDDATE"]), fmt(r["ZDUEDATE"]),
                       fmt(r["ZCOMPLETIONDATE"]),
                       "已完成" if r["ZCOMPLETED"] else "未完成",
                       "%d 个" % na if na else "无"))
            print("  主键: %s" % ",".join(str(r["Z_PK"]) for r in rows))
        c.close()
        return

    if a.chain:
        if not pks:
            ap.error("--chain 需要 --pks")
        path, _, _ = find_active_store(a.store)
        c = connect(path)
        for pk in pks:
            alarms = alarm_chain(c, pk)
            recs = recurrence_rows(c, pk)
            print("Z_PK=%d  闹钟 %d 个，循环 %d 条" % (pk, len(alarms), len(recs)))
            for al in alarms:
                j = al["trigger_json"] or {}
                print("   alarm=%s trigger=%s ack=%s  components=%s" %
                      (al["alarm_pk"], al["trigger_pk"], fmt(al["ack"]),
                       {k: j.get(k) for k in
                        ("year", "month", "day", "hour", "minute", "timeZone")}))
            for r in recs:
                print("   recur=%s marked_del=%s freq=%s interval=%s" %
                      (r["Z_PK"], r["ZMARKEDFORDELETION"],
                       r["ZFREQUENCY"], r["ZINTERVAL"]))
        c.close()
        return

    ap.print_help()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, sqlite3.Error, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
