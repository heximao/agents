#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填「创建时间 / 最后修改时间」两列，其余字段一律不动。

日期口径二选一（由计划 JSON 的 `date` 决定）：
  * 省略 `date` —— 按每条事项**各自截止日期**的北京自然日（creation_from_due）
  * 给出 `date` —— 用这个**固定日期** YYYY-MM-DD（creation_on_date），
    例如「改成今天 2026-11-07 的 7 点」；此时一批事项截止日期各不相同，
    不能从 ZDUEDATE 取日，但前置校验仍要求目标创建时刻早于截止。

  python3 edit_creation.py --plan /tmp/plan.json                       # dry-run
  python3 edit_creation.py --plan /tmp/plan.json --apply --tag pre-bed
  python3 edit_creation.py --plan /tmp/plan.json --verify \
      --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
      --export /tmp/export.json

存在理由：`edit_times.py` 面向「回填一整套历史时间」场景，会连带改截止时间、
完成时间、完成标记、全天/时区列、闹钟与痕迹。用户只要求「把创建和最后修改
时间按各自截止日期改成当天 07:00」且事项**仍未完成**时，用那个脚本会越过
范围。本脚本只发一条 UPDATE：

    UPDATE ZREMCDREMINDER SET ZCREATIONDATE=?, ZLASTMODIFIEDDATE=? WHERE Z_PK=?

默认 dry-run；`--apply` 才在单事务里写入，写入前生成一致性备份与目标行原值。
`--verify` 纯只读，核对目标值、差分审计（除两列外无变化）与导出层字段。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb
import verify_export as ve

CHANGED_COLS = ("ZCREATIONDATE", "ZLASTMODIFIEDDATE")


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    if not p.get("list") or not p.get("title"):
        raise ValueError("计划需要 list 与 title")
    p.setdefault("time", "07:00")
    rdb.parse_hm(p["time"])           # 提前校验 HH:MM 格式
    p.setdefault("incomplete_only", True)
    if p.get("date"):
        # 固定日期模式：提前校验 YYYY-MM-DD 与 HH:MM 能组合成合法时刻
        rdb.creation_on_date(p["date"], p["time"])
    return p


def target_creation(plan, due_ts):
    """求目标创建时刻（Core Data epoch 秒）。纯函数，写入与体检共用同一口径。

    plan.date 存在 -> 固定日期；否则按截止日期的北京自然日推导。
    """
    if plan.get("date"):
        return rdb.creation_on_date(plan["date"], plan["time"])
    return rdb.creation_from_due(due_ts, plan["time"])


def select_rows(conn, plan):
    """只读选目标。targets 省略时自动按 list + title + 未完成筛选。"""
    lpk = rdb.find_list_pk(conn, plan["list"])
    if lpk is None:
        raise ValueError("找不到列表 %r" % plan["list"])
    if plan.get("targets"):
        pks = [int(t["pk"]) for t in plan["targets"]]
        ph = ",".join("?" * len(pks))
        rows = conn.execute("SELECT * FROM %s WHERE Z_PK IN (%s)" %
                            (rdb.MAIN_TABLE, ph), pks).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM %s WHERE ZLIST=? AND ZTITLE=? "
            "AND COALESCE(ZCOMPLETED,0)=0 "
            "AND COALESCE(ZMARKEDFORDELETION,0)=0 ORDER BY Z_PK" %
            rdb.MAIN_TABLE, (lpk, plan["title"])).fetchall()
    return lpk, rows


def build_updates(conn, plan, lpk, rows):
    """返回 (updates, issues, warnings)。每条只有一条两列 UPDATE。"""
    updates, issues, warnings = [], [], []
    for r in rows:
        pk = r["Z_PK"]
        if r["ZLIST"] != lpk:
            issues.append("Z_PK=%d 不属于列表 %r" % (pk, plan["list"]))
            continue
        if r["ZTITLE"] != plan["title"]:
            issues.append("Z_PK=%d 标题是 %r，与计划 %r 不符" %
                          (pk, r["ZTITLE"], plan["title"]))
            continue
        if plan["incomplete_only"] and r["ZCOMPLETED"]:
            issues.append("Z_PK=%d 已完成，不符合「未完成」筛选" % pk)
            continue
        if rdb.active_recurrence(conn, pk):
            issues.append("Z_PK=%d 带活跃循环规则" % pk)
            continue
        due = r["ZDUEDATE"]
        if due is None:
            issues.append("Z_PK=%d 没有截止日期，无法推导" % pk)
            continue
        target = target_creation(plan, due)
        if target >= float(due):
            issues.append("Z_PK=%d 目标创建时刻 %s 不早于截止 %s" %
                          (pk, rdb.fmt(target), rdb.fmt(due)))
        if r["ZSTARTDATE"] is not None and float(r["ZSTARTDATE"]) < target:
            warnings.append("Z_PK=%d 的 ZSTARTDATE=%s 早于新创建时间（本次不改该列）"
                            % (pk, rdb.fmt(r["ZSTARTDATE"])))
        alarms = rdb.alarm_chain(conn, pk)
        if not alarms:
            warnings.append("Z_PK=%d 无闹钟对象（本次不改闹钟）" % pk)
        updates.append({
            "pk": pk,
            "due": due,
            "due_day": rdb.to_bj(due).date().isoformat(),
            "target": target,
            "old_cre": r["ZCREATIONDATE"],
            "old_mod": r["ZLASTMODIFIEDDATE"],
            "sql": "UPDATE %s SET ZCREATIONDATE=?, ZLASTMODIFIEDDATE=? "
                   "WHERE Z_PK=?" % rdb.MAIN_TABLE,
            "args": (target, target, pk),
            "alarms": len(alarms),
        })
    return updates, issues, warnings


def print_report(updates, issues, warnings, rows_total, plan):
    print("=" * 104)
    print("回填创建/最后修改时间（北京时间 UTC+8，最小改动两列）")
    print("=" * 104)
    date_mode = ("固定日期 %s" % plan["date"]) if plan.get("date") \
        else "各自截止日期"
    print("列表=%r  标题=%r  日期口径=%s  目标时刻=%s  仅未完成=%s  目标条数=%d" %
          (plan["list"], plan["title"], date_mode, plan["time"],
           plan["incomplete_only"], len(updates)))
    print("%5s %-12s %-12s | %-17s %-17s | %-17s %-5s" %
          ("PK", "截止日期", "目标日期", "创建(旧)", "修改(旧)",
           "创建=修改(新)", "闹钟"))
    print("-" * 116)
    for u in updates:
        print("%5d %-12s %-12s | %-17s %-17s | %-17s %-5d" %
              (u["pk"], u["due_day"],
               rdb.to_bj(u["target"]).date().isoformat(),
               rdb.fmt(u["old_cre"]), rdb.fmt(u["old_mod"]),
               rdb.fmt(u["target"]), u["alarms"]))
    print("-" * 116)
    print("只写两列：ZCREATIONDATE / ZLASTMODIFIEDDATE；"
          "截止、完成、完成标记、全天/时区、闹钟、痕迹一律不动")
    print("预计语句：%d 条 UPDATE；全库提醒条数：%d（不应变化）" %
          (len(updates), rows_total))
    if warnings:
        print("提示：%d 项" % len(warnings))
        for w in warnings:
            print("   - %s" % w)
    if issues:
        print("前置问题：%d 项" % len(issues))
        for s in issues:
            print("   ! %s" % s)
    else:
        print("前置校验：全部通过")
    print("=" * 104)


def apply(path, updates, tag, backup_dir):
    b = rdb.backup_store(path, tag, backup_dir, [u["pk"] for u in updates])
    print("已备份：%s" % b["db"])
    print("原值  ：%s" % b["original"])
    print("备份校验：%d 行 / integrity=%s" % (b["rows"], b["integrity"]))
    conn = rdb.connect(path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for u in updates:
            conn.execute(u["sql"], u["args"])
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    print("写入完成：%d 条 UPDATE，integrity_check=%s，全库 %d 条" %
          (len(updates), rdb.integrity(conn), rdb.total_rows(conn)))
    conn.close()


def decode_original(obj):
    """把 backup_store 导出的原值 JSON 还原（BLOB 用 hex）。"""
    out = {}
    for row in obj:
        d = {}
        for k, v in row.items():
            if isinstance(v, dict) and "__hex__" in v:
                d[k] = bytes.fromhex(v["__hex__"])
            else:
                d[k] = v
        out[d["Z_PK"]] = d
    return out


def verify(path, plan, updates, original_path, export_path, skip_export=False):
    """纯只读：目标值 + 差分审计 + 导出层。返回失败数。

    skip_export 只用于全库副本演练：remindctl 永远读活跃主库，副本上的
    导出层数值必然对不上。主库验收必须跑完整导出层。
    """
    conn = rdb.connect(path)
    if skip_export:
        items, by_uuid = None, None
    else:
        # 导出层交叉验证是硬性步骤：未给 --export 时实时调用 remindctl all --json
        items = ve.load_export(export_path, 90)
        by_uuid = ve.index_by_uuid(items)
    orig = None
    if original_path:
        with open(original_path, encoding="utf-8") as f:
            orig = decode_original(json.load(f))

    fail = []
    for u in updates:
        pk = u["pk"]
        r = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                              rdb.MAIN_TABLE, (pk,)).fetchone())
        want = target_creation(plan, r["ZDUEDATE"])
        if r["ZCREATIONDATE"] != want:
            fail.append("Z_PK=%d 创建期望 %s 实际 %s" %
                        (pk, rdb.fmt(want), rdb.fmt(r["ZCREATIONDATE"])))
        if r["ZLASTMODIFIEDDATE"] != want:
            fail.append("Z_PK=%d 修改期望 %s 实际 %s" %
                        (pk, rdb.fmt(want), rdb.fmt(r["ZLASTMODIFIEDDATE"])))
        if orig and pk in orig:
            changed = {k for k in orig[pk] if orig[pk][k] != r.get(k)}
            extra = changed - set(CHANGED_COLS)
            if extra:
                fail.append("Z_PK=%d 除两列外还有变化：%s" %
                            (pk, sorted(extra)))
        if by_uuid is not None:
            uid = bytes(r["ZIDENTIFIER"]).hex().lower()
            f, _ = ve.check_export_row(pk, r, by_uuid.get(uid),
                                       {"alarm": "due"}, None)
            for s in f:
                fail.append("Z_PK=%d 导出层 %s" % (pk, s))

    print("=" * 104)
    print("验证（只读）  store=%s" % os.path.basename(path))
    print("=" * 104)
    date_desc = ("固定 %s %s" % (plan["date"], plan["time"])) \
        if plan.get("date") else ("各自截止当天 %s" % plan["time"])
    print("目标值校验   : %d 条，创建 = 修改 = %s（北京时间）" %
          (len(updates), date_desc))
    print("差分审计     : %s" %
          ("仅两列变化（对照 %s）" % os.path.basename(original_path)
           if orig else "未提供 --original，跳过"))
    print("导出层校验   : %s" %
          ("副本演练已跳过" if skip_export else
           "%d 条（来源：%s）" % (len(items),
                                os.path.basename(export_path) if export_path
                                else "remindctl all --json")))
    print("完整性检查   : %s" % rdb.integrity(conn))
    print("全库提醒条数 : %d" % rdb.total_rows(conn))
    print("未通过项     : %d" % len(fail))
    for s in fail:
        print("   - %s" % s)
    if not fail:
        print("   全部通过")
    conn.close()
    return len(fail)


def main():
    ap = argparse.ArgumentParser(description="按截止日期回填创建/修改时间（最小改动）")
    ap.add_argument("--plan", required=True, help="计划 JSON")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--verify", action="store_true", help="只读验证")
    ap.add_argument("--tag", help="备份标签")
    ap.add_argument("--backup-dir", help="备份目录")
    ap.add_argument("--store", help="显式指定 store 路径（副本演练用）")
    ap.add_argument("--export", help="verify 用的导出 JSON；省略则实时调 remindctl")
    ap.add_argument("--no-export", action="store_true",
                    help="verify 跳过导出层（仅用于全库副本演练；主库验收不要用）")
    ap.add_argument("--original", help="verify 用的备份 -original.json，做差分审计")
    ap.add_argument("--force", action="store_true", help="有前置问题时仍强制写入")
    a = ap.parse_args()

    plan = load_plan(a.plan)
    path, _, _ = rdb.find_active_store(a.store)
    conn = rdb.connect(path)
    lpk, rows = select_rows(conn, plan)
    updates, issues, warnings = build_updates(conn, plan, lpk, rows)
    rows_total = rdb.total_rows(conn)
    conn.close()

    if a.verify:
        sys.exit(1 if verify(path, plan, updates, a.original, a.export,
                             a.no_export) else 0)

    print_report(updates, issues, warnings, rows_total, plan)
    if issues and not a.force:
        print("存在前置问题，已停止。")
        sys.exit(2)
    if not a.apply:
        print("DRY-RUN：未写入任何数据。")
        return
    tag = a.tag or ("pre-" + os.path.splitext(os.path.basename(a.plan))[0])
    apply(path, updates, tag, a.backup_dir)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
