#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已完成事项：按截止时间回填「创建 / 最后修改 / 完成」三列，其余字段一律不动。

  python3 edit_completion.py --plan /tmp/plan.json \
      --emit-plan /tmp/verify-plan.json                         # dry-run
  python3 edit_completion.py --plan /tmp/plan.json --apply --tag pre-litter
  python3 edit_completion.py --plan /tmp/plan.json --verify \
      --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json

用户口径：「创建时间和最后编辑时间改为当天 07:00；完成时间改为截止时间前
30 分钟」。「当天」= 每条事项**各自截止日期**的北京自然日（与
edit_creation.py / rdb.creation_from_due() 口径一致），不是操作当天。

只发一条三列 UPDATE：

    UPDATE ZREMCDREMINDER
       SET ZCREATIONDATE=?, ZLASTMODIFIEDDATE=?, ZCOMPLETIONDATE=?
     WHERE Z_PK=?

截止时间、完成标记、显示日期镜像、全天/时区列、闹钟、ZSTARTDATE、
ZLASTBANNERPRESENTATIONDATE、ZACKNOWLEDGEDDATE 一律不动。这与
edit_times.py 不同：后者面向「回填一整套历史时间」，会连带改截止时间、
全天/时区、闹钟 JSON 并清理痕迹，越过「只改三个时间字段」的范围；
edit_creation.py 则只改两列且仅针对未完成事项。

默认 dry-run；--apply 才在单事务里写入，写入前生成一致性备份与目标行原值。
--verify 纯只读：目标值 + 差分审计（除三列外无变化）+ 导出层 + 完整性。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb
import verify_export as ve

CHANGED_COLS = ("ZCREATIONDATE", "ZLASTMODIFIEDDATE", "ZCOMPLETIONDATE")


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    if not p.get("list") or not p.get("title"):
        raise ValueError("计划需要 list 与 title")
    p.setdefault("create_time", "07:00")
    rdb.parse_hm(p["create_time"])          # 提前校验 HH:MM 格式
    p.setdefault("complete_offset_minutes", 30)
    off = p["complete_offset_minutes"]
    if not isinstance(off, int) or isinstance(off, bool) or off <= 0:
        raise ValueError("complete_offset_minutes 必须是正整数")
    p.setdefault("completed_only", True)
    return p


def select_rows(conn, plan):
    """只读选目标。targets 省略时自动按 list + title + 已完成筛选。"""
    lpk = rdb.find_list_pk(conn, plan["list"])
    if lpk is None:
        raise ValueError("找不到列表 %r" % plan["list"])
    if plan.get("targets"):
        pks = [int(t["pk"]) for t in plan["targets"]]
        ph = ",".join("?" * len(pks))
        rows = conn.execute(
            "SELECT * FROM %s WHERE Z_PK IN (%s) ORDER BY Z_PK" %
            (rdb.MAIN_TABLE, ph), pks).fetchall()
    else:
        cond = "AND COALESCE(ZCOMPLETED,0)=1 " if plan["completed_only"] else ""
        rows = conn.execute(
            "SELECT * FROM %s WHERE ZLIST=? AND ZTITLE=? %s"
            "AND COALESCE(ZMARKEDFORDELETION,0)=0 ORDER BY Z_PK" %
            (rdb.MAIN_TABLE, cond), (lpk, plan["title"])).fetchall()
    return lpk, rows


def build_updates(conn, plan, lpk, rows):
    """返回 (updates, issues, warnings)。每条只有一条三列 UPDATE。"""
    updates, issues, warnings = [], [], []
    off = plan["complete_offset_minutes"]
    for r in rows:
        pk = r["Z_PK"]
        if r["ZLIST"] != lpk:
            issues.append("Z_PK=%d 不属于列表 %r" % (pk, plan["list"]))
            continue
        if r["ZTITLE"] != plan["title"]:
            issues.append("Z_PK=%d 标题是 %r，与计划 %r 不符" %
                          (pk, r["ZTITLE"], plan["title"]))
            continue
        if plan["completed_only"] and not r["ZCOMPLETED"]:
            issues.append("Z_PK=%d 未完成，不符合「已完成」筛选" % pk)
            continue
        if rdb.active_recurrence(conn, pk):
            issues.append("Z_PK=%d 带活跃循环规则" % pk)
            continue
        due = r["ZDUEDATE"]
        if due is None:
            issues.append("Z_PK=%d 没有截止日期，无法推导" % pk)
            continue

        due_i = int(due)
        create = rdb.creation_from_due(due_i, plan["create_time"])
        complete = due_i - off * 60
        if not (create < complete < due_i):
            issues.append("Z_PK=%d 不满足 创建 %s < 完成 %s < 截止 %s" %
                          (pk, rdb.fmt(create), rdb.fmt(complete),
                           rdb.fmt(due_i)))
            continue
        days = {rdb.to_bj(x).date() for x in (create, complete, due_i)}
        if len(days) != 1:
            issues.append("Z_PK=%d 三条时间不在同一北京自然日" % pk)
            continue

        # 语义提示：这些列本次按用户要求**不改动**，但与新的时间线存在矛盾，
        # 列为提示而非失败项，是否另行清理由用户决定（与 edit_creation.py 一致）。
        if r["ZSTARTDATE"] is not None and float(r["ZSTARTDATE"]) < create:
            warnings.append(
                "Z_PK=%d 的 ZSTARTDATE=%s 早于新创建时间（本次不改该列）" %
                (pk, rdb.fmt(r["ZSTARTDATE"])))
        banner = r["ZLASTBANNERPRESENTATIONDATE"]
        if banner is not None and float(banner) > complete:
            warnings.append(
                "Z_PK=%d 的横幅痕迹 %s 晚于新完成时间（本次不改该列）" %
                (pk, rdb.fmt(banner)))
        alarms = rdb.alarm_chain(conn, pk)
        if not alarms:
            warnings.append("Z_PK=%d 无闹钟对象（本次不改闹钟）" % pk)
        elif alarms[0]["ack"] is not None:
            warnings.append("Z_PK=%d 闹钟有确认痕迹（本次不改闹钟）" % pk)

        updates.append({
            "pk": pk,
            "due": due_i,
            "due_day": rdb.to_bj(due_i).date().isoformat(),
            "due_hm": rdb.to_bj(due_i).strftime("%H:%M"),
            "create": create,
            "complete": complete,
            "complete_hm": rdb.to_bj(complete).strftime("%H:%M"),
            "old_cre": r["ZCREATIONDATE"],
            "old_mod": r["ZLASTMODIFIEDDATE"],
            "old_comp": r["ZCOMPLETIONDATE"],
            "sql": "UPDATE %s SET ZCREATIONDATE=?, ZLASTMODIFIEDDATE=?, "
                   "ZCOMPLETIONDATE=? WHERE Z_PK=?" % rdb.MAIN_TABLE,
            "args": (create, create, complete, pk),
            "alarms": len(alarms),
        })
    return updates, issues, warnings


def print_report(updates, issues, warnings, rows_total, plan):
    print("=" * 116)
    print("已完成事项：按截止时间回填创建/最后修改/完成时间"
          "（北京时间 UTC+8，最小改动三列）")
    print("=" * 116)
    print("列表=%r  标题=%r  创建=截止当天 %s  完成=截止前 %d 分钟  "
          "仅已完成=%s  目标条数=%d" %
          (plan["list"], plan["title"], plan["create_time"],
           plan["complete_offset_minutes"], plan["completed_only"],
           len(updates)))
    print("%5s %-11s %-17s | %-17s %-17s | %-17s %-17s | %-17s %-17s" %
          ("PK", "截止日期", "截止时间", "创建(旧)", "创建=修改(新)",
           "完成(旧)", "完成(新)", "修改(旧)", "闹钟"))
    print("-" * 116)
    for u in updates:
        print("%5d %-11s %-17s | %-17s %-17s | %-17s %-17s | %-17s %d 个" %
              (u["pk"], u["due_day"], u["due_hm"], rdb.fmt(u["old_cre"]),
               rdb.fmt(u["create"]), rdb.fmt(u["old_comp"]),
               rdb.fmt(u["complete"]), rdb.fmt(u["old_mod"]), u["alarms"]))
    print("-" * 116)
    print("只写三列：ZCREATIONDATE / ZLASTMODIFIEDDATE / ZCOMPLETIONDATE；"
          "截止、完成标记、全天/时区、闹钟、痕迹一律不动")
    print("预计语句：%d 条 UPDATE；全库提醒条数：%d（不应变化）" %
          (len(updates), rows_total))
    if warnings:
        print("语义提示：%d 项（本次按用户要求不改动这些列）" % len(warnings))
        for w in warnings:
            print("   - %s" % w)
    if issues:
        print("前置问题：%d 项" % len(issues))
        for s in issues:
            print("   ! %s" % s)
    else:
        print("前置校验：全部通过（列表/标题/已完成/无循环/创建<完成<截止/同一北京自然日）")
    print("=" * 116)


def emit_verify_plan(plan, updates, path):
    """生成 verify.py / verify_export.py 兼容的计划文件（只读辅助产物）。

    rules.clear=[] 表示本次不清理 ZSTARTDATE / 横幅痕迹，避免体检把
    「按用户要求保留的既有痕迹」误报为失败。
    """
    doc = {
        "list": plan["list"],
        "title": plan["title"],
        "rules": {
            "last_modified": "creation",
            "alarm": "due",
            "display_date": "due",
            "completed": 1,
            "all_day": "off",
            "clear": [],
        },
        "targets": [
            {"pk": u["pk"], "date": u["due_day"],
             "create": plan["create_time"], "due": u["due_hm"],
             "complete": u["complete_hm"]}
            for u in updates
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print("已生成体检计划：%s（%d 条 targets）" % (path, len(updates)))


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
    """纯只读：目标值 + 差分审计 + 导出层 + 完整性。返回失败数。

    skip_export 只用于全库副本演练：remindctl 永远读活跃主库，副本上的
    导出层数值必然对不上。主库验收必须跑完整导出层。
    """
    conn = rdb.connect(path)
    if skip_export:
        items, by_uuid = None, None
    else:
        items = ve.load_export(export_path, 90)
        by_uuid = ve.index_by_uuid(items)
    orig = None
    if original_path:
        with open(original_path, encoding="utf-8") as f:
            orig = decode_original(json.load(f))

    fail = []
    for u in updates:
        pk = u["pk"]
        row = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                                rdb.MAIN_TABLE, (pk,)).fetchone())
        cre, mod, comp, due = (row["ZCREATIONDATE"], row["ZLASTMODIFIEDDATE"],
                               row["ZCOMPLETIONDATE"], row["ZDUEDATE"])
        if cre != u["create"]:
            fail.append("Z_PK=%d 创建期望 %s 实际 %s" %
                        (pk, rdb.fmt(u["create"]), rdb.fmt(cre)))
        if mod != u["create"]:
            fail.append("Z_PK=%d 最后修改期望 %s 实际 %s" %
                        (pk, rdb.fmt(u["create"]), rdb.fmt(mod)))
        if comp != u["complete"]:
            fail.append("Z_PK=%d 完成期望 %s 实际 %s" %
                        (pk, rdb.fmt(u["complete"]), rdb.fmt(comp)))
        if due != u["due"]:
            fail.append("Z_PK=%d 截止时间被改动（期望 %s 实际 %s）" %
                        (pk, rdb.fmt(u["due"]), rdb.fmt(due)))
        if not row["ZCOMPLETED"]:
            fail.append("Z_PK=%d 完成标记被改动" % pk)
        if not (cre < comp < due):
            fail.append("Z_PK=%d 不满足 创建<完成<截止" % pk)
        elif len({rdb.to_bj(x).date() for x in (cre, comp, due)}) != 1:
            fail.append("Z_PK=%d 三条时间不同天(北京)" % pk)
        if orig and pk in orig:
            changed = {k for k in orig[pk] if orig[pk][k] != row.get(k)}
            extra = changed - set(CHANGED_COLS)
            if extra:
                fail.append("Z_PK=%d 除三列外还有变化：%s" %
                            (pk, sorted(extra)))
            missing = set(CHANGED_COLS) - changed
            if missing:
                fail.append("Z_PK=%d 目标列未发生变化：%s" %
                            (pk, sorted(missing)))
        if by_uuid is not None:
            uid = bytes(row["ZIDENTIFIER"]).hex().lower()
            f, _ = ve.check_export_row(pk, row, by_uuid.get(uid),
                                       {"alarm": "due"}, None)
            for s in f:
                fail.append("Z_PK=%d 导出层 %s" % (pk, s))

    print("=" * 104)
    print("验证（只读）  store=%s" % os.path.basename(path))
    print("=" * 104)
    print("目标值校验   : %d 条，创建 = 最后修改 = 截止当天 %s；"
          "完成 = 截止前 %d 分钟" %
          (len(updates), plan["create_time"], plan["complete_offset_minutes"]))
    print("差分审计     : %s" %
          ("仅三列变化（对照 %s）" % os.path.basename(original_path)
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
    ap = argparse.ArgumentParser(
        description="已完成事项按截止时间回填三列（最小改动）")
    ap.add_argument("--plan", required=True, help="计划 JSON")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--verify", action="store_true", help="只读验证")
    ap.add_argument("--emit-plan", help="输出 verify.py 兼容的体检计划 JSON")
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
    if a.emit_plan:
        emit_verify_plan(plan, updates, a.emit_plan)
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
