#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全库时间线归一化：统一创建时间 + 业务时间整体平移 + 冲突修正。

  python3 normalize_timeline.py --plan /tmp/plan.json                      # dry-run
  python3 normalize_timeline.py --plan /tmp/plan.json --apply --tag pre-norm
  python3 normalize_timeline.py --plan /tmp/plan.json --verify \
      --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
      --export /tmp/export.json

用户口径（2026-11-07 确认）：
  1. 创建时间早于 T=2026-11-01 07:00 的事项，全部统一为 T（418 条）。
  2. 其中早于 T 的截止/完成时间，整体平移 +15 天（保留 HH:MM、日期序列、
     逾期关系），最早截止 10-17 08:00 → 11-01 08:00。
  3. 辅助字段对齐：早于 T 的 ZSTARTDATE / 横幅痕迹置 T；这些事项的
     ZLASTMODIFIEDDATE 也置 T。
  4. 覆盖范围是全库：创建时间 >= T 的事项不改创建时间，仅清理遗留冲突
     （ZSTARTDATE 早于创建、已完成项横幅晚于完成）。

必要联动（不能省）：
  * 截止平移时，REMCDAlarm 的 ZDATECOMPONENTSDATA 同步对齐到新截止时刻，
    否则快照层 alarmDate != dueDate。
  * ZDISPLAYDATEDATE 跟随截止平移，保持原有镜像关系。全天事项的显示日期
    天然比截止早 8 小时，属正常锚点，**不**强行对齐到 T。
  * 不改 ZCOMPLETED / ZALLDAY / 时区列，不改 L4 系统表与父表 ZCREATIONDATE。

默认 dry-run；--apply 才在单事务里写入，写入前生成一致性备份与全部目标行
原值。--verify 纯只读：目标值 + 差分审计 + 闹钟对齐 + 导出层 + 完整性。
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb
import verify_export as ve

MAIN_CHANGED_COLS = {
    "ZCREATIONDATE", "ZLASTMODIFIEDDATE", "ZDUEDATE", "ZCOMPLETIONDATE",
    "ZDISPLAYDATEDATE", "ZSTARTDATE", "ZLASTBANNERPRESENTATIONDATE",
}
# remindd / Reminders.app 会在裸 SQL 写入前后自行刷新的列。备份与写入之间
# 发生这类变化属于外部并发写入，不是脚本误改：只提示，不判差分审计失败。
SYSTEM_VOLATILE = {
    "Z_OPT", "ZLASTBANNERPRESENTATIONDATE", "ZLASTMODIFIEDDATE",
    "ZCKSERVERRECORDDATA", "ZRESOLUTIONTOKENMAP_V3_JSONDATA",
    "ZSPOTLIGHTINDEXCOUNT", "ZCKCLOUDSTATE", "ZCKIDENTIFIER",
}


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    d = dt.datetime.strptime(p["target"], "%Y-%m-%d %H:%M")
    p["_T"] = rdb.to_cd(d)
    p.setdefault("shift_days", 15)
    if not isinstance(p["shift_days"], int) or p["shift_days"] <= 0:
        raise ValueError("shift_days 必须是正整数")
    p["_D"] = p["shift_days"] * 86400
    p.setdefault("align_aux_to_target", True)
    p.setdefault("clean_conflicts_outside", True)
    return p


def build_changes(conn, plan):
    """只读构造全部改动。returns (changes, stats)

    changes 每项：{pk, in_scope, sets, cols, old, new_due, alarm_updates, why}
      sets        : 主表 SET 子句用的 {列名: 新值}
      alarm_updates : [(trigger_pk, bytes), ...]
    """
    T, D = plan["_T"], plan["_D"]
    rows = conn.execute(
        "SELECT * FROM %s WHERE COALESCE(ZMARKEDFORDELETION,0)=0 "
        "ORDER BY Z_PK" % rdb.MAIN_TABLE).fetchall()
    changes = []
    stats = {"total": len(rows), "in_scope": 0, "out_scope": 0,
             "due_shifted": 0, "completion_shifted": 0, "alarms_aligned": 0,
             "start_aligned": 0, "banner_aligned": 0,
             "outside_start_cleared": 0, "banner_conflicts_cleared": 0,
             "lastmod_conflicts_cleared": 0}

    for r in rows:
        pk = r["Z_PK"]
        cre = r["ZCREATIONDATE"]
        if cre is None:
            continue
        in_scope = float(cre) < T
        sets, why = {}, []

        if in_scope:
            stats["in_scope"] += 1
            sets["ZCREATIONDATE"] = T
            sets["ZLASTMODIFIEDDATE"] = T
            why.append("创建/修改→T")

            due = r["ZDUEDATE"]
            new_due = None
            if due is not None and float(due) < T:
                new_due = int(due) + D
                sets["ZDUEDATE"] = new_due
                stats["due_shifted"] += 1
                why.append("截止+%dd" % plan["shift_days"])
                if r["ZDISPLAYDATEDATE"] is not None:
                    # 保持原有镜像差值（全天项恒差 8 小时，具体时刻项相等）
                    sets["ZDISPLAYDATEDATE"] = int(r["ZDISPLAYDATEDATE"]) + D
            comp = r["ZCOMPLETIONDATE"]
            if comp is not None and float(comp) < T:
                sets["ZCOMPLETIONDATE"] = int(comp) + D
                stats["completion_shifted"] += 1
                why.append("完成+%dd" % plan["shift_days"])

            if plan["align_aux_to_target"]:
                if r["ZSTARTDATE"] is not None and float(r["ZSTARTDATE"]) < T:
                    sets["ZSTARTDATE"] = T
                    stats["start_aligned"] += 1
                    why.append("开始→T")
                b = r["ZLASTBANNERPRESENTATIONDATE"]
                if b is not None and float(b) < T:
                    sets["ZLASTBANNERPRESENTATIONDATE"] = T
                    stats["banner_aligned"] += 1
                    why.append("横幅→T")

            # 全库覆盖：in_scope 条也可能有「横幅晚于完成」的遗留冲突
            # （完成/横幅都在 T 之后，没被上面的对齐规则碰到）
            if plan["clean_conflicts_outside"] and r["ZCOMPLETED"]:
                b_after = sets.get("ZLASTBANNERPRESENTATIONDATE",
                                   r["ZLASTBANNERPRESENTATIONDATE"])
                comp_after = sets.get("ZCOMPLETIONDATE", r["ZCOMPLETIONDATE"])
                if (b_after is not None and comp_after is not None
                        and float(b_after) > float(comp_after)):
                    sets["ZLASTBANNERPRESENTATIONDATE"] = None
                    stats["banner_conflicts_cleared"] += 1
                    why.append("清理横幅>完成")

            # 闹钟组件联动：截止平移后对齐到新截止时刻
            alarm_updates = []
            if new_due is not None:
                for al in rdb.alarm_chain(conn, pk):
                    j = al["trigger_json"]
                    if not isinstance(j, dict):
                        continue
                    _, blob = rdb.align_alarm_components(j, new_due)
                    alarm_updates.append((al["resolved_trigger_pk"], blob))
                    stats["alarms_aligned"] += 1
        else:
            stats["out_scope"] += 1
            new_due = None
            alarm_updates = []
            if plan["clean_conflicts_outside"]:
                s = r["ZSTARTDATE"]
                if s is not None and float(s) < float(cre):
                    sets["ZSTARTDATE"] = None
                    stats["outside_start_cleared"] += 1
                    why.append("清理遗留开始时间")
                lm = r["ZLASTMODIFIEDDATE"]
                if lm is not None and float(lm) < float(cre):
                    sets["ZLASTMODIFIEDDATE"] = cre
                    stats["lastmod_conflicts_cleared"] += 1
                    why.append("清理修改<创建")
                b = r["ZLASTBANNERPRESENTATIONDATE"]
                if (r["ZCOMPLETED"] and b is not None
                        and r["ZCOMPLETIONDATE"] is not None
                        and float(b) > float(r["ZCOMPLETIONDATE"])):
                    sets["ZLASTBANNERPRESENTATIONDATE"] = None
                    stats["banner_conflicts_cleared"] += 1
                    why.append("清理横幅>完成")

        if not sets and not alarm_updates:
            continue
        changes.append({
            "pk": pk, "in_scope": in_scope, "sets": sets,
            "cols": set(sets), "old": dict(r), "new_due": new_due,
            "alarm_updates": alarm_updates, "why": why,
        })
    return changes, stats


def print_report(changes, stats, plan, rows_total):
    T = rdb.fmt(plan["_T"])
    print("=" * 112)
    print("全库时间线归一化（北京时间 UTC+8）  T=%s  平移 +%d 天" %
          (T, plan["shift_days"]))
    print("=" * 112)
    for k, label in [("total", "全库事项"), ("in_scope", "创建 < T，统一为 T"),
                     ("out_scope", "创建 >= T，保持不动"),
                     ("due_shifted", "截止/显示日期平移"),
                     ("completion_shifted", "完成时间平移"),
                     ("alarms_aligned", "闹钟组件联动对齐"),
                     ("start_aligned", "ZSTARTDATE 对齐到 T"),
                     ("banner_aligned", "横幅痕迹对齐到 T"),
                     ("outside_start_cleared", "范围外：清理遗留开始时间"),
                     ("banner_conflicts_cleared", "全库：清理横幅晚于完成"),
                     ("lastmod_conflicts_cleared", "全库：清理修改早于创建")]:
        print("  %-28s %4d 条" % (label, stats[k]))
    print("-" * 112)
    print("抽样前后对照（前 8 条有业务时间平移的事项）：")
    sample = [x for x in changes if x["new_due"] is not None][:8]
    print("%5s %-24s | %-17s %-17s | %-17s %-17s | %-17s %-17s" %
          ("PK", "标题", "创建(旧)", "创建(新)", "截止(旧)", "截止(新)",
           "完成(旧)", "完成(新)"))
    for x in sample:
        o = x["old"]
        print("%5d %-24s | %-17s %-17s | %-17s %-17s | %-17s %-17s" %
              (x["pk"], str(o["ZTITLE"])[:22], rdb.fmt(o["ZCREATIONDATE"]),
               rdb.fmt(x["sets"].get("ZCREATIONDATE", o["ZCREATIONDATE"])),
               rdb.fmt(o["ZDUEDATE"]), rdb.fmt(x["sets"].get("ZDUEDATE", o["ZDUEDATE"])),
               rdb.fmt(o["ZCOMPLETIONDATE"]),
               rdb.fmt(x["sets"].get("ZCOMPLETIONDATE", o["ZCOMPLETIONDATE"]))))
    print("-" * 112)
    print("将执行 %d 条主表 UPDATE + %d 条闹钟 JSON UPDATE；全库 %d 条（不应变化）" %
          (len([x for x in changes if x["sets"]]), stats["alarms_aligned"], rows_total))
    print("不改：ZCOMPLETED / ZALLDAY / 时区列 / 循环规则 / L4 系统表 / 父表 ZCREATIONDATE")
    print("显示日期：仅随截止平移，保持全天项 8 小时锚点差，不强行对齐 T")
    print("=" * 112)


def write_dryrun_detail(changes, path):
    out = []
    for x in changes:
        o = x["old"]
        out.append({
            "pk": x["pk"], "title": o["ZTITLE"], "in_scope": x["in_scope"],
            "why": x["why"],
            "old": {k: (rdb.fmt(v) if k in MAIN_CHANGED_COLS and v is not None else v)
                    for k, v in o.items() if k in MAIN_CHANGED_COLS},
            "new": {k: (rdb.fmt(v) if k in MAIN_CHANGED_COLS and v is not None else v)
                    for k, v in x["sets"].items()},
            "alarm_updates": len(x["alarm_updates"]),
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("完整前后对照明细：%s（%d 条）" % (path, len(out)))


def apply(path, changes, tag, backup_dir):
    pks = [x["pk"] for x in changes if x["sets"]]
    b = rdb.backup_store(path, tag, backup_dir, pks)
    print("已备份：%s" % b["db"])
    print("原值  ：%s" % b["original"])
    print("备份校验：%d 行 / integrity=%s" % (b["rows"], b["integrity"]))
    # 写库前的计划快照必须落盘：--verify 若基于「写入后的库」重算计划，
    # 会只看到残余差异，差分审计失去意义。
    root = backup_dir or rdb.BACKUP_ROOT
    snap_path = os.path.join(root, tag + "-changes.json")
    snap = [{"pk": x["pk"],
             "sets": {k: ({"__hex__": v.hex()}
                          if isinstance(v, (bytes, memoryview)) else v)
                      for k, v in x["sets"].items()},
             "new_due": x["new_due"]} for x in changes]
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    print("计划快照：%s" % snap_path)
    conn = rdb.connect(path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        n_main = n_alarm = 0
        for x in changes:
            if x["sets"]:
                cols = list(x["sets"])
                sql = ("UPDATE %s SET %s WHERE Z_PK=?" %
                       (rdb.MAIN_TABLE,
                        ",".join("%s=?" % c for c in cols)))
                conn.execute(sql, tuple(x["sets"][c] for c in cols) + (x["pk"],))
                n_main += 1
            for tpk, blob in x["alarm_updates"]:
                conn.execute("UPDATE %s SET ZDATECOMPONENTSDATA=? WHERE Z_PK=?" %
                             rdb.OBJECT_TABLE, (blob, tpk))
                n_alarm += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    print("写入完成：%d 条主表 + %d 条闹钟 JSON；integrity_check=%s；全库 %d 条" %
          (n_main, n_alarm, rdb.integrity(conn), rdb.total_rows(conn)))
    conn.close()


def shaped_for_export(row):
    """把库内时间线换算成 EventKit 导出口径，供 ve.check_export_row 比较。

    全天事项的 ZDUEDATE 是「当天 08:00 北京」日期锚点，而 remindctl 导出的是
    「当天 00:00 北京」，恒差 8 小时。这是正常形态，不是数据错误；通用验证器
    check_export_row 直接比绝对时刻会把 231 条全天项全判为失败。这里只在
    本脚本的验收层做形态归一，不改公共验证器（避免影响其它脚本与单测）。
    """
    d = dict(row)
    if (d.get("ZDUEDATE") is not None
            and (d.get("ZALLDAY") or d.get("ZDISPLAYDATEISALLDAY"))):
        d["ZDUEDATE"] = float(d["ZDUEDATE"]) - 8 * 3600
    return d


def load_changes(path):
    """加载写库前的计划快照（apply 时由 <tag>-changes.json 落盘）。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for x in raw:
        sets = {k: (bytes.fromhex(v["__hex__"])
                    if isinstance(v, dict) and "__hex__" in v else v)
                for k, v in x["sets"].items()}
        out.append({"pk": x["pk"], "sets": sets, "cols": set(sets),
                    "new_due": x["new_due"]})
    return out


def decode_original(obj):
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


def verify(path, plan, changes, original_path, export_path, skip_export=False):
    conn = rdb.connect(path)
    items = None
    by_uuid = None
    if not skip_export:
        items = ve.load_export(export_path, 90)
        by_uuid = ve.index_by_uuid(items)
    orig = None
    if original_path:
        with open(original_path, encoding="utf-8") as f:
            orig = decode_original(json.load(f))

    fail = []
    external = []
    for x in changes:
        pk = x["pk"]
        row = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                                rdb.MAIN_TABLE, (pk,)).fetchone())
        for col, want in x["sets"].items():
            if row[col] != want:
                fail.append("Z_PK=%d %s 期望 %s 实际 %s" %
                            (pk, col, rdb.fmt(want) if col in MAIN_CHANGED_COLS else want,
                             rdb.fmt(row[col]) if col in MAIN_CHANGED_COLS else row[col]))
        if orig and pk in orig:
            changed = {k for k in orig[pk] if orig[pk][k] != row.get(k)}
            unexpected = changed - x["cols"] - SYSTEM_VOLATILE
            if unexpected:
                fail.append("Z_PK=%d 计划外列变化：%s" % (pk, sorted(unexpected)))
            volatile = (changed - x["cols"]) & SYSTEM_VOLATILE
            if volatile:
                external.append((pk, sorted(volatile)))
        # 闹钟组件必须等于新截止时刻（仅对平移了截止的事项）
        if x["new_due"] is not None:
            chains = rdb.alarm_chain(conn, pk)
            target = rdb.to_bj(x["new_due"])
            for al in chains:
                j = al["trigger_json"]
                if not isinstance(j, dict):
                    fail.append("Z_PK=%d 闹钟 JSON 无法解析" % pk)
                    continue
                parts = tuple(j.get(k) for k in
                              ("year", "month", "day", "hour", "minute"))
                if parts != (target.year, target.month, target.day,
                             target.hour, target.minute):
                    fail.append("Z_PK=%d 闹钟组件 %s ≠ 新截止 %s" %
                                (pk, parts, rdb.fmt(x["new_due"])))
        if by_uuid is not None:
            uid = bytes(row["ZIDENTIFIER"]).hex().lower()
            ex = by_uuid.get(uid)
            ex2 = dict(ex) if ex else None
            # 无截止日期的说明类事项：库内 ZALLDAY=1 但导出 dueDateIsAllDay=false，
            # 属既有口径差异，跳过该项比较。
            if ex2 and row["ZDUEDATE"] is None:
                ex2.pop("dueDateIsAllDay", None)
            rules = {"alarm": "due"} if (row["ZDUEDATE"] and not row["ZALLDAY"]) \
                else {"alarm": "keep"}
            f, _ = ve.check_export_row(pk, shaped_for_export(row), ex2,
                                       rules, None)
            for s in f:
                fail.append("Z_PK=%d 导出层 %s" % (pk, s))

    print("=" * 104)
    print("验证（只读）  store=%s" % os.path.basename(path))
    print("=" * 104)
    print("目标值/差分审计 : %d 条（对照 %s）" %
          (len(changes), os.path.basename(original_path) if orig else "无"))
    print("闹钟组件对齐   : %d 条" %
          sum(1 for x in changes if x["new_due"] is not None))
    print("导出层校验     : %s" %
          ("副本演练已跳过" if skip_export else
           "%d 条（来源：%s）" % (len(items),
                                os.path.basename(export_path) if export_path
                                else "remindctl all --json")))
    print("完整性检查     : %s" % rdb.integrity(conn))
    print("全库提醒条数   : %d" % rdb.total_rows(conn))
    if external:
        print("外部并发写入提示 : %d 条（系统刷新 %s，非脚本改动）" %
              (len(external), "/".join(sorted(SYSTEM_VOLATILE))))
        print("   PK: %s" % ",".join(str(pk) for pk, _ in external[:12]))
    print("未通过项       : %d" % len(fail))
    for s in fail[:40]:
        print("   - %s" % s)
    if len(fail) > 40:
        print("   ... 另有 %d 项" % (len(fail) - 40))
    if not fail:
        print("   全部通过")
    conn.close()
    return len(fail)


def main():
    ap = argparse.ArgumentParser(description="全库时间线归一化（默认 dry-run）")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--tag")
    ap.add_argument("--backup-dir")
    ap.add_argument("--store", help="副本演练用")
    ap.add_argument("--export")
    ap.add_argument("--no-export", action="store_true", help="仅副本演练用")
    ap.add_argument("--original")
    ap.add_argument("--changes",
                    help="verify 用的写库前计划快照；省略则从 --original 推导")
    ap.add_argument("--detail", help="dry-run 完整前后对照 JSON 输出路径")
    a = ap.parse_args()

    plan = load_plan(a.plan)
    path, _, _ = rdb.find_active_store(a.store)

    if a.verify:
        cp = a.changes
        if not cp and a.original:
            cp = a.original.replace("-original.json", "-changes.json")
        if not cp or not os.path.exists(cp):
            raise ValueError("需要 --changes（或可从 --original 推导的 "
                             "<tag>-changes.json）才能按写库前的计划验收")
        changes = load_changes(cp)
        sys.exit(1 if verify(path, plan, changes, a.original, a.export,
                             a.no_export) else 0)

    conn = rdb.connect(path)
    changes, stats = build_changes(conn, plan)
    rows_total = rdb.total_rows(conn)
    print_report(changes, stats, plan, rows_total)
    if a.detail:
        write_dryrun_detail(changes, a.detail)
    conn.close()

    if not a.apply:
        print("DRY-RUN：未写入任何数据。")
        return
    tag = a.tag or ("pre-" + os.path.splitext(os.path.basename(a.plan))[0])
    apply(path, changes, tag, a.backup_dir)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
