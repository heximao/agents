#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全库时间逻辑异常修复：未来完成时间、早于创建的横幅/确认痕迹。

  python3 fix_time_anomalies.py --plan /tmp/plan.json                      # dry-run
  python3 fix_time_anomalies.py --plan /tmp/plan.json --apply --tag pre-fix
  python3 fix_time_anomalies.py --plan /tmp/plan.json --verify \
      --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
      --export /tmp/export.json

修复三类「逻辑不可能」（2026-11-07 全库 530 条体检确认）：

  A1  已完成但完成时间在未来（8 条）。整体回移该条的
      截止 + 闹钟 + 显示日期 + 完成，保持「截止 - 完成」相对关系（真实逾期量
      不变），使 max(截止,完成) 落在 now 之前；按 PK 顺序每条错开 30 分钟，
      避免全挤在同一时刻。
  A9  横幅痕迹早于创建（23 条）。清空 ZLASTBANNERPRESENTATIONDATE。
  A12 闹钟确认痕迹早于创建（17 条）。清空 ZREMCDOBJECT.ZACKNOWLEDGEDDATE。

不修的（已定性为正常形态或业务事实）：
  * 全天事项的 08:00 日期锚点（含新建事项创建晚于锚点）；
  * 创建时系统写入的横幅 = 创建时刻；
  * 真实逾期、提前完成、非全天项未设闹钟、无截止说明类事项。

默认 dry-run；--apply 才在单事务里写入（主表 + 对象表），写入前生成一致性
备份与全部目标行原值，并落盘计划快照供 --verify 使用。
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
from verify import components_to_epoch

MAIN_COLS = {"ZDUEDATE", "ZCOMPLETIONDATE", "ZDISPLAYDATEDATE",
             "ZLASTBANNERPRESENTATIONDATE"}
SYSTEM_VOLATILE = {
    "Z_OPT", "ZLASTBANNERPRESENTATIONDATE", "ZLASTMODIFIEDDATE",
    "ZCKSERVERRECORDDATA", "ZRESOLUTIONTOKENMAP_V3_JSONDATA",
    "ZSPOTLIGHTINDEXCOUNT", "ZCKCLOUDSTATE", "ZCKIDENTIFIER",
}


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    d = dt.datetime.strptime(p["now"], "%Y-%m-%d %H:%M")
    p["_NOW"] = rdb.to_cd(d)
    p.setdefault("safe_buffer_minutes", 60)
    p.setdefault("stagger_minutes", 30)
    return p


def build_changes(conn, plan):
    """只读构造改动。returns (changes, stats)"""
    now = plan["_NOW"]
    safe = now - plan["safe_buffer_minutes"] * 60
    rows = conn.execute(
        "SELECT * FROM %s WHERE COALESCE(ZMARKEDFORDELETION,0)=0 "
        "ORDER BY Z_PK" % rdb.MAIN_TABLE).fetchall()
    stats = {"total": len(rows), "future_completion": 0, "banner_before_create": 0,
             "ack_before_create": 0, "alarm_realigned": 0}

    # --- A1：已完成但完成时间在未来，按 PK 排序错开回移
    a1 = sorted([r for r in rows
                 if r["ZCOMPLETED"] and r["ZCOMPLETIONDATE"]
                 and float(r["ZCOMPLETIONDATE"]) > now],
                key=lambda r: r["Z_PK"])
    by_pk = {}
    for i, r in enumerate(a1):
        due, comp, disp, cre = (r["ZDUEDATE"], r["ZCOMPLETIONDATE"],
                                r["ZDISPLAYDATEDATE"], r["ZCREATIONDATE"])
        target = safe - i * plan["stagger_minutes"] * 60
        target = max(target, float(cre) + 7200)   # 至少比创建晚 2 小时
        if target > now:
            raise ValueError("Z_PK=%d 无法把完成时间压到 now 之前" % r["Z_PK"])
        shift = max(float(due), float(comp)) - target
        # 闹钟 JSON 只写到分钟（秒归零），库内截止/完成必须同为整分钟，
        # 否则快照层 alarmDate != dueDate。Core Data epoch 起点是 UTC 整点，
        # 整除 60 即 UTC/北京整分钟。
        wm = lambda ts: int(ts) // 60 * 60
        new_due, new_comp = wm(due - shift), wm(comp - shift)
        if new_comp <= cre or new_comp > now:
            raise ValueError("Z_PK=%d 新完成时间不在 (创建, now] 内" % r["Z_PK"])
        sets = {"ZDUEDATE": new_due, "ZCOMPLETIONDATE": new_comp}
        if disp is not None:
            sets["ZDISPLAYDATEDATE"] = wm(disp - shift)
        # 回移后不能出现「横幅晚于完成」：把这类横幅收敛到完成时刻
        ban = r["ZLASTBANNERPRESENTATIONDATE"]
        if ban is not None and float(ban) > new_comp:
            sets["ZLASTBANNERPRESENTATIONDATE"] = new_comp
        obj = []
        for al in rdb.alarm_chain(conn, r["Z_PK"]):
            j = al["trigger_json"]
            if not isinstance(j, dict):
                continue
            _, blob = rdb.align_alarm_components(j, new_due)
            obj.append(("json", al["resolved_trigger_pk"], blob))
            stats["alarm_realigned"] += 1
        by_pk[r["Z_PK"]] = {"pk": r["Z_PK"], "sets": sets, "obj": obj,
                            "kind": ["A1"], "old": dict(r), "new_due": new_due,
                            "shift_hours": shift / 3600}
        stats["future_completion"] += 1

    # --- A9：横幅早于创建（清空）
    for r in rows:
        ban, cre = r["ZLASTBANNERPRESENTATIONDATE"], r["ZCREATIONDATE"]
        if ban is None or cre is None or float(ban) >= float(cre):
            continue
        x = by_pk.setdefault(r["Z_PK"],
                             {"pk": r["Z_PK"], "sets": {}, "obj": [],
                              "kind": [], "old": dict(r), "new_due": None,
                              "shift_hours": 0})
        if "ZDUEDATE" not in x["sets"]:   # A1 已回移的条不动横幅
            x["sets"]["ZLASTBANNERPRESENTATIONDATE"] = None
            x["kind"].append("A9")
            stats["banner_before_create"] += 1

    # --- A12：确认痕迹早于创建（清空对象表列）
    for r in rows:
        cre = r["ZCREATIONDATE"]
        for al in rdb.alarm_chain(conn, r["Z_PK"]):
            ack = al["ack"]
            if ack is None or cre is None or float(ack) >= float(cre):
                continue
            x = by_pk.setdefault(r["Z_PK"],
                                 {"pk": r["Z_PK"], "sets": {}, "obj": [],
                                  "kind": [], "old": dict(r), "new_due": None,
                                  "shift_hours": 0})
            x["obj"].append(("ack_null", al["alarm_pk"], None))
            if "A12" not in x["kind"]:
                x["kind"].append("A12")
            stats["ack_before_create"] += 1

    changes = [by_pk[k] for k in sorted(by_pk)]
    return changes, stats


def print_report(changes, stats, plan):
    print("=" * 112)
    print("全库时间逻辑异常修复  now=%s（北京时间 UTC+8）" % rdb.fmt(plan["_NOW"]))
    print("=" * 112)
    for key, label in [("total", "全库事项"),
                       ("future_completion", "A1 已完成但完成在未来（整体回移）"),
                       ("banner_before_create", "A9 横幅早于创建（清空）"),
                       ("ack_before_create", "A12 确认痕迹早于创建（清空）"),
                       ("alarm_realigned", "闹钟组件对齐新截止")]:
        print("  %-34s %4d 条" % (label, stats[key]))
    print("-" * 112)
    print("A1 前后对照（全部 %d 条）：" % stats["future_completion"])
    print("%5s %-24s | %-17s %-17s | %-17s %-17s | %s" %
          ("PK", "标题", "截止(旧)", "截止(新)", "完成(旧)", "完成(新)", "回移"))
    for x in changes:
        if x["new_due"] is None:
            continue
        o = x["old"]
        print("%5d %-24s | %-17s %-17s | %-17s %-17s | -%.1fh" %
              (x["pk"], str(o["ZTITLE"])[:22], rdb.fmt(o["ZDUEDATE"]),
               rdb.fmt(x["sets"]["ZDUEDATE"]), rdb.fmt(o["ZCOMPLETIONDATE"]),
               rdb.fmt(x["sets"]["ZCOMPLETIONDATE"]), x["shift_hours"]))
    print("-" * 112)
    print("将执行 %d 条主表 UPDATE + %d 条对象表 UPDATE；全库 %d 条（不应变化）" %
          (len([x for x in changes if x["sets"]]),
           sum(len(x["obj"]) for x in changes), stats["total"]))
    print("不改：创建/最后修改时间、完成标记、全天与时区列、ZSTARTDATE、循环规则、L4 系统表")
    print("=" * 112)


def apply(path, changes, tag, backup_dir):
    pks = [x["pk"] for x in changes if x["sets"]]
    b = rdb.backup_store(path, tag, backup_dir, pks)
    print("已备份：%s" % b["db"])
    print("原值  ：%s" % b["original"])
    root = backup_dir or rdb.BACKUP_ROOT
    snap_path = os.path.join(root, tag + "-changes.json")
    snap = [{"pk": x["pk"], "sets": x["sets"], "new_due": x["new_due"],
             "obj": [(k, pk) for k, pk, _ in x["obj"]],
             "kind": x["kind"]} for x in changes]
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    print("计划快照：%s" % snap_path)
    conn = rdb.connect(path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        n_main = n_obj = 0
        for x in changes:
            if x["sets"]:
                cols = list(x["sets"])
                conn.execute("UPDATE %s SET %s WHERE Z_PK=?" %
                             (rdb.MAIN_TABLE, ",".join("%s=?" % c for c in cols)),
                             tuple(x["sets"][c] for c in cols) + (x["pk"],))
                n_main += 1
            for kind, opk, blob in x["obj"]:
                if kind == "json":
                    conn.execute("UPDATE %s SET ZDATECOMPONENTSDATA=? WHERE Z_PK=?" %
                                 rdb.OBJECT_TABLE, (blob, opk))
                else:
                    conn.execute("UPDATE %s SET ZACKNOWLEDGEDDATE=NULL WHERE Z_PK=?" %
                                 rdb.OBJECT_TABLE, (opk,))
                n_obj += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    print("写入完成：%d 条主表 + %d 条对象表；integrity_check=%s；全库 %d 条" %
          (n_main, n_obj, rdb.integrity(conn), rdb.total_rows(conn)))
    conn.close()


def load_changes(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for x in raw:
        sets = {k: v for k, v in x["sets"].items()}
        out.append({"pk": x["pk"], "sets": sets, "cols": set(sets),
                    "new_due": x["new_due"], "obj": [tuple(o) for o in x["obj"]],
                    "kind": x["kind"]})
    return out


def decode_original(obj):
    out = {}
    for row in obj:
        d = {k: (bytes.fromhex(v["__hex__"])
                 if isinstance(v, dict) and "__hex__" in v else v)
             for k, v in row.items()}
        out[d["Z_PK"]] = d
    return out


def shaped_for_export(row):
    d = dict(row)
    if (d.get("ZDUEDATE") is not None
            and (d.get("ZALLDAY") or d.get("ZDISPLAYDATEISALLDAY"))):
        d["ZDUEDATE"] = float(d["ZDUEDATE"]) - 8 * 3600
    return d


def verify(path, plan, changes, original_path, export_path, skip_export=False):
    conn = rdb.connect(path)
    by_uuid = None
    items = None
    if not skip_export:
        items = ve.load_export(export_path, 90)
        by_uuid = ve.index_by_uuid(items)
    orig = None
    if original_path:
        with open(original_path, encoding="utf-8") as f:
            orig = decode_original(json.load(f))

    fail = []
    external = []
    now = plan["_NOW"]
    for x in changes:
        pk = x["pk"]
        row = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                                rdb.MAIN_TABLE, (pk,)).fetchone())
        for col, want in x["sets"].items():
            if row[col] != want:
                fail.append("Z_PK=%d %s 期望 %s 实际 %s" %
                            (pk, col,
                             rdb.fmt(want) if col in MAIN_COLS else want,
                             rdb.fmt(row[col]) if col in MAIN_COLS else row[col]))
        if orig and pk in orig:
            changed = {k for k in orig[pk] if orig[pk][k] != row.get(k)}
            unexpected = changed - x["cols"] - SYSTEM_VOLATILE
            if unexpected:
                fail.append("Z_PK=%d 计划外列变化：%s" % (pk, sorted(unexpected)))
            if (changed - x["cols"]) & SYSTEM_VOLATILE:
                external.append(pk)
        # 完成时间不得在未来；不得早于创建
        if row["ZCOMPLETED"] and row["ZCOMPLETIONDATE"]:
            if float(row["ZCOMPLETIONDATE"]) > now:
                fail.append("Z_PK=%d 完成时间仍在未来" % pk)
            if float(row["ZCOMPLETIONDATE"]) < float(row["ZCREATIONDATE"]):
                fail.append("Z_PK=%d 完成早于创建" % pk)
        # 闹钟组件必须等于新截止；确认痕迹必须已清空
        for kind, opk in x["obj"]:
            if kind == "ack_null":
                v = conn.execute("SELECT ZACKNOWLEDGEDDATE FROM %s WHERE Z_PK=?" %
                                 rdb.OBJECT_TABLE, (opk,)).fetchone()
                if v and v[0] is not None:
                    fail.append("Z_PK=%d 确认痕迹未清空 (alarm=%s)" % (pk, opk))
        if x["new_due"] is not None:
            t = rdb.to_bj(x["new_due"])
            for al in rdb.alarm_chain(conn, pk):
                j = al["trigger_json"]
                if not isinstance(j, dict):
                    fail.append("Z_PK=%d 闹钟 JSON 无法解析" % pk)
                    continue
                parts = tuple(j.get(k) for k in
                              ("year", "month", "day", "hour", "minute"))
                if parts != (t.year, t.month, t.day, t.hour, t.minute):
                    fail.append("Z_PK=%d 闹钟组件 %s != 新截止 %s" %
                                (pk, parts, rdb.fmt(x["new_due"])))
        if by_uuid is not None:
            uid = bytes(row["ZIDENTIFIER"]).hex().lower()
            ex = by_uuid.get(uid)
            ex2 = dict(ex) if ex else None
            if ex2 and row["ZDUEDATE"] is None:
                ex2.pop("dueDateIsAllDay", None)
            has = bool(rdb.alarm_chain(conn, pk))
            rules = {"alarm": "due"} if (row["ZDUEDATE"] and not row["ZALLDAY"]
                                        and has) else {"alarm": "keep"}
            f, _ = ve.check_export_row(pk, shaped_for_export(row), ex2,
                                       rules, None)
            for s in f:
                fail.append("Z_PK=%d 导出层 %s" % (pk, s))

    # 全库语义复检（只读）：A 类逻辑不可能项
    allrows = conn.execute(
        "SELECT * FROM %s WHERE COALESCE(ZMARKEDFORDELETION,0)=0" %
        rdb.MAIN_TABLE).fetchall()
    recount = {
        "已完成但完成在未来": 0, "完成<创建": 0, "创建>截止(全天锚点除外)": 0,
        "横幅<创建": 0, "横幅>完成": 0, "确认痕迹<创建": 0,
        "最后修改<创建": 0, "开始<创建": 0, "显示镜像错位(非全天)": 0,
    }
    for r in allrows:
        cre, mod, comp, due, disp, st, ban = (
            r[k] for k in ("ZCREATIONDATE", "ZLASTMODIFIEDDATE",
                           "ZCOMPLETIONDATE", "ZDUEDATE", "ZDISPLAYDATEDATE",
                           "ZSTARTDATE", "ZLASTBANNERPRESENTATIONDATE"))
        if r["ZCOMPLETED"] and comp and float(comp) > now:
            recount["已完成但完成在未来"] += 1
        if cre and comp and float(comp) < float(cre):
            recount["完成<创建"] += 1
        if cre and due and float(cre) > float(due) and not r["ZALLDAY"]:
            recount["创建>截止(全天锚点除外)"] += 1
        if ban and cre and float(ban) < float(cre):
            recount["横幅<创建"] += 1
        if r["ZCOMPLETED"] and ban and comp and float(ban) > float(comp):
            recount["横幅>完成"] += 1
        if mod and cre and float(mod) < float(cre):
            recount["最后修改<创建"] += 1
        if st and cre and float(st) < float(cre):
            recount["开始<创建"] += 1
        if disp and due and not r["ZALLDAY"] and abs(float(due)-float(disp)) > 1:
            recount["显示镜像错位(非全天)"] += 1
        for al in rdb.alarm_chain(conn, r["Z_PK"]):
            if al["ack"] is not None and cre and float(al["ack"]) < float(cre):
                recount["确认痕迹<创建"] += 1

    print("=" * 104)
    print("验证（只读）  store=%s" % os.path.basename(path))
    print("=" * 104)
    print("目标值/差分审计 : %d 条（对照 %s）" %
          (len(changes), os.path.basename(original_path) if orig else "无"))
    print("导出层校验     : %s" %
          ("副本演练已跳过" if skip_export else
           "%d 条（来源：%s）" % (len(items),
                                os.path.basename(export_path) if export_path
                                else "remindctl all --json")))
    if external:
        print("外部并发写入提示 : %d 条（系统刷新，非脚本改动）" % len(external))
    print("完整性检查     : %s" % rdb.integrity(conn))
    print("全库提醒条数   : %d" % rdb.total_rows(conn))
    print("--- 全库语义复检（均应为 0）---")
    for k, v in recount.items():
        print("  %-30s %d" % (k, v))
    print("未通过项       : %d" % (len(fail) + sum(recount.values())))
    for s in fail[:30]:
        print("   - %s" % s)
    if len(fail) > 30:
        print("   ... 另有 %d 项" % (len(fail) - 30))
    if not fail and not any(recount.values()):
        print("   全部通过")
    conn.close()
    return len(fail) + sum(recount.values())


def main():
    ap = argparse.ArgumentParser(description="全库时间逻辑异常修复（默认 dry-run）")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--tag")
    ap.add_argument("--backup-dir")
    ap.add_argument("--store", help="副本演练用")
    ap.add_argument("--export")
    ap.add_argument("--no-export", action="store_true", help="仅副本演练用")
    ap.add_argument("--original")
    ap.add_argument("--changes")
    a = ap.parse_args()

    plan = load_plan(a.plan)
    path, _, _ = rdb.find_active_store(a.store)
    if a.verify:
        cp = a.changes
        if not cp and a.original:
            cp = a.original.replace("-original.json", "-changes.json")
        if not cp or not os.path.exists(cp):
            raise ValueError("需要 --changes（或可从 --original 推导的快照）")
        changes = load_changes(cp)
        sys.exit(1 if verify(path, plan, changes, a.original, a.export,
                             a.no_export) else 0)

    conn = rdb.connect(path)
    changes, stats = build_changes(conn, plan)
    conn.close()
    print_report(changes, stats, plan)
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
