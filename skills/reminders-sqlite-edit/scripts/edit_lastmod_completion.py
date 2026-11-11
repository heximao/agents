#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit_lastmod_completion.py — 最小改动校准「最后修改时间 / 完成时间」。

version : v1.1.0 (2026-11-07)
依赖    : Python 3.9+ 标准库；同目录 rdb.py / verify.py / verify_export.py；
          remindctl 0.3.8（仅导出层只读交叉验证）
用法    :
  python3 edit_lastmod_completion.py --plan /tmp/plan.json
  python3 edit_lastmod_completion.py --plan /tmp/plan.json --apply --tag pre-pushup
  python3 edit_lastmod_completion.py --plan /tmp/plan.json --verify \
      --changes  /tmp/reminders-db-backup-YYYYMMDD/<tag>-changes.json \
      --original /tmp/reminders-db-backup-YYYYMMDD/<tag>-original.json
退出码  : 0 成功 / 1 运行错误 / 2 前置校验未通过 / 3 验证未通过
变化摘要: 首版。面向「保持创建时间不变，只把最后修改时间改成创建时间、
          完成时间改成截止时间前 N 分钟」的口径。与 edit_completion.py 的
          区别：后者会把创建时间一并回填到截止当天指定时刻，并要求三条
          时间同一天；本脚本不改创建时间，允许创建早于完成若干天。

只写主表两列（可选加完成标记）：
    ZLASTMODIFIEDDATE = 现有 ZCREATIONDATE
    ZCOMPLETIONDATE   = ZDUEDATE - complete_offset_minutes * 60
    ZCOMPLETED        = 1                （mark_completed=true 时）
创建时间、截止时间、显示日期镜像、全天/时区列、闹钟、ZSTARTDATE、
确认痕迹、CloudKit 列一律不动。横幅痕迹策略 clear_banner：
    true        整批清空（v1.0 原有行为）
    false       不动（默认）
    "problematic" 仅清空「晚于新完成时间或早于创建时间」的异常项
                 （已完成事项的合理区间为 [创建, 完成]，NULL 不算问题）

计划 JSON：
{
  "list": "life",
  "title": "做俯卧撑",
  "complete_offset_minutes": 30,
  "mark_completed": true,
  "clear_banner": true,
  "targets": [
    {"pk": 144, "due": "2026-11-01 10:00"},
    {"pk": 240, "due": "2026-11-01 18:00"}
  ]
}
targets 必须显式点名主键；due 是可选的交叉校验字符串（北京时间
YYYY-MM-DD HH:MM），与库内 ZDUEDATE 不符直接判前置失败。

默认 dry-run；--apply 才写库，写入前生成一致性备份、目标行整行原值与
计划快照（-changes.json）。--verify 纯只读，用计划快照做目标值校验，
避免「写入后重算计划」导致差分审计失真。
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

# 系统/后台可能自行刷新的列：差分审计里列为提示，不判失败。
SYSTEM_VOLATILE = {
    "Z_OPT", "ZLASTBANNERPRESENTATIONDATE",
    "ZCKSERVERRECORDDATA", "ZRESOLUTIONTOKENMAP_V3_JSONDATA",
    "ZSPOTLIGHTINDEXCOUNT", "ZCKCLOUDSTATE", "ZCKIDENTIFIER",
}


# ---------------------------------------------------------------- 计划
def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    if not p.get("list") or not p.get("title"):
        raise ValueError("计划需要 list 与 title")
    if not p.get("targets"):
        raise ValueError("计划需要 targets（必须显式点名主键，不做扫描式批量改动）")
    p.setdefault("complete_offset_minutes", 30)
    off = p["complete_offset_minutes"]
    if not isinstance(off, int) or isinstance(off, bool) or off <= 0:
        raise ValueError("complete_offset_minutes 必须是正整数")
    p.setdefault("mark_completed", True)
    if not isinstance(p["mark_completed"], bool):
        raise ValueError("mark_completed 必须是布尔值")
    p.setdefault("clear_banner", False)
    cb = p["clear_banner"]
    if isinstance(cb, str):
        if cb != "problematic":
            raise ValueError("clear_banner 字符串仅支持 'problematic'")
    elif not isinstance(cb, bool):
        raise ValueError("clear_banner 必须是布尔值或 'problematic'")
    seen = set()
    for t in p["targets"]:
        pk = int(t["pk"])
        if pk in seen:
            raise ValueError("targets 里出现重复主键 %d" % pk)
        seen.add(pk)
        if t.get("due"):
            dt.datetime.strptime(t["due"], "%Y-%m-%d %H:%M")
    return p


# ---------------------------------------------------------------- 横幅策略（纯函数）
def banner_problematic(banner, creation, completion):
    """已完成事项的横幅合理区间是 [创建, 完成]；NULL 不算问题。

    横幅是系统展示日志：早于创建＝还没创建就展示过，晚于完成＝完成后还弹过提醒。
    """
    if banner is None:
        return False
    b = float(banner)
    return b > completion or b < float(creation)


def wants_clear_banner(plan, banner, creation, completion):
    """clear_banner: True 整批清空 / 'problematic' 仅清有问题的 / False 不动。"""
    cb = plan["clear_banner"]
    if cb is True:
        return True
    if cb == "problematic":
        return banner_problematic(banner, creation, completion)
    return False


def banner_label(plan):
    cb = plan["clear_banner"]
    return {True: "NULL（整批）", False: "保持",
            "problematic": "按问题清理"}.get(cb, str(cb))


# ---------------------------------------------------------------- 前置与计划构建
def build_changes(conn, plan):
    lpk = rdb.find_list_pk(conn, plan["list"])
    if lpk is None:
        raise ValueError("找不到列表 %r" % plan["list"])
    parent_cols = [c for c in ("ZPARENTREMINDER", "Z15REMINDERS")
                   if rdb.has_col(conn, rdb.MAIN_TABLE, c)]
    now = rdb.to_cd(dt.datetime.now(rdb.TZ))
    off = plan["complete_offset_minutes"]
    changes, issues, warnings = [], [], []

    for t in plan["targets"]:
        pk = int(t["pk"])
        r = conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                         rdb.MAIN_TABLE, (pk,)).fetchone()
        if r is None:
            issues.append("Z_PK=%d 行缺失" % pk)
            continue
        if r["ZLIST"] != lpk:
            issues.append("Z_PK=%d 不属于列表 %r" % (pk, plan["list"]))
            continue
        if r["ZTITLE"] != plan["title"]:
            issues.append("Z_PK=%d 标题 %r 与计划 %r 不符" %
                          (pk, r["ZTITLE"], plan["title"]))
            continue
        if r["ZMARKEDFORDELETION"]:
            issues.append("Z_PK=%d 已标记删除" % pk)
            continue
        if rdb.active_recurrence(conn, pk):
            issues.append("Z_PK=%d 带活跃循环规则" % pk)
            continue
        if parent_cols and any(r[c] for c in parent_cols):
            issues.append("Z_PK=%d 是循环/父子母本" % pk)
            continue
        due = r["ZDUEDATE"]
        cre = r["ZCREATIONDATE"]
        if due is None or cre is None:
            issues.append("Z_PK=%d 缺少截止或创建时间" % pk)
            continue
        due_i, cre_i = int(due), float(cre)
        if t.get("due") and rdb.fmt(due_i) != t["due"]:
            issues.append("Z_PK=%d 截止 %s 与计划 %s 不符（拒绝误改行）" %
                          (pk, rdb.fmt(due_i), t["due"]))
            continue
        comp = due_i - off * 60
        if not (cre_i < comp < due_i):
            issues.append("Z_PK=%d 不满足 创建 %s < 完成 %s < 截止 %s" %
                          (pk, rdb.fmt(cre_i), rdb.fmt(comp), rdb.fmt(due_i)))
            continue
        if comp > now:
            issues.append("Z_PK=%d 完成时间 %s 落在未来" % (pk, rdb.fmt(comp)))
            continue

        banner = r["ZLASTBANNERPRESENTATIONDATE"]
        prob = banner_problematic(banner, r["ZCREATIONDATE"], comp)
        sets = {"ZLASTMODIFIEDDATE": r["ZCREATIONDATE"],
                "ZCOMPLETIONDATE": comp}
        if plan["mark_completed"]:
            sets["ZCOMPLETED"] = 1
        if wants_clear_banner(plan, banner, r["ZCREATIONDATE"], comp):
            sets["ZLASTBANNERPRESENTATIONDATE"] = None

        if prob:
            act = "按计划清空" if "ZLASTBANNERPRESENTATIONDATE" in sets else "本次不动该列"
            warnings.append(
                "Z_PK=%d 横幅痕迹 %s 不在 [创建 %s, 完成 %s] 区间（%s）" %
                (pk, rdb.fmt(banner), rdb.fmt(r["ZCREATIONDATE"]),
                 rdb.fmt(comp), act))
        if r["ZSTARTDATE"] is not None and float(r["ZSTARTDATE"]) < cre_i:
            warnings.append("Z_PK=%d 的 ZSTARTDATE 早于创建时间（本次不动该列）" % pk)
        if not r["ZTIMEZONE"]:
            warnings.append("Z_PK=%d 的 ZTIMEZONE 为 NULL，导出 dueDate 可能早 8 小时" % pk)
        alarms = rdb.alarm_chain(conn, pk)
        if not alarms:
            warnings.append("Z_PK=%d 无闹钟对象（本次不动闹钟）" % pk)
        else:
            j = alarms[0]["trigger_json"]
            if not isinstance(j, dict):
                warnings.append("Z_PK=%d 闹钟组件无法解析" % pk)
            else:
                try:
                    ts = components_to_epoch(j)
                    if abs(float(ts) - due_i) >= 1:
                        warnings.append("Z_PK=%d 闹钟 %s 不等于截止 %s（本次不动闹钟）" %
                                        (pk, rdb.fmt(ts), rdb.fmt(due_i)))
                except (ValueError, TypeError, KeyError) as e:
                    warnings.append("Z_PK=%d 闹钟组件无法回算：%s" % (pk, e))
            if alarms[0]["ack"] is not None:
                warnings.append("Z_PK=%d 闹钟有确认痕迹（本次不动）" % pk)

        changes.append({
            "pk": pk,
            "sets": sets,
            "old_cre": r["ZCREATIONDATE"],
            "old_mod": r["ZLASTMODIFIEDDATE"],
            "old_comp": r["ZCOMPLETIONDATE"],
            "old_completed": r["ZCOMPLETED"],
            "due": due_i,
            "comp": comp,
            "banner": banner,
            "banner_problematic": prob,
        })
    return changes, issues, warnings


def print_report(changes, issues, warnings, total_rows, plan):
    print("=" * 132)
    print("最小改动：最后修改时间 = 创建时间；完成时间 = 截止前 %d 分钟"
          "（北京时间 UTC+8）" % plan["complete_offset_minutes"])
    print("=" * 132)
    print("列表=%r  标题=%r  完成标记改为 1 = %s  清空横幅 = %s  目标条数=%d  全库=%d" %
          (plan["list"], plan["title"], plan["mark_completed"],
           plan["clear_banner"], len(changes), total_rows))
    print("%5s %-17s | %-17s %-17s %-17s | %-17s %-17s | %-8s" %
          ("PK", "截止(不动)", "创建(不动)", "修改(旧)", "修改(新)=创建",
           "完成(旧)", "完成(新)", "标记"))
    print("-" * 132)
    for x in changes:
        mark = "%s→%s" % (x["old_completed"],
                          x["sets"].get("ZCOMPLETED", x["old_completed"]))
        print("%5d %-17s | %-17s %-17s %-17s | %-17s %-17s | %-8s" %
              (x["pk"], rdb.fmt(x["due"]), rdb.fmt(x["old_cre"]),
               rdb.fmt(x["old_mod"]), rdb.fmt(x["sets"]["ZLASTMODIFIEDDATE"]),
               rdb.fmt(x["old_comp"]), rdb.fmt(x["comp"]), mark))
    print("-" * 132)
    cols = sorted({c for x in changes for c in x["sets"]})
    print("写入列：%s；其余列（截止/显示镜像/全天与时区/闹钟/开始/确认痕迹）一律不动" %
          ", ".join(cols))
    n_clear = sum(1 for x in changes
                  if "ZLASTBANNERPRESENTATIONDATE" in x["sets"])
    n_prob = sum(1 for x in changes if x.get("banner_problematic"))
    print("横幅痕迹：异常 %d 条 / 清空 %d 条 / 保留 %d 条（策略=%s）" %
          (n_prob, n_clear, len(changes) - n_clear, banner_label(plan)))
    print("预计语句：%d 条主表 UPDATE，单事务提交；全库提醒条数应保持 %d" %
          (len(changes), total_rows))
    if warnings:
        print("语义提示：%d 项" % len(warnings))
        for w in warnings:
            print("   - %s" % w)
    if issues:
        print("前置问题：%d 项" % len(issues))
        for s in issues:
            print("   ! %s" % s)
    else:
        print("前置校验：全部通过（列表/标题/未软删/无循环无母本/截止与计划一致/"
              "创建<完成<截止/完成不在未来）")
    print("=" * 132)


# ---------------------------------------------------------------- 写入
def apply(path, changes, tag, backup_dir):
    pks = [x["pk"] for x in changes]
    b = rdb.backup_store(path, tag, backup_dir, pks)
    print("一致性备份 : %s" % b["db"])
    print("原值快照   : %s" % (b["original"] or "(无)"))
    print("备份校验   : %d 行 / integrity=%s" % (b["rows"], b["integrity"]))
    root = backup_dir or rdb.BACKUP_ROOT
    cp = os.path.join(root, tag + "-changes.json")
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=2)
    print("计划快照   : %s" % cp)

    conn = rdb.connect(path, readonly=False)
    try:
        conn.execute("PRAGMA busy_timeout=8000")
        conn.execute("BEGIN IMMEDIATE")
        for x in changes:
            cols = list(x["sets"])
            conn.execute(
                "UPDATE %s SET %s WHERE Z_PK=?" %
                (rdb.MAIN_TABLE, ",".join("%s=?" % c for c in cols)),
                tuple(x["sets"][c] for c in cols) + (x["pk"],))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    print("写入完成   : %d 条 UPDATE；integrity_check=%s；全库 %d 条" %
          (len(changes), rdb.integrity(conn), rdb.total_rows(conn)))
    conn.close()


def load_changes(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [{"pk": int(x["pk"]), "sets": x["sets"],
             "old_cre": x["old_cre"], "old_mod": x["old_mod"],
             "old_comp": x["old_comp"], "old_completed": x["old_completed"],
             "due": x["due"], "comp": x["comp"], "banner": x["banner"],
             "banner_problematic": x.get("banner_problematic", False)}
            for x in raw]


def decode_original(obj):
    def dec(row):
        return {k: (bytes.fromhex(v["__hex__"])
                    if isinstance(v, dict) and "__hex__" in v else v)
                for k, v in row.items()}
    return {dec(r)["Z_PK"]: dec(r) for r in obj}


# ---------------------------------------------------------------- 验证
def verify(path, plan, changes, original_path, export_path, skip_export=False):
    conn = rdb.connect(path)
    items, by_uuid = None, None
    if not skip_export:
        items = ve.load_export(export_path, 90)
        by_uuid = ve.index_by_uuid(items)
    orig = None
    if original_path:
        with open(original_path, encoding="utf-8") as f:
            orig = decode_original(json.load(f))

    fail, notes = [], []
    for x in changes:
        pk = x["pk"]
        row = dict(conn.execute("SELECT * FROM %s WHERE Z_PK=?" %
                                rdb.MAIN_TABLE, (pk,)).fetchone())
        for col, want in x["sets"].items():
            if row[col] != want:
                fail.append("Z_PK=%d %s 期望 %r 实际 %r" %
                            (pk, col, want, row[col]))
        if row["ZCREATIONDATE"] != x["old_cre"]:
            fail.append("Z_PK=%d 创建时间被改动" % pk)
        if row["ZDUEDATE"] != x["due"]:
            fail.append("Z_PK=%d 截止时间被改动" % pk)
        if row["ZDISPLAYDATEDATE"] != x["due"]:
            fail.append("Z_PK=%d 显示日期镜像被改动" % pk)
        if not (float(row["ZCREATIONDATE"]) < float(row["ZCOMPLETIONDATE"])
                < float(row["ZDUEDATE"])):
            fail.append("Z_PK=%d 时序不自洽" % pk)
        if plan["mark_completed"] and not row["ZCOMPLETED"]:
            fail.append("Z_PK=%d 完成标记未置 1" % pk)
        if orig and pk in orig:
            changed = {k for k in orig[pk] if orig[pk][k] != row.get(k)}
            extra = changed - set(x["sets"]) - SYSTEM_VOLATILE
            if extra:
                fail.append("Z_PK=%d 计划外列变化：%s" % (pk, sorted(extra)))
            volatile = sorted((changed & SYSTEM_VOLATILE) - set(x["sets"]))
            if volatile:
                notes.append("Z_PK=%d 系统易变列被刷新：%s（不判失败）" %
                             (pk, ", ".join(volatile)))
            missing = set(x["sets"]) - changed
            if missing:
                notes.append("Z_PK=%d 原值已等于目标值、无需改动：%s" %
                             (pk, sorted(missing)))
        if by_uuid is not None:
            uid = bytes(row["ZIDENTIFIER"]).hex().lower()
            ex = by_uuid.get(uid)
            f, _ = ve.check_export_row(pk, row, ex, {"alarm": "due"}, None)
            for s in f:
                fail.append("Z_PK=%d 导出层 %s" % (pk, s))

    print("=" * 108)
    print("验证（只读）  store=%s" % os.path.basename(path))
    print("=" * 108)
    print("目标值校验   : %d 条（修改=创建；完成=截止前 %d 分钟；标记=%s；横幅=%s）" %
          (len(changes), plan["complete_offset_minutes"],
           "1" if plan["mark_completed"] else "保持",
           banner_label(plan)))
    print("差分审计     : %s" %
          ("对照 %s" % os.path.basename(original_path) if orig else "未提供 --original，跳过"))
    print("导出层校验   : %s" %
          ("副本演练已跳过" if skip_export else
           "%d 条（来源：%s）" %
           (len(items), os.path.basename(export_path) if export_path
            else "remindctl all --json")))
    print("完整性检查   : %s" % rdb.integrity(conn))
    print("全库提醒条数 : %d" % rdb.total_rows(conn))
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
        description="最小改动校准最后修改/完成时间（默认 dry-run）")
    ap.add_argument("--plan", required=True, help="计划 JSON")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--verify", action="store_true", help="只读验证")
    ap.add_argument("--tag", help="备份标签")
    ap.add_argument("--backup-dir", help="备份目录")
    ap.add_argument("--store", help="显式指定 store 路径（副本演练用）")
    ap.add_argument("--export", help="verify 用的导出 JSON；省略则实时调 remindctl")
    ap.add_argument("--no-export", action="store_true",
                    help="verify 跳过导出层（仅副本演练用）")
    ap.add_argument("--original", help="verify 用的备份 -original.json")
    ap.add_argument("--changes", help="verify 用的 -changes.json 计划快照")
    ap.add_argument("--force", action="store_true",
                    help="有前置问题时仍强制写入（不推荐）")
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
        sys.exit(3 if verify(path, plan, changes, a.original, a.export,
                             a.no_export) else 0)

    conn = rdb.connect(path)
    changes, issues, warnings = build_changes(conn, plan)
    total = rdb.total_rows(conn)
    conn.close()
    print_report(changes, issues, warnings, total, plan)
    if issues and not a.force:
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
    except (ValueError, RuntimeError, sqlite3.Error, OSError,
            json.JSONDecodeError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
