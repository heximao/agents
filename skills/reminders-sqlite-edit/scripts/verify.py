#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读语义体检：验证一批提醒事项在时间线上自洽。

  python3 verify.py --plan /tmp/my-plan.json
  python3 verify.py --pks 12,19,24          # 不核对计划值，只跑通用语义检查

不修改任何数据。目标：未通过项 0 + 闹钟 N/N 对齐 + integrity_check=ok
+ 全库行数不变。
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb

UTC8_TZ_IDS = rdb.UTC8_TZ_IDS

DEFAULT_RULES = {
    "last_modified": "creation",
    "alarm": "due",
    "display_date": "due",
    "completed": 1,
    "all_day": "off",
    "clear": ["ZSTARTDATE", "ZLASTBANNERPRESENTATIONDATE",
              "ZACKNOWLEDGEDDATE"],
}


def components_to_epoch(j):
    """按闹钟 JSON **自己的** timeZone 把日历组件回算成 Core Data epoch 秒。

    旧版本硬编码 UTC+8 回算，导致「组件是北京时间、时区标识是
    America/Los_Angeles」这类错位仍被判为绝对时间一致；时区只能靠另一条
    字符串检查兜底。这里改为按真实时区回算，让组件校验与绝对时间戳校验
    真正相互独立。时区标识非法/缺失时返回 None（判为不通过）。
    """
    tzobj = j.get("timeZone")
    tzid = tzobj.get("identifier") if isinstance(tzobj, dict) else None
    if not tzid:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tzid)          # IANA 标识走真实时区规则（含历史偏移）
    except (ValueError, KeyError, OSError):
        # GMT+0800 这类不是 IANA 标识，仅当它在白名单内才退化为固定 UTC+8
        if tzid not in UTC8_TZ_IDS:
            return None
        tz = rdb.TZ
    try:
        a = dt.datetime(j["year"], j["month"], j["day"],
                        j["hour"], j["minute"], j.get("second", 0),
                        tzinfo=tz)
    except (KeyError, ValueError, TypeError):
        return None
    return rdb.to_cd(a)


def check_one(conn, pk, expect, rules, list_pk=None, title=None):
    """返回 (failures, alarm_ok, alarm_count, row_view)"""
    r = conn.execute(
        "SELECT * FROM %s WHERE Z_PK=?" % rdb.MAIN_TABLE, (pk,)
    ).fetchone()
    if r is None:
        return ["行缺失"], False, 0, None

    f = []
    def bad(name):
        f.append(name)

    cre, mod = r["ZCREATIONDATE"], r["ZLASTMODIFIEDDATE"]
    due, disp = r["ZDUEDATE"], r["ZDISPLAYDATEDATE"]
    comp = r["ZCOMPLETIONDATE"]

    if title and r["ZTITLE"] != title:
        bad("标题不符")
    if list_pk is not None and r["ZLIST"] != list_pk:
        bad("列表不符")

    # 计划值
    if expect:
        for key, col in (("create", cre), ("due", due), ("complete", comp)):
            want = expect["date"] + " " + expect[key]
            if rdb.fmt(col) != want:
                bad("%s 期望 %s 实际 %s" % (key, want, rdb.fmt(col)))

    # 目标语义：当天创建、未再修改、截止前完成
    lm = rules.get("last_modified", "creation")
    if lm == "creation" and mod != cre:
        bad("创建≠修改")
    elif lm == "completion" and mod != comp:
        bad("修改≠完成")
    # 与 edit_times.load_plan 的 rules.completed 保持同一口径，不再硬编码 1
    want_completed = rules.get("completed", 1)
    if want_completed in (0, 1) and r["ZCOMPLETED"] != want_completed:
        bad("完成标记≠%s" % want_completed)
    if None in (cre, comp, due) or not (cre < comp < due):
        bad("非 创建<完成<截止")
    else:
        if len({rdb.to_bj(x).date() for x in (cre, comp, due)}) != 1:
            bad("三条时间不同天(北京)")
    if rules.get("display_date", "due") == "due" and disp != due:
        bad("显示日期≠截止")

    # 具体时刻（HH:MM）的事项不能带全天标记，且必须显式写 UTC+8 显示时区。
    # 全天事项的 ZDUEDATE 是「当天 00:00 UTC」，混淆会产生 8 小时偏差。
    if rules.get("all_day", "off") == "off":
        if r["ZALLDAY"] or r["ZDISPLAYDATEISALLDAY"]:
            bad("被标记为全天")
        tzname = r["ZDISPLAYDATETIMEZONE"]
        if tzname not in UTC8_TZ_IDS:
            bad("显示时区非 UTC+8: %s" % tzname)
        # ZTIMEZONE 是独立列。它为空时 EventKit / remindctl 会把 ZDUEDATE 的
        # 绝对 epoch 秒当成 UTC+8 墙上时间再换算一次，导出的 dueDate 早 8 小时，
        # 于是 alarmDate 与 dueDate 在快照里对不上。SQLite 层看不出这个错误。
        if r["ZTIMEZONE"] not in UTC8_TZ_IDS:
            bad("ZTIMEZONE 非 UTC+8: %s (导出的 dueDate 会早 8 小时)" %
                r["ZTIMEZONE"])
        if r["ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT"] != \
                rdb.DISPLAY_TZ_SECONDS_FROM_GMT:
            bad("显示时区偏移≠%d" % rdb.DISPLAY_TZ_SECONDS_FROM_GMT)

    clear = set(rules.get("clear", []))
    if "ZSTARTDATE" in clear and r["ZSTARTDATE"] is not None:
        bad("有残留开始时间")
    if "ZLASTBANNERPRESENTATIONDATE" in clear and \
            r["ZLASTBANNERPRESENTATIONDATE"] is not None:
        bad("有残留横幅痕迹")

    # 闹钟：组件一致 + 绝对时间戳回算一致，双重校验
    # 规则 due -> 对齐截止时间；'HH:MM' -> 对齐截止当天北京时间的指定时刻；
    # keep -> 跳过；none -> 要求没有闹钟。
    alarm_rule = rules.get("alarm", "due")
    alarms = rdb.alarm_chain(conn, pk)
    alarm_ok = 0
    want_ts = (rdb.alarm_target_ts(due, alarm_rule)
               if alarm_rule not in ("keep", "none") and due is not None
               else None)
    if alarm_rule == "none":
        if alarms:
            bad("规则要求无闹钟，实际 %d 个" % len(alarms))
    elif alarm_rule != "keep":
        if not alarms:
            bad("缺少闹钟")
        for al in alarms:
            # 关联链完整性：trigger 必须存在、实体类型为 18、反向指回 alarm
            if al["resolved_trigger_pk"] is None:
                bad("trigger 行缺失 (alarm=%s)" % al["alarm_pk"])
                continue
            if al["resolved_trigger_ent"] != rdb.TRIGGER_ENT:
                bad("trigger 实体类型=%s (alarm=%s)" %
                    (al["resolved_trigger_ent"], al["alarm_pk"]))
            if al["trigger_ent"] != rdb.TRIGGER_ENT:
                bad("Z17_TRIGGER=%s (alarm=%s)" %
                    (al["trigger_ent"], al["alarm_pk"]))
            if al["trigger_back"] is not None and \
                    al["trigger_back"] != al["alarm_pk"]:
                bad("trigger 反向外键错 (alarm=%s)" % al["alarm_pk"])

            j = al["trigger_json"]
            if not isinstance(j, dict):
                bad("闹钟 JSON 无法解析 (trigger=%s)" % al["trigger_pk"])
                continue
            d = rdb.to_bj(want_ts) if want_ts is not None else None
            parts = tuple(j.get(k) for k in
                          ("year", "month", "day", "hour", "minute"))
            comp_equal = (d is not None and None not in parts and
                          parts == (d.year, d.month, d.day, d.hour, d.minute))
            # 按闹钟 JSON 自己的时区回算，而不是硬编码 UTC+8：这样时区
            # 错位会同时打挂 comp_equal / ts_equal，形成真正的双重校验。
            epoch = components_to_epoch(j)
            ts_equal = (want_ts is not None and epoch is not None and
                        abs(epoch - float(want_ts)) < 1)
            tzobj = j.get("timeZone")
            tzid = tzobj.get("identifier", "") if isinstance(tzobj, dict) else ""
            tz_ok = tzid in UTC8_TZ_IDS
            secs_ok = not (j.get("second", 0) or j.get("nanosecond", 0))
            chain_ok = (al["resolved_trigger_ent"] == rdb.TRIGGER_ENT and
                        al["trigger_ent"] == rdb.TRIGGER_ENT and
                        (al["trigger_back"] is None or
                         al["trigger_back"] == al["alarm_pk"]))
            ack_ok = not ("ZACKNOWLEDGEDDATE" in clear and al["ack"] is not None)
            if not comp_equal:
                bad("闹钟组件≠目标时刻 (alarm=%s)" % al["alarm_pk"])
            if not ts_equal:
                bad("闹钟绝对时间≠目标时刻 (alarm=%s)" % al["alarm_pk"])
            if not secs_ok:
                bad("闹钟秒/纳秒未归零")
            if not tz_ok:
                bad("闹钟时区非 UTC+8: %s" % tzid)
            if not ack_ok:
                bad("有残留确认痕迹 (alarm=%s)" % al["alarm_pk"])
            # alarm_ok 只有在全部闹钟相关检查通过时才 +1。旧版本只要组件
            # 与硬编码回算一致就计数，导致时区错位仍被汇总成「N/N 对齐」。
            if all((comp_equal, ts_equal, tz_ok, secs_ok, chain_ok, ack_ok)):
                alarm_ok += 1

    # 循环关联：与选目标 / 写入阶段口径一致，只算仍生效的规则。
    # 已 ZMARKEDFORDELETION=1 的「待同步删除」行是标准残留态，不算违规。
    if rdb.active_recurrence(conn, pk):
        bad("仍有活跃循环规则关联")

    view = {
        "pk": pk,
        "create": rdb.fmt(cre),
        "due": rdb.fmt(due),
        "complete": rdb.fmt(comp),
        "alarm": "",
    }
    if alarms and isinstance(alarms[0]["trigger_json"], dict):
        # 展示值也按闹钟自身时区回算，避免把错位数据显示成「看起来对」
        epoch = components_to_epoch(alarms[0]["trigger_json"])
        view["alarm"] = rdb.fmt(epoch) if epoch is not None else "?"
    return f, alarm_ok, len(alarms), view


def main():
    ap = argparse.ArgumentParser(description="Reminders 时间语义只读体检")
    ap.add_argument("--plan", help="计划 JSON（同时校验计划值）")
    ap.add_argument("--pks", help="逗号分隔的 Z_PK，不校验计划值")
    ap.add_argument("--store", help="显式指定 store 路径")
    a = ap.parse_args()
    if not a.plan and not a.pks:
        ap.error("需要 --plan 或 --pks")

    plan = None
    if a.plan:
        with open(a.plan, encoding="utf-8") as fh:
            plan = json.load(fh)
        rules = dict(DEFAULT_RULES)
        rules.update(plan.get("rules", {}))
        targets = {t["pk"]: t for t in plan["targets"]}
        pks = list(targets)
    else:
        rules = dict(DEFAULT_RULES)
        targets = {}
        pks = [int(x) for x in a.pks.split(",")]

    path, _, _ = rdb.find_active_store(
        a.store or (plan.get("_store") if plan else None))
    conn = rdb.connect(path)
    list_pk = rdb.find_list_pk(conn, plan["list"]) if plan and plan.get("list") else None

    alarm_rule = rules.get("alarm", "due")
    print("=" * 100)
    print("语义体检（只读）  store=%s" % os.path.basename(path))
    print("闹钟规则：%s  全天规则：%s" %
          (alarm_rule, rules.get("all_day", "off")))
    print("=" * 100)
    print("%5s %-17s %-17s %-17s %-17s %-6s" %
          ("PK", "创建(=修改)", "截止", "完成", "闹钟", "结果"))
    print("-" * 100)

    all_fail, alarm_ok, alarm_total = [], 0, 0
    for pk in pks:
        t = targets.get(pk, {})
        # 多标题计划：target 自带 title 优先于计划级 title
        title = t.get("title") or (plan.get("title") if plan else None)
        f, ok, n, view = check_one(conn, pk, t or None, rules,
                                   list_pk, title)
        alarm_ok += ok
        alarm_total += n
        for name in f:
            all_fail.append((pk, name))
        if view:
            print("%5d %-17s %-17s %-17s %-17s %-6s" %
                  (pk, view["create"], view["due"], view["complete"],
                   view["alarm"] or "(无)", "OK" if not f else "FAIL"))
        else:
            print("%5d %s" % (pk, "行缺失"))

    print("-" * 100)
    if alarm_rule in ("keep", "none"):
        print("闹钟校验：按规则 %s 跳过（库中共 %d 个闹钟对象）" %
              (alarm_rule, alarm_total))
    else:
        print("闹钟 alarm == %s ：%d/%d 条对齐（组件 + 绝对时间戳）" %
              ("dueDate" if alarm_rule == "due" else alarm_rule,
               alarm_ok, alarm_total))
    print("完整性检查           : %s" % rdb.integrity(conn))
    print("全库提醒条数         : %d" % rdb.total_rows(conn))
    print("未通过项             : %d" % len(all_fail))
    for pk, name in all_fail:
        print("   - Z_PK=%d : %s" % (pk, name))
    if not all_fail:
        print("   全部通过")
    conn.close()
    sys.exit(1 if all_fail else 0)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
