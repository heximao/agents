#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按计划 JSON 批量改写 Reminders 时间字段，并联动闹钟/全天标记/痕迹。

默认 dry-run（只打印前后对照，不写库）：
  python3 edit_times.py --plan /tmp/my-plan.json
写入：
  python3 edit_times.py --plan /tmp/my-plan.json --apply --tag pre-my-edit

写入前自动生成一致性备份 + 目标行原值 JSON；所有语句（主表 UPDATE、
闹钟 JSON UPDATE、新建 alarm/trigger INSERT、Z_PRIMARYKEY 计数 UPDATE）
放进同一个 BEGIN IMMEDIATE 事务，任一步异常即 ROLLBACK。

每条 update 统一为 {"kind", "sql", "args", "desc", ...}，apply() 只负责
按序 conn.execute(sql, args)，不再假设所有语句都是 UPDATE ... WHERE Z_PK=?。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb

# 允许清空的列白名单。分属两张表，避免误清空或 SQL 拼接风险
CLEAR_MAIN = {"ZSTARTDATE", "ZLASTBANNERPRESENTATIONDATE",
              "ZDUEDATEDELTAALERTSDATA"}
CLEAR_ALARM = {"ZACKNOWLEDGEDDATE"}


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    if not p.get("targets"):
        raise ValueError("计划里没有 targets")
    p.setdefault("rules", {})
    r = p["rules"]
    r.setdefault("last_modified", "creation")
    # 对话未提及闹钟时间时，默认闹钟时间 = 截止时间。
    # 用户显式给出闹钟时间时写成 'HH:MM'（北京时间，日期取截止当天）。
    r.setdefault("alarm", "due")
    r.setdefault("display_date", "due")
    r.setdefault("completed", 1)
    # 计划里的 due/create/complete 都是 HH:MM 具体时刻，全天标记必须关掉，
    # 并显式写 UTC+8 显示时区，否则 EventKit 会按「日期」重新解释。
    r.setdefault("all_day", "off")
    r.setdefault("clear", ["ZSTARTDATE", "ZLASTBANNERPRESENTATIONDATE",
                           "ZACKNOWLEDGEDDATE"])
    for k, allowed in (("last_modified", {"creation", "completion", "keep"}),
                       ("display_date", {"due", "keep"}),
                       ("all_day", {"off", "keep"})):
        if r[k] not in allowed:
            raise ValueError("rules.%s 只能是 %s" % (k, sorted(allowed)))
    # 值域必须与 verify.py 的 DEFAULT_RULES / check_one 一致，否则计划写
    # completed=0 时写入成功但体检必然报「完成标记≠1」。
    if r["completed"] not in (0, 1, "keep"):
        raise ValueError("rules.completed 只能是 0 / 1 / keep")
    if r["alarm"] not in ("due", "keep", "none"):
        try:
            rdb.parse_hm(r["alarm"])
        except (ValueError, AttributeError, TypeError):
            raise ValueError("rules.alarm 只能是 due / keep / none / 'HH:MM'")
    for col in r["clear"]:
        if col not in CLEAR_MAIN | CLEAR_ALARM:
            raise ValueError("rules.clear 里的 %r 不在白名单，拒绝执行" % col)
    return p


def resolve(target):
    """把 {'date','create','due','complete'} 解析成 Core Data epoch 秒（北京时间）"""
    y, m, d = (int(x) for x in target["date"].split("-"))
    out = {}
    for key, field in (("create", "creation"), ("due", "due"),
                       ("complete", "completion")):
        h, mi = rdb.parse_hm(target[key])
        out[field] = rdb.cd(y, m, d, h, mi)
    return out


def _update_sql(table, sets, pk):
    return "UPDATE %s SET %s WHERE Z_PK=?" % (table, ",".join(sets))


def build_updates(plan):
    """构造但不执行更新。返回 (updates, issues)

    updates 每项都带 kind / sql / args / desc：
      main           主表时间 + 全天/时区 + 痕迹
      object_update  已存在闹钟的 trigger JSON / ack 清空
      object_insert  原本没有闹钟时新建的 alarm + date trigger
      primarykey     把 Z_PRIMARYKEY.Z_MAX 推进到新建对象的最大主键
    """
    path, _, _ = rdb.find_active_store(plan.get("_store"))
    conn = rdb.connect(path)
    list_pk = rdb.find_list_pk(conn, plan["list"]) if plan.get("list") else None
    if plan.get("list") and list_pk is None:
        raise ValueError("找不到列表 %r" % plan["list"])

    pks = [t["pk"] for t in plan["targets"]]
    ph = ",".join("?" * len(pks))
    rows = {r["Z_PK"]: r for r in conn.execute(
        "SELECT * FROM %s WHERE Z_PK IN (%s)" % (rdb.MAIN_TABLE, ph), pks)}

    rules = plan["rules"]
    updates, issues = [], []
    next_pk = rdb.next_object_pk(conn)
    acc = conn.execute(
        "SELECT ZACCOUNT FROM %s WHERE Z_ENT=16 AND ZACCOUNT IS NOT NULL LIMIT 1"
        % rdb.OBJECT_TABLE).fetchone()
    account = acc[0] if acc else 1
    created_alarms = 0
    last_pk_sql = None

    for t in plan["targets"]:
        pk = t["pk"]
        r = rows.get(pk)
        if r is None:
            issues.append("Z_PK=%d 不存在" % pk)
            continue
        if list_pk is not None and r["ZLIST"] != list_pk:
            issues.append("Z_PK=%d 不属于列表 %r（实际 ZLIST=%s）"
                          % (pk, plan["list"], r["ZLIST"]))
        # 多标题计划：每个 target 可自带 title，缺省时回退到计划级 title
        want_title = t.get("title") or plan.get("title")
        if want_title and r["ZTITLE"] != want_title:
            issues.append("Z_PK=%d 标题是 %r，与计划 %r 不符"
                          % (pk, r["ZTITLE"], want_title))
        for parent_col in ("ZPARENTREMINDER", "Z15REMINDERS"):
            if rdb.has_col(conn, rdb.MAIN_TABLE, parent_col) and r[parent_col]:
                issues.append("Z_PK=%d 有循环母本 %s=%s，不要改"
                              % (pk, parent_col, r[parent_col]))
        live_rec = rdb.active_recurrence(conn, pk)
        if live_rec:
            issues.append("Z_PK=%d 带活跃循环规则 %s，违反「不能用有循环的」"
                          % (pk, [x["Z_PK"] for x in live_rec]))

        ts = resolve(t)
        cre, due, comp = ts["creation"], ts["due"], ts["completion"]
        if not (cre < comp < due):
            issues.append("Z_PK=%d 时间不自洽：需 创建 < 完成 < 截止" % pk)
        # 日界必须按北京时间算，不能用 epoch 秒 // 86400（那是 UTC 日界，
        # 会把 07:00 创建、08:00 截止的正常计划误判成跨天）
        days = {rdb.to_bj(x).date() for x in (cre, comp, due)}
        if len(days) != 1:
            issues.append("Z_PK=%d 创建/完成/截止不在同一天(北京时间)" % pk)

        sets = ["ZCREATIONDATE=?", "ZDUEDATE=?", "ZCOMPLETIONDATE=?"]
        args = [cre, due, comp]
        lm = rules["last_modified"]
        if lm == "creation":
            sets.append("ZLASTMODIFIEDDATE=?"); args.append(cre)
        elif lm == "completion":
            sets.append("ZLASTMODIFIEDDATE=?"); args.append(comp)
        if rules["display_date"] == "due":
            sets.append("ZDISPLAYDATEDATE=?"); args.append(due)
        if rules["completed"] in (0, 1):
            sets.append("ZCOMPLETED=?"); args.append(rules["completed"])
        # 非全天 + 显式 UTC+8 显示时区，防止 HH:MM 被按日期重新解释
        if rules["all_day"] == "off":
            for col, val in sorted(rdb.time_specific_columns().items()):
                if rdb.has_col(conn, rdb.MAIN_TABLE, col):
                    sets.append("%s=?" % col); args.append(val)
        for col in sorted(CLEAR_MAIN & set(rules["clear"])):
            if rdb.has_col(conn, rdb.MAIN_TABLE, col):
                sets.append("%s=NULL" % col)

        before = (rdb.fmt(r["ZCREATIONDATE"]), rdb.fmt(r["ZLASTMODIFIEDDATE"]),
                  rdb.fmt(r["ZDUEDATE"]), rdb.fmt(r["ZCOMPLETIONDATE"]))
        after = (rdb.fmt(cre),
                 rdb.fmt({"creation": cre, "completion": comp}.get(
                     lm, r["ZLASTMODIFIEDDATE"])),
                 rdb.fmt(due), rdb.fmt(comp))

        args.append(pk)
        updates.append({
            "kind": "main", "pk": pk, "table": rdb.MAIN_TABLE,
            "sql": _update_sql(rdb.MAIN_TABLE, sets, pk),
            "sets": sets, "args": args,
            "before": before, "after": after, "title": r["ZTITLE"],
            "desc": "创建 %s / 修改 %s / 截止 %s / 完成 %s" % after,
        })

        # --- 闹钟 ---
        alarm_rule = rules["alarm"]
        if alarm_rule == "none":
            for al in rdb.alarm_chain(conn, pk):
                issues.append("Z_PK=%d 有闹钟(alarm=%s)，计划写 none 但未实现删除，"
                              "请改用 due 或手动处理" % (pk, al["alarm_pk"]))
        elif alarm_rule != "keep":
            target_ts = rdb.alarm_target_ts(due, alarm_rule)
            alarms = rdb.alarm_chain(conn, pk)
            if alarms:
                for al in alarms:
                    j = al["trigger_json"]
                    if not isinstance(j, dict):
                        issues.append("Z_PK=%d 闹钟 trigger=%s 的 JSON 无法解析"
                                      % (pk, al["trigger_pk"]))
                        continue
                    new_j, blob = rdb.align_alarm_components(j, target_ts)
                    tz_fixed = new_j.get("timeZone") != j.get("timeZone")
                    updates.append({
                        "kind": "object_update", "pk": al["trigger_pk"],
                        "table": rdb.OBJECT_TABLE,
                        "sql": _update_sql(rdb.OBJECT_TABLE,
                                           ["ZDATECOMPONENTSDATA=?"],
                                           al["trigger_pk"]),
                        "args": [blob, al["trigger_pk"]],
                        "tz_fixed": tz_fixed,
                        "desc": "闹钟 %s -> %s (北京时间)%s" % (
                            {k: (al["trigger_json"] or {}).get(k)
                             for k in ("month", "day", "hour", "minute")},
                            rdb.fmt(target_ts),
                            " [时区归一到 %s]" % rdb.DEFAULT_ALARM_TZ
                            if tz_fixed else ""),
                    })
                    if "ZACKNOWLEDGEDDATE" in rules["clear"] and al["ack"] is not None:
                        updates.append({
                            "kind": "object_update", "pk": al["alarm_pk"],
                            "table": rdb.OBJECT_TABLE,
                            "sql": _update_sql(rdb.OBJECT_TABLE,
                                               ["ZACKNOWLEDGEDDATE=NULL"],
                                               al["alarm_pk"]),
                            "args": [al["alarm_pk"]],
                            "desc": "清除闹钟确认痕迹 (alarm=%s)" % al["alarm_pk"],
                        })
            else:
                # 目标事项原本没有闹钟：新建一对 Core Data 对象行。
                # 不复制任何既有对象的 ZCKSERVERRECORDDATA，避免云端记录错配。
                inserts, last_pk_sql = rdb.build_alarm_inserts(
                    pk, target_ts, next_pk, next_pk + 1, account)
                for label, (sql, ins_args), obj_pk in zip(
                        ("alarm", "trigger"), inserts,
                        (next_pk, next_pk + 1)):
                    updates.append({
                        "kind": "object_insert", "table": rdb.OBJECT_TABLE,
                        "sql": sql, "args": ins_args,
                        "desc": "新建 %s (主键 %d) -> 闹钟 %s (北京时间 UTC+8)"
                                % (label, obj_pk, rdb.fmt(target_ts)),
                    })
                next_pk += 2
                created_alarms += 1

    if last_pk_sql:
        updates.append({
            "kind": "primarykey", "table": "Z_PRIMARYKEY",
            "sql": last_pk_sql[0], "args": last_pk_sql[1],
            "desc": "对象主键计数 Z_MAX 推进到 %d" % last_pk_sql[1][0],
        })
    conn.close()
    return updates, issues


def print_report(updates, issues, rows_total, rules=None):
    rules = rules or {}
    groups = {}
    for u in updates:
        groups.setdefault(u["kind"], []).append(u)
    main = groups.get("main", [])
    obj_upd = groups.get("object_update", [])
    obj_ins = groups.get("object_insert", [])
    pk_upd = groups.get("primarykey", [])

    print("=" * 100)
    print("主表时间改写（北京时间，UTC+8）")
    print("=" * 100)
    print("规则：闹钟=%s  最后修改=%s  显示日期=%s  全天=%s  完成标记=%s" % (
        rules.get("alarm", "due"), rules.get("last_modified", "creation"),
        rules.get("display_date", "due"), rules.get("all_day", "off"),
        rules.get("completed", 1)))
    print("%5s | %-17s %-17s %-17s %-17s" %
          ("PK", "创建(旧)", "修改(旧)", "截止(旧)", "完成(旧)"))
    print("     | %-17s %-17s %-17s %-17s" %
          ("创建(新)", "修改(新)", "截止(新)", "完成(新)"))
    print("-" * 100)
    for u in main:
        print("%5d | %-17s %-17s %-17s %-17s" % ((u["pk"],) + u["before"]))
        print("     | %-17s %-17s %-17s %-17s  <= NEW" % u["after"])
    print("-" * 100)
    if rules.get("all_day", "off") == "off":
        print("全天/时区校正：%d 条 -> ZALLDAY=0, ZDISPLAYDATEISALLDAY=0, "
              "ZDISPLAYDATETIMEZONE=ZTIMEZONE=%s (UTC+8, %d 秒)"
              % (len(main), rdb.DISPLAY_TZ_NAME,
                 rdb.DISPLAY_TZ_SECONDS_FROM_GMT))
        print("  ZTIMEZONE 是独立列：漏写会让导出的 dueDate 早 8 小时，"
              "SQLite 体检测不出来，写入后必须跑 verify_export.py")
    print("联动子对象：已存在闹钟 UPDATE %d 条 / 新建 alarm+trigger INSERT %d 条 "
          "(覆盖 %d 个事项) / 主键计数 UPDATE %d 条" %
          (len(obj_upd), len(obj_ins), len(obj_ins) // 2, len(pk_upd)))
    tz_fixed = sum(1 for u in obj_upd if u.get("tz_fixed"))
    print("闹钟时区归一：%d 个既有闹钟被改写到 %s (UTC+8)，"
          "防止组件按原时区解释产生错位" % (tz_fixed, rdb.DEFAULT_ALARM_TZ))
    for u in (obj_upd + obj_ins)[:4]:
        print("   %s" % u["desc"])
    if len(obj_upd + obj_ins) > 4:
        print("   ... 其余 %d 条同构" % (len(obj_upd + obj_ins) - 4))
    print("-" * 100)
    print("单事务语句合计：%d 条（主表 %d + 对象 UPDATE %d + 对象 INSERT %d "
          "+ 主键计数 %d）" % (len(updates), len(main), len(obj_upd),
                              len(obj_ins), len(pk_upd)))
    print("全库提醒条数：%d（不应变化）" % rows_total)
    if issues:
        print("问题 / 警告：%d 项" % len(issues))
        for s in issues:
            print("   ! %s" % s)
    else:
        print("前置校验：全部通过")
    print("=" * 100)


def apply(conn_path, updates, tag, backup_dir, pks):
    b = rdb.backup_store(conn_path, tag, backup_dir, pks)
    print("已备份：%s" % b["db"])
    if b["original"]:
        print("原值  ：%s" % b["original"])
    print("备份校验：%d 行 / integrity=%s" % (b["rows"], b["integrity"]))

    conn = rdb.connect(conn_path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for u in updates:
            sql = u.get("sql")
            if not sql:  # 兼容旧格式 {table, sets}
                sql = _update_sql(u["table"], u["sets"], u["pk"])
            conn.execute(sql, u["args"])
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise RuntimeError("事务失败已回滚：%s" % e)
    chk = rdb.integrity(conn)
    n = rdb.total_rows(conn)
    conn.close()
    print("写入完成：%d 条语句，integrity_check=%s，全库 %d 条" %
          (len(updates), chk, n))
    print("下一步：python3 scripts/verify.py --plan <计划文件>")


def main():
    ap = argparse.ArgumentParser(description="批量改写 Reminders 时间字段")
    ap.add_argument("--plan", required=True, help="计划 JSON 路径")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--tag", help="备份标签，默认按计划文件名生成")
    ap.add_argument("--backup-dir", help="备份目录")
    ap.add_argument("--store", help="显式指定 store 路径")
    ap.add_argument("--force", action="store_true", help="有警告时仍强制写入")
    a = ap.parse_args()

    plan = load_plan(a.plan)
    if a.store:
        plan["_store"] = a.store
    path, _, _ = rdb.find_active_store(a.store)

    updates, issues = build_updates(plan)
    c = rdb.connect(path)
    rows_total = rdb.total_rows(c)
    c.close()
    print_report(updates, issues, rows_total, plan["rules"])

    if issues and not a.force:
        print("存在前置问题，已停止。修正计划后再跑；确需继续加 --force。")
        sys.exit(2)
    if not a.apply:
        print("DRY-RUN：未写入任何数据。核对上方前置问题为 0、新旧值对照与计划一致后，"
              "用 --apply --tag <标签> 执行。")
        return

    pks = [t["pk"] for t in plan["targets"]]
    tag = a.tag or ("pre-" + os.path.splitext(os.path.basename(a.plan))[0])
    apply(path, updates, tag, a.backup_dir, pks)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
