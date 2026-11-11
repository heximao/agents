#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按计划把一批未完成事项回填成「当天创建 -> 截止前完成」的干净历史。

  python3 complete_planned_batch.py --plan /tmp/plan.json                  # dry-run
  python3 complete_planned_batch.py --plan /tmp/plan.json --apply --tag pre-batch
  python3 complete_planned_batch.py --plan /tmp/plan.json --verify \
      --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json \
      --export /tmp/export.json

计划 JSON：
{
  "list": "life", "title": "喂猫",
  "create": "07:00", "last_modified": "07:00",
  "banner": "creation",          // creation | completion | null | keep
  "clear_ack": true,
  "targets": [
    {"pk": 476, "date": "2026-11-06", "due": "08:00", "complete": "07:30"},
    {"pk": 131, "date": "2026-11-06", "due": "12:00", "complete": "11:30"}
  ]
}

每条单事务写入：主表时间/完成标记/全天时区 + 闹钟 JSON 对齐新截止 +
清空闹钟确认痕迹。`banner=creation` 把横幅放在 [创建, 完成] 区间下界，
符合新建事项「创建即写横幅」的实测行为；确认痕迹因完成早于闹钟触发、
不存在自洽时刻，一律清空。

默认 dry-run；--apply 前生成一致性备份、目标行原值与计划快照。
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

SYSTEM_VOLATILE = {
    "Z_OPT", "ZLASTBANNERPRESENTATIONDATE", "ZLASTMODIFIEDDATE",
    "ZCKSERVERRECORDDATA", "ZRESOLUTIONTOKENMAP_V3_JSONDATA",
    "ZSPOTLIGHTINDEXCOUNT", "ZCKCLOUDSTATE", "ZCKIDENTIFIER",
}


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    if not p.get("targets"):
        raise ValueError("计划需要 targets")
    p.setdefault("create", "07:00")
    p.setdefault("last_modified", "07:00")
    p.setdefault("banner", "creation")
    p.setdefault("clear_ack", True)
    if p["banner"] not in ("creation", "completion", "null", "keep"):
        raise ValueError("banner 只能是 creation / completion / null / keep")
    rdb.parse_hm(p["create"])
    rdb.parse_hm(p["last_modified"])
    return p


def build_changes(conn, plan):
    lpk = rdb.find_list_pk(conn, plan["list"]) if plan.get("list") else None
    changes, issues = [], []
    for t in plan["targets"]:
        pk = int(t["pk"])
        r = conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                         rdb.MAIN_TABLE, (pk,)).fetchone()
        if r is None:
            issues.append("Z_PK=%d 行缺失" % pk)
            continue
        if lpk is not None and r["ZLIST"] != lpk:
            issues.append("Z_PK=%d 不属于列表 %r" % (pk, plan["list"]))
            continue
        if plan.get("title") and r["ZTITLE"] != plan["title"]:
            issues.append("Z_PK=%d 标题 %r != %r" %
                          (pk, r["ZTITLE"], plan["title"]))
            continue
        if rdb.active_recurrence(conn, pk):
            issues.append("Z_PK=%d 带活跃循环规则" % pk)
            continue
        y, m, d = (int(x) for x in t["date"].split("-"))
        ch, cm = rdb.parse_hm(plan["create"])
        mh, mm = rdb.parse_hm(plan["last_modified"])
        dh, dm = rdb.parse_hm(t["due"])
        xh, xm = rdb.parse_hm(t["complete"])
        cre = rdb.cd(y, m, d, ch, cm)
        mod = rdb.cd(y, m, d, mh, mm)
        due = rdb.cd(y, m, d, dh, dm)
        comp = rdb.cd(y, m, d, xh, xm)
        if not (cre <= mod <= comp < due):
            issues.append("Z_PK=%d 不满足 创建<=修改<=完成<截止" % pk)
            continue
        if len({rdb.to_bj(x).date() for x in (cre, mod, comp, due)}) != 1:
            issues.append("Z_PK=%d 四条时间不同天" % pk)
            continue
        alarms = rdb.alarm_chain(conn, pk)
        if not alarms:
            issues.append("Z_PK=%d 无闹钟对象，需另行新建" % pk)
            continue

        sets = {
            "ZCREATIONDATE": cre, "ZLASTMODIFIEDDATE": mod,
            "ZDUEDATE": due, "ZDISPLAYDATEDATE": due,
            "ZCOMPLETIONDATE": comp, "ZCOMPLETED": 1,
            "ZSTARTDATE": None,
        }
        for col, val in rdb.time_specific_columns().items():
            sets[col] = val
        if plan["banner"] == "creation":
            sets["ZLASTBANNERPRESENTATIONDATE"] = cre
        elif plan["banner"] == "completion":
            sets["ZLASTBANNERPRESENTATIONDATE"] = comp
        elif plan["banner"] == "null":
            sets["ZLASTBANNERPRESENTATIONDATE"] = None

        obj = []
        for a in alarms:
            if isinstance(a["trigger_json"], dict):
                _, blob = rdb.align_alarm_components(a["trigger_json"], due)
                obj.append(("json", a["resolved_trigger_pk"], blob))
            if plan["clear_ack"]:
                obj.append(("ack_null", a["alarm_pk"], None))
        changes.append({"pk": pk, "sets": sets, "obj": obj,
                        "old": dict(r), "cre": cre, "due": due,
                        "comp": comp})
    return changes, issues


def print_report(changes, issues, plan):
    print("=" * 112)
    print("按计划回填完成态（北京时间 UTC+8）  创建=修改=%s  横幅=%s  清空确认痕迹=%s" %
          (plan["create"], plan["banner"], plan["clear_ack"]))
    print("=" * 112)
    print("%5s %-12s | %-17s %-17s | %-17s %-17s | %-17s %-6s" %
          ("PK", "日期", "创建(旧)", "创建=修改(新)", "截止(旧)", "截止(新)",
           "完成(新)", "标记"))
    print("-" * 112)
    for x in changes:
        o = x["old"]
        print("%5d %-12s | %-17s %-17s | %-17s %-17s | %-17s %-6s" %
              (x["pk"], rdb.to_bj(x["due"]).date().isoformat(),
               rdb.fmt(o["ZCREATIONDATE"]), rdb.fmt(x["cre"]),
               rdb.fmt(o["ZDUEDATE"]), rdb.fmt(x["due"]),
               rdb.fmt(x["comp"]), "%s→1" % o["ZCOMPLETED"]))
    print("-" * 112)
    print("横幅：%s → 统一 %s（[创建, 完成] 区间下界）；确认痕迹全部清空" %
          (" / ".join(rdb.fmt(x["old"]["ZLASTBANNERPRESENTATIONDATE"])
                      for x in changes), rdb.fmt(changes[0]["cre"])))
    print("-" * 112)
    print("目标：%d 条；主表 UPDATE %d 条 + 闹钟 JSON %d 条 + 确认痕迹清空 %d 条" %
          (len(changes), len(changes),
           sum(1 for x in changes for k, _, _ in x["obj"] if k == "json"),
           sum(1 for x in changes for k, _, _ in x["obj"] if k == "ack_null")))
    if issues:
        print("前置问题 %d 项：" % len(issues))
        for s in issues:
            print("   ! %s" % s)
    else:
        print("前置校验：全部通过（列表/标题/无循环/有闹钟/创建<=修改<=完成<截止/同一天）")
    print("=" * 112)


def apply(path, changes, tag, backup_dir):
    pks = [x["pk"] for x in changes]
    b = rdb.backup_store(path, tag, backup_dir, pks)
    print("已备份：%s" % b["db"])
    print("原值  ：%s" % b["original"])
    root = backup_dir or rdb.BACKUP_ROOT
    cp = os.path.join(root, tag + "-changes.json")
    snap = [{"pk": x["pk"], "sets": x["sets"],
             "obj": [(k, pk) for k, pk, _ in x["obj"]],
             "cre": x["cre"], "due": x["due"], "comp": x["comp"]}
            for x in changes]
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    print("计划快照：%s" % cp)
    conn = rdb.connect(path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for x in changes:
            cols = list(x["sets"])
            conn.execute("UPDATE %s SET %s WHERE Z_PK=?" %
                         (rdb.MAIN_TABLE, ",".join("%s=?" % c for c in cols)),
                         tuple(x["sets"][c] for c in cols) + (x["pk"],))
            for kind, opk, blob in x["obj"]:
                if kind == "json":
                    conn.execute("UPDATE %s SET ZDATECOMPONENTSDATA=? WHERE Z_PK=?" %
                                 rdb.OBJECT_TABLE, (blob, opk))
                else:
                    conn.execute("UPDATE %s SET ZACKNOWLEDGEDDATE=NULL WHERE Z_PK=?" %
                                 rdb.OBJECT_TABLE, (opk,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    print("写入完成：%d 条主表 + %d 条对象表；integrity=%s；全库 %d 条" %
          (len(changes), sum(len(x["obj"]) for x in changes),
           rdb.integrity(conn), rdb.total_rows(conn)))
    conn.close()


def load_changes(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [{"pk": x["pk"], "sets": x["sets"],
             "cols": set(x["sets"]),
             "obj": [tuple(o) for o in x["obj"]],
             "cre": x["cre"], "due": x["due"], "comp": x["comp"]}
            for x in raw]


def decode_original(obj):
    def dec(row):
        return {k: (bytes.fromhex(v["__hex__"])
                    if isinstance(v, dict) and "__hex__" in v else v)
                for k, v in row.items()}
    return {dec(r)["Z_PK"]: dec(r) for r in obj}


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
    for x in changes:
        pk = x["pk"]
        row = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                                rdb.MAIN_TABLE, (pk,)).fetchone())
        for col, want in x["sets"].items():
            if row[col] != want:
                fail.append("Z_PK=%d %s 期望 %r 实际 %r" %
                            (pk, col, want, row[col]))
        if orig and pk in orig:
            changed = {k for k in orig[pk] if orig[pk][k] != row.get(k)}
            extra = changed - x["cols"] - SYSTEM_VOLATILE
            if extra:
                fail.append("Z_PK=%d 计划外列变化：%s" % (pk, sorted(extra)))
        t = rdb.to_bj(x["due"])
        for al in rdb.alarm_chain(conn, pk):
            j = al["trigger_json"]
            if not isinstance(j, dict):
                fail.append("Z_PK=%d 闹钟 JSON 无法解析" % pk)
                continue
            parts = tuple(j.get(k) for k in
                          ("year", "month", "day", "hour", "minute"))
            if parts != (t.year, t.month, t.day, t.hour, t.minute):
                fail.append("Z_PK=%d 闹钟组件 %s != 截止 %s" %
                            (pk, parts, rdb.fmt(x["due"])))
            if al["ack"] is not None:
                fail.append("Z_PK=%d 确认痕迹未清空" % pk)
        # 语义：创建 <= 修改 <= 完成 < 截止，横幅在区间内
        if not (row["ZCREATIONDATE"] <= row["ZLASTMODIFIEDDATE"]
                <= row["ZCOMPLETIONDATE"] < row["ZDUEDATE"]):
            fail.append("Z_PK=%d 时序不自洽" % pk)
        ban = row["ZLASTBANNERPRESENTATIONDATE"]
        if ban is not None and not (row["ZCREATIONDATE"] <= ban <= row["ZCOMPLETIONDATE"]):
            fail.append("Z_PK=%d 横幅不在 [创建, 完成] 区间" % pk)
        if by_uuid is not None:
            uid = bytes(row["ZIDENTIFIER"]).hex().lower()
            ex = by_uuid.get(uid)
            ex2 = dict(ex) if ex else None
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
    print("闹钟/痕迹/时序 : %d 条逐条核对" % len(changes))
    print("导出层校验     : %s" %
          ("副本演练已跳过" if skip_export else
           "%d 条（来源：%s）" % (len(items),
                                os.path.basename(export_path) if export_path
                                else "remindctl all --json")))
    print("完整性检查     : %s" % rdb.integrity(conn))
    print("全库提醒条数   : %d" % rdb.total_rows(conn))
    print("未通过项       : %d" % len(fail))
    for s in fail[:30]:
        print("   - %s" % s)
    if not fail:
        print("   全部通过")
    conn.close()
    return len(fail)


def main():
    ap = argparse.ArgumentParser(description="按计划回填完成态（默认 dry-run）")
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
    changes, issues = build_changes(conn, plan)
    conn.close()
    print_report(changes, issues, plan)
    if issues:
        print("存在前置问题，已停止。")
        sys.exit(2)
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
