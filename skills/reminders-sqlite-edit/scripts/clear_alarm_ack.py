#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clear_alarm_ack.py — 清空指定提醒事项的闹钟确认痕迹 ZACKNOWLEDGEDDATE。

version : v1.0.0 (2026-11-07)
依赖    : Python 3.9+ 标准库；同目录 rdb.py
用法    :
  python3 clear_alarm_ack.py --pks 175 --list life --title 做午餐
  python3 clear_alarm_ack.py --pks 175 --apply --tag pre-ack-main
  python3 clear_alarm_ack.py --pks 175 --verify \
      --changes /tmp/reminders-db-backup-YYYYMMDD/<tag>-changes.json
退出码  : 0 成功 / 1 运行错误 / 2 前置校验未通过 / 3 验证未通过

为什么独立成脚本：ZACKNOWLEDGEDDATE 在 ZREMCDOBJECT 的 REMCDAlarm 行上，
不是 ZREMCDREMINDER 的列。edit_times.py 与 complete_planned_batch.py 清它会
连带改主表一整套字段（越界）；fix_time_anomalies.py 的 A12 只覆盖
「ack < 创建时间」，不覆盖「完成时间早于闹钟」这种语义不自洽。

只发一条带精确条件的 UPDATE：
    UPDATE ZREMCDOBJECT SET ZACKNOWLEDGEDDATE=NULL
     WHERE Z_PK=? AND Z_ENT=16 AND ZREMINDER=? AND ZACKNOWLEDGEDDATE IS NOT NULL
主表、闹钟 trigger、ZDATECOMPONENTSDATA、CloudKit 列一律不动。

默认 dry-run；--apply 先生成全库一致性备份 + 主表原值 + 闹钟行原值 +
计划快照，再单事务写入。--verify 纯只读，做目标值校验与差分审计。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb
from verify import components_to_epoch

ALARM_ENT = 16
# 系统/后台可能自行刷新的列：差分审计里只提示，不判失败。
SYSTEM_VOLATILE = {
    "Z_OPT", "ZCKSERVERRECORDDATA", "ZCKCLOUDSTATE", "ZCKIDENTIFIER",
    "ZSPOTLIGHTINDEXCOUNT", "ZRESOLUTIONTOKENMAP_V3_JSONDATA",
}


def _json_default(o):
    if isinstance(o, (bytes, bytearray, memoryview)):
        return {"__hex__": bytes(o).hex()}
    raise TypeError("不可序列化的类型 %r" % type(o))


def _decode(v):
    if isinstance(v, dict) and "__hex__" in v:
        return bytes.fromhex(v["__hex__"])
    return v


def _row(r):
    return {k: _decode(v) for k, v in dict(r).items()}


# ---------------------------------------------------------------- 前置与计划
def build_changes(conn, pks, list_name=None, title=None):
    lpk = rdb.find_list_pk(conn, list_name) if list_name else None
    if list_name and lpk is None:
        raise ValueError("找不到列表 %r" % list_name)
    changes, issues = [], []
    for pk in pks:
        r = conn.execute("SELECT * FROM %s WHERE Z_PK=?" % rdb.MAIN_TABLE,
                         (pk,)).fetchone()
        if r is None:
            issues.append("Z_PK=%d 主表行缺失" % pk)
            continue
        r = dict(r)
        if lpk is not None and r["ZLIST"] != lpk:
            issues.append("Z_PK=%d 不属于列表 %r" % (pk, list_name))
            continue
        if title and r["ZTITLE"] != title:
            issues.append("Z_PK=%d 标题 %r 与 %r 不符" %
                          (pk, r["ZTITLE"], title))
            continue
        if r["ZMARKEDFORDELETION"]:
            issues.append("Z_PK=%d 已标记删除" % pk)
            continue
        rows = conn.execute(
            "SELECT * FROM %s WHERE Z_ENT=? AND ZREMINDER=? "
            "AND ZMARKEDFORDELETION=0" % rdb.OBJECT_TABLE,
            (ALARM_ENT, pk)).fetchall()
        if len(rows) != 1:
            issues.append("Z_PK=%d 活跃 REMCDAlarm 对象数=%d（要求恰好 1 个）" %
                          (pk, len(rows)))
            continue
        a = dict(rows[0])
        if a["ZACKNOWLEDGEDDATE"] is None:
            issues.append("Z_PK=%d 的 alarm %d 确认痕迹已是 NULL" %
                          (pk, a["Z_PK"]))
            continue
        changes.append({
            "rem_pk": pk, "alarm_pk": a["Z_PK"],
            "old_ack": a["ZACKNOWLEDGEDDATE"],
            "creation": r["ZCREATIONDATE"],
            "completion": r["ZCOMPLETIONDATE"],
            "due": r["ZDUEDATE"],
            "completed": r["ZCOMPLETED"],
        })
    return changes, issues


def print_report(changes, issues, total_rows):
    print("=" * 104)
    print("最小改动：清空 REMCDAlarm.ZACKNOWLEDGEDDATE（北京时间 UTC+8）")
    print("=" * 104)
    print("目标条数=%d  全库=%d" % (len(changes), total_rows))
    print("%6s %8s %-17s %-17s %-17s %-17s %s" %
          ("提醒PK", "闹钟PK", "创建", "完成", "截止", "确认痕迹(旧)", "→ 新值"))
    print("-" * 104)
    for x in changes:
        print("%6d %8d %-17s %-17s %-17s %-17s %s" %
              (x["rem_pk"], x["alarm_pk"], rdb.fmt(x["creation"]),
               rdb.fmt(x["completion"]), rdb.fmt(x["due"]),
               rdb.fmt(x["old_ack"]), "NULL"))
    print("-" * 104)
    print("写入列：ZREMCDOBJECT.ZACKNOWLEDGEDDATE=NULL；主表/trigger/组件/CloudKit 一律不动")
    print("预计语句：%d 条 UPDATE（带 Z_ENT/ZREMINDER/非空 三重条件），单事务提交" %
          len(changes))
    if issues:
        print("前置问题：%d 项" % len(issues))
        for s in issues:
            print("   ! %s" % s)
    else:
        print("前置校验：全部通过（列表/标题/未软删/闹钟对象唯一/确认痕迹非空）")
    print("=" * 104)


# ---------------------------------------------------------------- 写入
def apply(path, changes, tag, backup_dir):
    pks = [x["rem_pk"] for x in changes]
    b = rdb.backup_store(path, tag, backup_dir, pks)
    root = backup_dir or rdb.BACKUP_ROOT
    print("一致性备份 : %s" % b["db"])
    print("主表原值   : %s" % (b["original"] or "(无)"))
    print("备份校验   : %d 行 / integrity=%s" % (b["rows"], b["integrity"]))

    conn = rdb.connect(path)
    alarm_pks = [x["alarm_pk"] for x in changes]
    rows = conn.execute(
        "SELECT * FROM %s WHERE Z_PK IN (%s)" %
        (rdb.OBJECT_TABLE, ",".join("?" * len(alarm_pks))), alarm_pks).fetchall()
    conn.close()
    ao = os.path.join(root, tag + "-alarms-original.json")
    with open(ao, "w", encoding="utf-8") as f:
        json.dump([_row(x) for x in rows], f, ensure_ascii=False,
                  indent=2, default=_json_default)
    cp = os.path.join(root, tag + "-changes.json")
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)
    print("闹钟行原值 : %s" % ao)
    print("计划快照   : %s" % cp)

    conn = rdb.connect(path, readonly=False)
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN IMMEDIATE")
        for x in changes:
            cur = conn.execute(
                "UPDATE %s SET ZACKNOWLEDGEDDATE=NULL "
                "WHERE Z_PK=? AND Z_ENT=? AND ZREMINDER=? "
                "AND ZACKNOWLEDGEDDATE IS NOT NULL" % rdb.OBJECT_TABLE,
                (x["alarm_pk"], ALARM_ENT, x["rem_pk"]))
            if cur.rowcount != 1:
                raise RuntimeError("alarm %d 预期更新 1 行，实际 %d 行" %
                                   (x["alarm_pk"], cur.rowcount))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    print("写入完成   : %d 条 UPDATE；integrity_check=%s；全库 %d 条" %
          (len(changes), rdb.integrity(conn), rdb.total_rows(conn)))
    conn.close()


# ---------------------------------------------------------------- 验证
def verify(path, changes, original_path, alarms_original_path):
    conn = rdb.connect(path)
    orig_main = {}
    if original_path and os.path.exists(original_path):
        with open(original_path, encoding="utf-8") as f:
            orig_main = {_row(r)["Z_PK"]: _row(r) for r in json.load(f)}
    orig_alarm = {}
    if alarms_original_path and os.path.exists(alarms_original_path):
        with open(alarms_original_path, encoding="utf-8") as f:
            orig_alarm = {_row(r)["Z_PK"]: _row(r) for r in json.load(f)}

    fail, notes = [], []
    for x in changes:
        rp, ap = x["rem_pk"], x["alarm_pk"]
        a = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                              rdb.OBJECT_TABLE, (ap,)).fetchone())
        if a["ZACKNOWLEDGEDDATE"] is not None:
            fail.append("alarm %d 确认痕迹仍为 %s" %
                        (ap, rdb.fmt(a["ZACKNOWLEDGEDDATE"])))
        if a["Z_ENT"] != ALARM_ENT or a["ZREMINDER"] != rp:
            fail.append("alarm %d 关联被改动 Z_ENT=%s ZREMINDER=%s" %
                        (ap, a["Z_ENT"], a["ZREMINDER"]))
        if ap in orig_alarm:
            changed = {k for k in orig_alarm[ap]
                       if orig_alarm[ap][k] != a.get(k)}
            extra = changed - {"ZACKNOWLEDGEDDATE"} - SYSTEM_VOLATILE
            if extra:
                fail.append("alarm %d 计划外列变化：%s" % (ap, sorted(extra)))
            volatile = sorted(changed & SYSTEM_VOLATILE)
            if volatile:
                notes.append("alarm %d 系统易变列刷新：%s（不判失败）" %
                             (ap, ", ".join(volatile)))
        r = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                              rdb.MAIN_TABLE, (rp,)).fetchone())
        for col, want in (("ZCREATIONDATE", x["creation"]),
                          ("ZCOMPLETIONDATE", x["completion"]),
                          ("ZDUEDATE", x["due"]), ("ZCOMPLETED", x["completed"])):
            if r[col] != want:
                fail.append("reminder %d 主表 %s 被改动：%r → %r" %
                            (rp, col, want, r[col]))
        if rp in orig_main:
            changed = {k for k in orig_main[rp]
                       if orig_main[rp][k] != r.get(k)}
            extra = changed - SYSTEM_VOLATILE
            if extra:
                fail.append("reminder %d 主表计划外列变化：%s" %
                            (rp, sorted(extra)))
        al = rdb.alarm_chain(conn, rp)
        if len(al) != 1 or al[0]["alarm_pk"] != ap:
            fail.append("reminder %d 闹钟关联链异常" % rp)
        elif isinstance(al[0]["trigger_json"], dict):
            try:
                ts = components_to_epoch(al[0]["trigger_json"])
                if abs(float(ts) - float(r["ZDUEDATE"])) >= 1:
                    fail.append("reminder %d 闹钟组件不再等于截止" % rp)
            except (ValueError, TypeError, KeyError) as e:
                fail.append("reminder %d 闹钟组件无法回算：%s" % (rp, e))

    print("=" * 100)
    print("验证（只读）  store=%s" % os.path.basename(path))
    print("=" * 100)
    print("目标值校验   : %d 条（ZACKNOWLEDGEDDATE=NULL）" % len(changes))
    print("差分审计     : 主表 %s / 闹钟行 %s" %
          (os.path.basename(original_path) if orig_main else "(未提供)",
           os.path.basename(alarms_original_path) if orig_alarm else "(未提供)"))
    print("完整性检查   : %s" % rdb.integrity(conn))
    print("全库提醒条数 : %d" % rdb.total_rows(conn))
    n_ack = conn.execute(
        "SELECT COUNT(*) FROM %s WHERE Z_ENT=? AND ZACKNOWLEDGEDDATE IS NOT NULL" %
        rdb.OBJECT_TABLE, (ALARM_ENT,)).fetchone()[0]
    print("全库非空确认痕迹 : %d" % n_ack)
    if notes:
        print("提示         : %d 项" % len(notes))
        for s in notes:
            print("   - %s" % s)
    print("未通过项     : %d" % len(fail))
    for s in fail:
        print("   - %s" % s)
    if not fail:
        print("   全部通过")
    conn.close()
    return len(fail)


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(
        description="清空指定提醒事项的闹钟确认痕迹（默认 dry-run）")
    ap.add_argument("--pks", required=True, help="逗号分隔的提醒事项 Z_PK")
    ap.add_argument("--list", dest="list_name", help="可选的列表名交叉校验")
    ap.add_argument("--title", help="可选的标题交叉校验")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--verify", action="store_true", help="只读验证")
    ap.add_argument("--tag", help="备份标签")
    ap.add_argument("--backup-dir", help="备份目录")
    ap.add_argument("--store", help="显式指定 store 路径（副本演练用）")
    ap.add_argument("--changes", help="verify 用的 -changes.json")
    ap.add_argument("--original", help="verify 用的主表 -original.json")
    ap.add_argument("--alarms-original", help="verify 用的 -alarms-original.json")
    a = ap.parse_args()

    pks = [int(x) for x in a.pks.split(",") if x.strip()]
    if not pks:
        raise ValueError("--pks 不能为空")
    path, _, _ = rdb.find_active_store(a.store)

    if a.verify:
        cp = a.changes
        if not cp and a.original:
            cp = a.original.replace("-original.json", "-changes.json")
        if not cp or not os.path.exists(cp):
            raise ValueError("需要 --changes（或可从 --original 推导的快照）")
        with open(cp, encoding="utf-8") as f:
            changes = json.load(f)
        op = a.original or cp.replace("-changes.json", "-original.json")
        ao = a.alarms_original or cp.replace("-changes.json",
                                             "-alarms-original.json")
        sys.exit(3 if verify(path, changes, op, ao) else 0)

    conn = rdb.connect(path)
    changes, issues = build_changes(conn, pks, a.list_name, a.title)
    total = rdb.total_rows(conn)
    conn.close()
    print_report(changes, issues, total)
    if issues:
        print("存在前置问题，已停止。")
        sys.exit(2)
    if not a.apply:
        print("DRY-RUN：未写入任何数据。")
        return
    tag = a.tag or "pre-clear-ack"
    apply(path, changes, tag, a.backup_dir)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, sqlite3.Error, OSError,
            json.JSONDecodeError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
