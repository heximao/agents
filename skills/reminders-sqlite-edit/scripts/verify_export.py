#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读导出交叉验证：把 SQLite 状态与 `remindctl all --json` 的字段逐条对齐。

  python3 scripts/verify_export.py --plan /tmp/my-plan.json
  python3 scripts/verify_export.py --plan /tmp/my-plan.json --export /tmp/export.json
  python3 scripts/verify_export.py --pks 12,19,24 --export /tmp/export.json

为什么必须有这一步：项目快照（`scan_reminders.py`）直接搬运 remindctl 的
`alarmDate` / `dueDate`，分析口径只读快照、不读 SQLite。只跑 `verify.py`
会出现「库里全绿、快照里 alarmDate 为 null 或 dueDate 差 8 小时」的假阳性。
典型成因：

  * 事项没有 `REMCDAlarm` 对象  -> 导出的 alarmDate 为 null；
  * `ZTIMEZONE` 为 NULL          -> 导出的 dueDate 比库内绝对时刻早 8 小时，
                                    而 alarmDate 仍正确，于是「闹钟 ≠ 截止」。

本脚本只读取，不改任何数据。默认调用 `remindctl all --json`（只读，带超时）；
`--export` 可传入已有导出 / 历史快照 JSON，用于离线核对或避免重复调用。
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb
from verify import components_to_epoch

REMINDCTL = shutil.which("remindctl") or "/usr/local/bin/remindctl"


# ---------------------------------------------------------------- 纯函数
def abs_unix(cd_ts):
    """Core Data epoch 秒 -> Unix epoch 秒（UTC 绝对时刻）。纯函数。"""
    if cd_ts is None:
        return None
    return float(cd_ts) + rdb.EPOCH


def parse_export_utc(s):
    """导出 JSON 的 UTC 时间字符串 -> Unix epoch 秒。纯函数，坏值返回 None。"""
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.timestamp()
    except (ValueError, TypeError):
        return None


def iso_utc(cd_ts):
    """Core Data epoch 秒 -> 'YYYY-MM-DDTHH:MM:SSZ'，用于报告。纯函数。"""
    t = abs_unix(cd_ts)
    if t is None:
        return "NULL"
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def export_items(doc):
    """兼容三种输入：remindctl 原始列表 / 快照 {items:[...]} / 单条对象。纯函数。"""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("items"), list):
        return doc["items"]
    if isinstance(doc, dict) and "id" in doc:
        return [doc]
    raise ValueError("导出 JSON 既不是数组，也没有 items 数组")


def index_by_uuid(items):
    """id (带横线 UUID) -> 去横线小写 hex，与 hex(ZIDENTIFIER) 对齐。纯函数。"""
    return {str(x.get("id", "")).replace("-", "").lower(): x
            for x in items if x.get("id")}


def check_export_row(pk, row, ex, rules, target=None, alarm_ts=None):
    """核对单条事项的导出字段。纯函数，返回 (failures, view)。

    row   : ZREMCDREMINDER 的一行（dict 或 sqlite3.Row）
    ex    : 导出 JSON 里对应的一条（dict）
    rules : 计划 rules；target 为 None 时用于 --pks 通用模式
    alarm_ts : 期望的闹钟 Core Data epoch 秒；None 表示按规则求 / 跳过
    """
    f = []
    def bad(s):
        f.append(s)

    def same(field, db_ts, ex_val):
        want, got = abs_unix(db_ts), parse_export_utc(ex_val)
        if want is None and got is None:
            return
        if want is None or got is None or abs(want - got) >= 1:
            bad("%s 期望 %s 实际 %s" % (field, iso_utc(db_ts), ex_val))

    if ex is None:
        return ["导出中找不到该事项 UUID"], None
    if target and target.get("title") and ex.get("title") != target["title"]:
        bad("导出标题 %r ≠ 计划 %r" % (ex.get("title"), target["title"]))

    same("creationDate", row["ZCREATIONDATE"], ex.get("creationDate"))
    same("lastModifiedDate", row["ZLASTMODIFIEDDATE"], ex.get("lastModifiedDate"))
    # 这一条专门抓 ZTIMEZONE 为空导致的 8 小时偏移（库内对、导出错）
    same("dueDate", row["ZDUEDATE"], ex.get("dueDate"))
    # 快照（scan_reminders.py 产出）带 completionDate，remindctl 原始输出不带
    if "completionDate" in ex:
        same("completionDate", row["ZCOMPLETIONDATE"], ex.get("completionDate"))

    if "isCompleted" in ex:
        if bool(ex.get("isCompleted")) != bool(row["ZCOMPLETED"]):
            bad("isCompleted 期望 %s 实际 %s" %
                (bool(row["ZCOMPLETED"]), ex.get("isCompleted")))
    if "dueDateIsAllDay" in ex:
        db_allday = bool(row["ZALLDAY"] or row["ZDISPLAYDATEISALLDAY"])
        if bool(ex.get("dueDateIsAllDay")) != db_allday:
            bad("dueDateIsAllDay 期望 %s 实际 %s" %
                (db_allday, ex.get("dueDateIsAllDay")))

    rule = rules.get("alarm", "due")
    if alarm_ts is None and rule not in ("keep", "none") and row["ZDUEDATE"]:
        alarm_ts = rdb.alarm_target_ts(row["ZDUEDATE"], rule)
    if rule == "none":
        if ex.get("alarmDate"):
            bad("规则 none 但 alarmDate=%s" % ex.get("alarmDate"))
    elif rule != "keep":
        want, got = abs_unix(alarm_ts), parse_export_utc(ex.get("alarmDate"))
        if got is None:
            bad("缺少 alarmDate（库中闹钟对象未反映到导出）")
        elif want is None or abs(want - got) >= 1:
            bad("alarmDate 期望 %s 实际 %s" %
                (iso_utc(alarm_ts), ex.get("alarmDate")))
        # 用户核心语义：闹钟 = 截止时间，必须在快照层也成立。
        # 显式 'HH:MM' 恰好等于截止时刻时同样适用，不能只看 rule=='due'。
        alarm_is_due = (alarm_ts is not None and row["ZDUEDATE"] is not None
                        and abs(float(alarm_ts) - float(row["ZDUEDATE"])) < 1)
        if alarm_is_due and ex.get("alarmDate") and ex.get("dueDate"):
            a, d = parse_export_utc(ex["alarmDate"]), parse_export_utc(ex["dueDate"])
            if a is None or d is None or abs(a - d) >= 1:
                bad("快照层 alarmDate ≠ dueDate（%s vs %s）" %
                    (ex.get("alarmDate"), ex.get("dueDate")))

    view = {
        "pk": pk,
        "due": ex.get("dueDate") or "NULL",
        "alarm": ex.get("alarmDate") or "NULL",
        "created": ex.get("creationDate") or "NULL",
    }
    return f, view


# ---------------------------------------------------------------- 主流程
def load_export(path, timeout):
    if path:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    else:
        try:
            r = subprocess.run([REMINDCTL, "all", "--json"],
                               capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise RuntimeError("调用 %s 失败：%s" % (REMINDCTL, e))
        if r.returncode != 0:
            raise RuntimeError("remindctl 退出码 %d：%s" %
                               (r.returncode, r.stderr.strip()[:300]))
        doc = json.loads(r.stdout)
    return export_items(doc)


def main():
    ap = argparse.ArgumentParser(description="导出层 alarmDate / dueDate 只读交叉验证")
    ap.add_argument("--plan", help="计划 JSON")
    ap.add_argument("--pks", help="逗号分隔 Z_PK（不校验计划值）")
    ap.add_argument("--export", help="已有 remindctl 导出或快照 JSON；省略则实时调用")
    ap.add_argument("--store", help="显式指定 store 路径")
    ap.add_argument("--timeout", type=int, default=90, help="remindctl 超时秒数")
    a = ap.parse_args()
    if not a.plan and not a.pks:
        ap.error("需要 --plan 或 --pks")

    if a.plan:
        with open(a.plan, encoding="utf-8") as f:
            plan = json.load(f)
        rules = {"alarm": "due", "completed": 1, "all_day": "off"}
        rules.update(plan.get("rules", {}))
        targets = plan["targets"]
        pks = [t["pk"] for t in targets]
    else:
        plan = None
        rules = {"alarm": "due"}
        targets = [{"pk": int(x)} for x in a.pks.split(",")]
        pks = [t["pk"] for t in targets]

    path, _, _ = rdb.find_active_store(
        a.store or (plan.get("_store") if plan else None))
    conn = rdb.connect(path)
    items = load_export(a.export, a.timeout)
    by_uuid = index_by_uuid(items)

    print("=" * 104)
    print("导出层交叉验证（只读）  store=%s" % os.path.basename(path))
    print("导出条目：%d  来源：%s  闹钟规则：%s" %
          (len(items), a.export or "remindctl all --json", rules.get("alarm")))
    print("=" * 104)
    print("%5s %-22s %-22s %-22s %-6s" %
          ("PK", "dueDate", "alarmDate", "creationDate", "结果"))
    print("-" * 104)

    all_fail = []
    for t in targets:
        pk = t["pk"]
        row = conn.execute("SELECT * FROM %s WHERE Z_PK=?" % rdb.MAIN_TABLE,
                           (pk,)).fetchone()
        if row is None:
            all_fail.append((pk, "库中行缺失"))
            print("%5d %s" % (pk, "库中行缺失"))
            continue
        uid = bytes(row["ZIDENTIFIER"]).hex().lower() if row["ZIDENTIFIER"] else ""
        ex = by_uuid.get(uid)
        # --pks 模式没有计划：期望闹钟时刻取库内既有闹钟 JSON 的自身时区回算值，
        # 与规则 due 的绝对时刻分开校验，避免把「闹钟本来就不是截止时刻」误报。
        alarm_ts = None
        if rules.get("alarm") == "due" and not (plan and t.get("due")):
            chains = rdb.alarm_chain(conn, pk)
            if chains and isinstance(chains[0]["trigger_json"], dict):
                # components_to_epoch 返回的就是 Core Data epoch 秒，
                # check_export_row 内部会再经 abs_unix() 加 EPOCH，不要再减一次。
                alarm_ts = components_to_epoch(chains[0]["trigger_json"])
        f, view = check_export_row(pk, row, ex, rules, t, alarm_ts)
        for name in f:
            all_fail.append((pk, name))
        if view:
            print("%5d %-22s %-22s %-22s %-6s" %
                  (pk, view["due"], view["alarm"], view["created"],
                   "OK" if not f else "FAIL"))
        else:
            print("%5d %s" % (pk, "导出中找不到"))

    print("-" * 104)
    print("未通过项：%d" % len(all_fail))
    for pk, name in all_fail:
        print("   - Z_PK=%d : %s" % (pk, name))
    if not all_fail:
        print("   全部通过（快照层 alarmDate / dueDate 与库内绝对时刻一致）")
    conn.close()
    sys.exit(1 if all_fail else 0)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
