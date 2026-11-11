#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性单测：只测纯函数，不连数据库、不读写任何文件。

  python3 scripts/test_rdb.py
"""
import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rdb


class TestEpochConversion(unittest.TestCase):
    def test_epoch_zero_is_beijing_8am_2001(self):
        # 2001-01-01 00:00 UTC == 2001-01-01 08:00 北京 == Core Data epoch 0
        self.assertEqual(rdb.cd(2001, 1, 1, 8, 0), 0)
        self.assertEqual(rdb.fmt(0), "2001-01-01 08:00")

    def test_roundtrip(self):
        cases = [
            (2026, 11, 1, 7, 0), (2026, 11, 1, 8, 0),
            (2026, 11, 5, 21, 30), (2026, 11, 5, 22, 0),
            (2001, 1, 1, 8, 0), (2038, 1, 19, 11, 14),
        ]
        for y, m, d, h, mi in cases:
            with self.subTest(case=(y, m, d, h, mi)):
                ts = rdb.cd(y, m, d, h, mi)
                back = rdb.to_bj(ts)
                self.assertEqual(
                    (back.year, back.month, back.day, back.hour, back.minute),
                    (y, m, d, h, mi))
                self.assertEqual(rdb.to_cd(back), ts)

    def test_null_and_parse(self):
        self.assertIsNone(rdb.to_bj(None))
        self.assertEqual(rdb.fmt(None), "NULL")
        self.assertEqual(rdb.parse_hm("07:30"), (7, 30))
        self.assertEqual(rdb.parse_hm("22:00"), (22, 0))


class TestDayBoundary(unittest.TestCase):
    """回归：07:00 创建 / 08:00 截止按北京时间是同一天，
    但 epoch 秒 // 86400 是 UTC 日界，会把它们判成跨天。"""

    def test_beijing_same_day(self):
        cre = rdb.cd(2026, 11, 1, 7, 0)
        due = rdb.cd(2026, 11, 1, 8, 0)
        days = {rdb.to_bj(x).date() for x in (cre, due)}
        self.assertEqual(len(days), 1)
        self.assertLess(cre, due)

    def test_utc_integer_division_would_be_wrong(self):
        cre = rdb.cd(2026, 11, 1, 7, 0)
        due = rdb.cd(2026, 11, 1, 8, 0)
        # 记录这个陷阱本身：UTC 日界确实把它们分到两天
        self.assertNotEqual(cre // 86400, due // 86400)

    def test_real_cross_day_is_detected(self):
        cre = rdb.cd(2026, 11, 1, 23, 0)
        due = rdb.cd(2026, 11, 2, 8, 0)
        days = {rdb.to_bj(x).date() for x in (cre, due)}
        self.assertEqual(len(days), 2)


class TestAlarmComponents(unittest.TestCase):
    ORIGINAL = {
        "timeZone": {"identifier": "Asia/Singapore"}, "era": 1,
        "day": 1, "minute": 0, "year": 2026, "second": 0,
        "hour": 12, "nanosecond": 0, "month": 12,
    }

    def test_alignment_matches_due_components_and_absolute_ts(self):
        due = rdb.cd(2026, 11, 1, 8, 0)
        new, blob = rdb.align_alarm_components(self.ORIGINAL, due)
        d = rdb.to_bj(due)
        self.assertEqual(
            (new["year"], new["month"], new["day"], new["hour"], new["minute"]),
            (d.year, d.month, d.day, d.hour, d.minute))
        alarm_dt = dt.datetime(new["year"], new["month"], new["day"],
                               new["hour"], new["minute"],
                               new["second"], tzinfo=rdb.TZ)
        self.assertEqual(rdb.to_cd(alarm_dt), due)

    def test_preserves_timezone_era_and_zeros_seconds(self):
        due = rdb.cd(2026, 11, 5, 22, 0)
        new, blob = rdb.align_alarm_components(self.ORIGINAL, due)
        self.assertEqual(new["timeZone"], {"identifier": "Asia/Singapore"})
        self.assertEqual(new["era"], 1)
        self.assertEqual(new["second"], 0)
        self.assertEqual(new["nanosecond"], 0)
        self.assertEqual(new["hour"], 22)
        self.assertEqual(json.loads(blob.decode("utf-8")), new)

    def test_does_not_mutate_input(self):
        original = dict(self.ORIGINAL)
        rdb.align_alarm_components(original, rdb.cd(2026, 11, 1, 8, 0))
        self.assertEqual(original, self.ORIGINAL)


class TestAlarmTimezoneNormalization(unittest.TestCase):
    """回归：旧版 align_alarm_components 保留原 timeZone。

    本机实测存在 America/Los_Angeles 与无 timeZone 的闹钟；若只把日历
    组件改成北京时间而不改时区标识，系统会按原时区解释组件，产生
    15~16 小时错位，且 dry-run 前置校验毫无提示。
    """
    LA = {
        "timeZone": {"identifier": "America/Los_Angeles"}, "era": 1,
        "year": 2026, "month": 12, "day": 1, "hour": 12,
        "minute": 0, "second": 30, "nanosecond": 5,
    }
    TARGET = rdb.cd(2026, 11, 1, 8, 0)

    def test_non_utc8_timezone_is_replaced(self):
        new, blob = rdb.align_alarm_components(self.LA, self.TARGET)
        self.assertEqual(new["timeZone"],
                         {"identifier": rdb.DEFAULT_ALARM_TZ})
        self.assertIn(new["timeZone"]["identifier"], rdb.UTC8_TZ_IDS)
        self.assertEqual(json.loads(blob.decode("utf-8")), new)

    def test_missing_timezone_is_added(self):
        src = {k: v for k, v in self.LA.items() if k != "timeZone"}
        new, _ = rdb.align_alarm_components(src, self.TARGET)
        self.assertEqual(new["timeZone"],
                         {"identifier": rdb.DEFAULT_ALARM_TZ})

    def test_malformed_timezone_is_added(self):
        src = dict(self.LA, timeZone="not-a-dict")
        new, _ = rdb.align_alarm_components(src, self.TARGET)
        self.assertEqual(new["timeZone"],
                         {"identifier": rdb.DEFAULT_ALARM_TZ})

    def test_existing_utc8_timezone_is_preserved(self):
        src = dict(self.LA, timeZone={"identifier": "Asia/Singapore"})
        new, _ = rdb.align_alarm_components(src, self.TARGET)
        self.assertEqual(new["timeZone"], {"identifier": "Asia/Singapore"})

    def test_other_keys_and_seconds_still_handled(self):
        new, _ = rdb.align_alarm_components(self.LA, self.TARGET)
        self.assertEqual(new["era"], 1)
        self.assertEqual((new["year"], new["month"], new["day"],
                          new["hour"], new["minute"]), (2026, 11, 1, 8, 0))
        self.assertEqual((new["second"], new["nanosecond"]), (0, 0))
        self.assertEqual(self.LA["timeZone"]["identifier"],
                         "America/Los_Angeles")  # 入参未被修改

    def test_old_behavior_would_really_be_wrong(self):
        """证明这个缺陷不是理论问题：按 LA 解释北京组件会差 15 小时。"""
        from zoneinfo import ZoneInfo
        from datetime import datetime
        bj_components = (2026, 11, 1, 8, 0)
        la = datetime(*bj_components, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.assertNotEqual(rdb.to_cd(la), self.TARGET)
        self.assertGreater(abs(rdb.to_cd(la) - self.TARGET), 14 * 3600)


class TestComponentsToEpoch(unittest.TestCase):
    """回归：verify 旧版硬编码 UTC+8 回算，时区错位测不出来。"""
    def _mod(self):
        import verify
        return verify

    def test_utc8_components_match(self):
        v = self._mod()
        j = rdb.new_alarm_components(rdb.cd(2026, 11, 1, 8, 0))
        self.assertEqual(v.components_to_epoch(j), rdb.cd(2026, 11, 1, 8, 0))

    def test_non_utc8_components_do_not_match(self):
        v = self._mod()
        j = rdb.new_alarm_components(rdb.cd(2026, 11, 1, 8, 0))
        j["timeZone"] = {"identifier": "America/Los_Angeles"}
        self.assertNotEqual(v.components_to_epoch(j),
                            rdb.cd(2026, 11, 1, 8, 0))

    def test_missing_or_bad_timezone_returns_none(self):
        v = self._mod()
        j = rdb.new_alarm_components(rdb.cd(2026, 11, 1, 8, 0))
        self.assertIsNone(v.components_to_epoch(dict(j, timeZone={})))
        self.assertIsNone(v.components_to_epoch(
            dict(j, timeZone={"identifier": "Not/A_Zone"})))


class TestAlarmRules(unittest.TestCase):
    """默认闹钟时间 = 截止时间；显式 HH:MM 时取截止当天北京时间。"""

    def test_due_rule_returns_due_unchanged(self):
        due = rdb.cd(2026, 11, 3, 21, 0)
        self.assertEqual(rdb.alarm_target_ts(due, "due"), due)

    def test_explicit_hhmm_uses_due_date_not_utc_date(self):
        # 21:00 北京 == 13:00 UTC，UTC 日界与北京日界仍是同一天，
        # 但 00:00~08:00 北京会落在前一个 UTC 日；用 07:00 覆盖这个陷阱。
        due = rdb.cd(2026, 11, 5, 21, 0)
        target = rdb.alarm_target_ts(due, "07:00")
        d = rdb.to_bj(target)
        self.assertEqual((d.year, d.month, d.day, d.hour, d.minute),
                         (2026, 11, 5, 7, 0))
        self.assertEqual(rdb.to_cd(d), target)

    def test_explicit_equal_to_due_is_identical(self):
        due = rdb.cd(2026, 11, 1, 21, 0)
        self.assertEqual(rdb.alarm_target_ts(due, "21:00"), due)

    def test_same_date_guard_for_early_beijing_hours(self):
        due = rdb.cd(2026, 11, 1, 8, 0)   # 00:00 UTC on 11-01
        target = rdb.alarm_target_ts(due, "07:00")
        self.assertEqual(rdb.to_bj(target).date(), rdb.to_bj(due).date())
        # UTC 日界会把两者判成不同天，证明不能用 ts // 86400
        self.assertNotEqual(target // 86400, due // 86400)


class TestNewAlarmObjects(unittest.TestCase):
    def test_new_components_are_utc8_and_zero_seconds(self):
        ts = rdb.cd(2026, 11, 7, 21, 0)
        j = rdb.new_alarm_components(ts)
        self.assertEqual(j["timeZone"], {"identifier": rdb.DEFAULT_ALARM_TZ})
        self.assertEqual((j["year"], j["month"], j["day"],
                          j["hour"], j["minute"]), (2026, 11, 7, 21, 0))
        self.assertEqual(j["second"], 0)
        self.assertEqual(j["nanosecond"], 0)
        self.assertEqual(j["era"], 1)
        a = dt.datetime(j["year"], j["month"], j["day"], j["hour"],
                        j["minute"], 0, tzinfo=rdb.TZ)
        self.assertEqual(rdb.to_cd(a), ts)

    def test_build_alarm_inserts_shape_and_links(self):
        ts = rdb.cd(2026, 11, 4, 21, 0)
        inserts, pk_update = rdb.build_alarm_inserts(
            123, ts, 3000, 3001, account=1)
        self.assertEqual(len(inserts), 2)
        alarm_sql, alarm_args = inserts[0]
        trig_sql, trig_args = inserts[1]
        self.assertTrue(alarm_sql.startswith("INSERT INTO ZREMCDOBJECT"))
        self.assertTrue(trig_sql.startswith("INSERT INTO ZREMCDOBJECT"))
        self.assertEqual(alarm_sql.count("?"), len(alarm_args))
        self.assertEqual(trig_sql.count("?"), len(trig_args))
        self.assertEqual(alarm_args[0], 3000)     # alarm Z_PK
        self.assertEqual(alarm_args[4], 123)      # ZREMINDER
        self.assertEqual(alarm_args[5], 3001)     # ZTRIGGER
        self.assertEqual(alarm_args[6], rdb.TRIGGER_ENT)
        self.assertEqual(alarm_args[8], 0)        # ZMARKEDFORDELETION
        self.assertEqual(trig_args[0], 3001)      # trigger Z_PK
        self.assertEqual(trig_args[4], 3000)      # ZALARM 反向指回
        self.assertEqual(trig_args[5], 0)
        blob = trig_args[-1]
        j = json.loads(blob.decode("utf-8"))
        self.assertEqual((j["year"], j["month"], j["day"],
                          j["hour"], j["minute"]), (2026, 11, 4, 21, 0))
        self.assertEqual(pk_update[0],
                         "UPDATE Z_PRIMARYKEY SET Z_MAX=? WHERE Z_ENT=?")
        self.assertEqual(pk_update[1], (3001, rdb.OBJECT_ROOT_ENT))
        # 两次构造的 UUID 必须不同（ZIDENTIFIER 上有 UNIQUE 索引）
        _, args2 = rdb.build_alarm_inserts(123, ts, 3002, 3003)[0][0]
        self.assertNotEqual(alarm_args[-1], args2[-1])


class TestTimeSpecificColumns(unittest.TestCase):
    def test_turns_off_all_day_and_pins_utc8(self):
        cols = rdb.time_specific_columns()
        self.assertEqual(cols["ZALLDAY"], 0)
        self.assertEqual(cols["ZDISPLAYDATEISALLDAY"], 0)
        self.assertEqual(cols["ZDISPLAYDATETIMEZONE"], rdb.DISPLAY_TZ_NAME)
        self.assertEqual(cols["ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT"], 8 * 3600)

    def test_due_timezone_column_is_not_forgotten(self):
        """ZTIMEZONE 与 ZDISPLAYDATETIMEZONE 是两个独立列。

        漏写 ZTIMEZONE 时 remindctl 导出的 dueDate 早 8 小时，但 SQLite
        层的 verify.py 看不出来——2026-11-07 实测缺陷。
        """
        cols = rdb.time_specific_columns()
        self.assertEqual(cols["ZTIMEZONE"], rdb.DISPLAY_TZ_NAME)
        self.assertIn(cols["ZTIMEZONE"], rdb.UTC8_TZ_IDS)
        self.assertIn("ZTIMEZONE", cols)
        self.assertNotEqual(cols["ZTIMEZONE"], None)

    def test_epoch_zero_is_utc_midnight(self):
        # Core Data epoch 0 == 2001-01-01 00:00 UTC == 08:00 北京，
        # 这正是全天事项「当天」的锚点：写 HH:MM 时必须同时关掉全天标记。
        self.assertEqual(rdb.cd(2001, 1, 1, 8, 0), 0)
        self.assertEqual(rdb.to_bj(0).hour, 8)


class TestExportCrossCheck(unittest.TestCase):
    """回归：SQLite 全绿、快照 alarmDate 为 null / dueDate 差 8 小时的假阳性。"""
    def _mod(self):
        import verify_export
        return verify_export

    def _row(self, due=None, alarm_rule_due=True):
        due = rdb.cd(2026, 11, 1, 21, 0) if due is None else due
        cre = rdb.cd(2026, 11, 1, 7, 0)
        comp = rdb.cd(2026, 11, 1, 10, 0)
        return {
            "ZCREATIONDATE": cre, "ZLASTMODIFIEDDATE": cre,
            "ZDUEDATE": due, "ZDISPLAYDATEDATE": due,
            "ZCOMPLETIONDATE": comp, "ZCOMPLETED": 1,
            "ZALLDAY": 0, "ZDISPLAYDATEISALLDAY": 0,
        }

    def _ex(self, row, alarm=True, due_shift_hours=0):
        v = self._mod()
        due = v.abs_unix(row["ZDUEDATE"]) + due_shift_hours * 3600
        def iso(t):
            return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        return {
            "creationDate": iso(v.abs_unix(row["ZCREATIONDATE"])),
            "lastModifiedDate": iso(v.abs_unix(row["ZLASTMODIFIEDDATE"])),
            "dueDate": iso(due),
            "alarmDate": iso(v.abs_unix(row["ZDUEDATE"])) if alarm else None,
            "isCompleted": True, "dueDateIsAllDay": False,
        }

    def test_abs_unix_and_iso_roundtrip(self):
        v = self._mod()
        ts = rdb.cd(2026, 11, 1, 21, 0)
        self.assertEqual(v.iso_utc(ts), "2026-11-01T13:00:00Z")
        self.assertEqual(v.parse_export_utc(v.iso_utc(ts)), v.abs_unix(ts))
        self.assertIsNone(v.parse_export_utc(None))
        self.assertIsNone(v.parse_export_utc("not-a-date"))
        self.assertIsNone(v.abs_unix(None))

    def test_export_items_accepts_list_snapshot_and_single(self):
        v = self._mod()
        self.assertEqual(v.export_items([{"id": "a"}]), [{"id": "a"}])
        self.assertEqual(v.export_items({"items": [{"id": "b"}]}), [{"id": "b"}])
        self.assertEqual(v.export_items({"id": "c"}), [{"id": "c"}])
        with self.assertRaises(ValueError):
            v.export_items({"foo": 1})

    def test_index_by_uuid_strips_hyphens(self):
        v = self._mod()
        self.assertEqual(v.index_by_uuid([{"id": "AB-CD"}]), {"abcd": {"id": "AB-CD"}})

    def test_correct_row_passes(self):
        v = self._mod()
        row = self._row()
        f, view = v.check_export_row(37, row, self._ex(row),
                                     {"alarm": "due"})
        self.assertEqual(f, [])
        self.assertEqual(view["due"], view["alarm"])

    def test_eight_hour_due_date_shift_is_detected(self):
        v = self._mod()
        row = self._row()
        ex = self._ex(row, due_shift_hours=-8)
        f, _ = v.check_export_row(37, row, ex, {"alarm": "due"})
        self.assertTrue(any("dueDate" in x for x in f))
        self.assertTrue(any("alarmDate ≠ dueDate" in x for x in f))

    def test_missing_alarm_date_is_detected(self):
        """库里有 REMCDAlarm，但导出 alarmDate 为 null -> 必须报错。"""
        v = self._mod()
        row = self._row()
        f, _ = v.check_export_row(37, row, self._ex(row, alarm=False),
                                  {"alarm": "due"})
        self.assertTrue(any("缺少 alarmDate" in x for x in f))

    def test_explicit_hhmm_equal_to_due_enforces_snapshot_invariant(self):
        v = self._mod()
        row = self._row()
        ex = self._ex(row, due_shift_hours=-8)
        f, _ = v.check_export_row(37, row, ex, {"alarm": "21:00"})
        self.assertTrue(any("alarmDate ≠ dueDate" in x for x in f))

    def test_none_rule_requires_null_alarm_date(self):
        v = self._mod()
        row = self._row()
        f, _ = v.check_export_row(37, row, self._ex(row), {"alarm": "none"})
        self.assertTrue(any("规则 none" in x for x in f))
        f2, _ = v.check_export_row(37, row, self._ex(row, alarm=False),
                                   {"alarm": "none"})
        self.assertEqual(f2, [])

    def test_missing_export_item_is_reported(self):
        v = self._mod()
        f, view = v.check_export_row(37, self._row(), None, {"alarm": "due"})
        self.assertEqual(len(f), 1)
        self.assertIsNone(view)


class TestCreationFromDue(unittest.TestCase):
    """回归：按截止日期回填创建时间，日期必须按北京自然日取。"""
    def test_due_8am_gives_same_day_7am(self):
        due = rdb.cd(2026, 11, 14, 8, 0)
        self.assertEqual(rdb.creation_from_due(due, "07:00"),
                         rdb.cd(2026, 11, 14, 7, 0))

    def test_all_day_anchor_does_not_fall_back_a_day(self):
        # 全天事项 ZDUEDATE 是「当天 08:00 北京 / 00:00 UTC」。
        # 用 UTC 日界切会退回 11-13，这里必须是 11-14。
        due = rdb.cd(2026, 11, 14, 8, 0)
        want = rdb.cd(2026, 11, 14, 7, 0)
        self.assertEqual(rdb.creation_from_due(due), want)
        self.assertNotEqual(due // 86400, want // 86400)

    def test_custom_time_and_none(self):
        due = rdb.cd(2026, 12, 25, 8, 0)
        self.assertEqual(rdb.creation_from_due(due, "06:30"),
                         rdb.cd(2026, 12, 25, 6, 30))
        self.assertIsNone(rdb.creation_from_due(None))

    def test_creation_is_before_due(self):
        for day in range(8, 28):
            due = rdb.cd(2026, 11, day, 8, 0)
            self.assertLess(rdb.creation_from_due(due), due)


class TestCreationOnDate(unittest.TestCase):
    """回归：用户点名固定日期时，不能从 ZDUEDATE 取日，也不能用 UTC 日界。"""
    def test_fixed_date_ignores_due_day(self):
        due = rdb.cd(2026, 11, 14, 8, 0)
        self.assertEqual(rdb.creation_on_date("2026-11-07", "07:00"),
                         rdb.cd(2026, 11, 7, 7, 0))
        self.assertNotEqual(rdb.creation_on_date("2026-11-07", "07:00"),
                            rdb.creation_from_due(due, "07:00"))

    def test_fixed_date_is_beijing_wall_clock(self):
        ts = rdb.creation_on_date("2026-11-07", "07:00")
        d = rdb.to_bj(ts)
        self.assertEqual((d.year, d.month, d.day, d.hour, d.minute),
                         (2026, 11, 7, 7, 0))
        # 北京 11-07 07:00 的绝对时刻是 UTC 11-06 23:00
        self.assertEqual(rdb.fmt(ts), "2026-11-07 07:00")
        self.assertEqual(ts - rdb.cd(2026, 11, 7, 0, 0), 7 * 3600)

    def test_invalid_date_is_rejected(self):
        for bad in ("2026-13-01", "not-a-date", "2026-02-30"):
            with self.assertRaises(ValueError):
                rdb.creation_on_date(bad)

    def test_target_creation_routes_by_plan(self):
        import edit_creation
        due = rdb.cd(2026, 11, 14, 8, 0)
        fixed = {"list": "life", "title": "铲猫砂", "time": "07:00",
                 "date": "2026-11-07", "incomplete_only": True}
        derived = {"list": "life", "title": "铺床", "time": "07:00",
                   "incomplete_only": True}
        self.assertEqual(edit_creation.target_creation(fixed, due),
                         rdb.cd(2026, 11, 7, 7, 0))
        self.assertEqual(edit_creation.target_creation(derived, due),
                         rdb.cd(2026, 11, 14, 7, 0))


class TestEditCreation(unittest.TestCase):
    """确定性检查：最小改动脚本只生成两列 UPDATE，且能还原 hex 原值。"""
    def _mod(self):
        import edit_creation
        return edit_creation

    def _mem(self):
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("""CREATE TABLE ZREMCDREMINDER (
            Z_PK INTEGER PRIMARY KEY, ZLIST INTEGER, ZTITLE TEXT,
            ZCOMPLETED INTEGER, ZMARKEDFORDELETION INTEGER,
            ZDUEDATE REAL, ZCREATIONDATE REAL, ZLASTMODIFIEDDATE REAL,
            ZSTARTDATE REAL, ZDISPLAYDATEDATE REAL, ZCOMPLETIONDATE REAL,
            ZALLDAY INTEGER, ZDISPLAYDATEISALLDAY INTEGER,
            ZTIMEZONE TEXT, ZDISPLAYDATETIMEZONE TEXT,
            ZDISPLAYDATEUPDATEDFORSECONDSFROMGMT INTEGER, ZIDENTIFIER BLOB)""")
        c.execute("""CREATE TABLE ZREMCDOBJECT (
            Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZREMINDER INTEGER,
            ZREMINDER4 INTEGER, ZMARKEDFORDELETION INTEGER, ZTRIGGER INTEGER,
            Z17_TRIGGER INTEGER, ZDATECOMPONENTSDATA BLOB,
            ZACKNOWLEDGEDDATE REAL, ZALARM INTEGER,
            ZFREQUENCY INTEGER, ZINTERVAL INTEGER)""")
        c.execute("""CREATE TABLE ZREMCDBASELIST (
            Z_PK INTEGER PRIMARY KEY, ZNAME TEXT, ZMARKEDFORDELETION INTEGER)""")
        c.execute("INSERT INTO ZREMCDBASELIST VALUES (2,'life',0)")
        due = rdb.cd(2026, 11, 14, 8, 0)
        c.execute("""INSERT INTO ZREMCDREMINDER
            (Z_PK,ZLIST,ZTITLE,ZCOMPLETED,ZMARKEDFORDELETION,ZDUEDATE,
             ZCREATIONDATE,ZLASTMODIFIEDDATE,ZSTARTDATE,ZIDENTIFIER)
            VALUES (9,2,'铺床',0,0,?,?,?,?,?)""",
                  (due, rdb.cd(2026, 1, 9, 22, 19), rdb.cd(2026, 11, 7, 12, 0),
                   rdb.cd(2026, 6, 10, 8, 0), b"\x01" * 16))
        return c

    def test_only_two_columns_are_written(self):
        m, c = self._mod(), self._mem()
        plan = {"list": "life", "title": "铺床", "time": "07:00",
                "incomplete_only": True, "targets": [{"pk": 9}]}
        lpk, rows = m.select_rows(c, plan)
        ups, issues, warns = m.build_updates(c, plan, lpk, rows)
        self.assertEqual(issues, [])
        self.assertEqual(len(ups), 1)
        sql = ups[0]["sql"].upper()
        self.assertIn("ZCREATIONDATE=?", sql)
        self.assertIn("ZLASTMODIFIEDDATE=?", sql)
        for col in ("ZDUEDATE", "ZCOMPLETED", "ZCOMPLETIONDATE", "ZALLDAY",
                    "ZTIMEZONE", "ZSTARTDATE"):
            self.assertNotIn(col + "=", sql, "%s 不应被改写" % col)
        self.assertEqual(ups[0]["args"][0], rdb.cd(2026, 11, 14, 7, 0))
        self.assertEqual(ups[0]["args"][0], ups[0]["args"][1])
        self.assertTrue(any("ZSTARTDATE" in w for w in warns))
        c.close()

    def test_fixed_date_mode_writes_two_columns(self):
        m, c = self._mod(), self._mem()
        plan = {"list": "life", "title": "铺床", "time": "07:00",
                "date": "2026-11-07", "incomplete_only": True,
                "targets": [{"pk": 9}]}
        lpk, rows = m.select_rows(c, plan)
        ups, issues, _ = m.build_updates(c, plan, lpk, rows)
        self.assertEqual(issues, [])
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["args"][0], rdb.cd(2026, 11, 7, 7, 0))
        self.assertEqual(ups[0]["args"][0], ups[0]["args"][1])
        sql = ups[0]["sql"].upper()
        self.assertEqual(sql.count("=?"), 3)   # 两列 SET + 一个 WHERE
        c.close()

    def test_completed_row_is_rejected(self):
        m, c = self._mod(), self._mem()
        c.execute("UPDATE ZREMCDREMINDER SET ZCOMPLETED=1 WHERE Z_PK=9")
        plan = {"list": "life", "title": "铺床", "incomplete_only": True,
                "targets": [{"pk": 9}]}
        lpk, rows = m.select_rows(c, plan)
        ups, issues, _ = m.build_updates(c, plan, lpk, rows)
        self.assertEqual(ups, [])
        self.assertTrue(any("已完成" in s for s in issues))
        c.close()

    def test_decode_original_hex_roundtrip(self):
        m = self._mod()
        raw = [{"Z_PK": 9, "ZIDENTIFIER": {"__hex__": "abcd"},
                "ZDUEDATE": 123.0}]
        out = m.decode_original(raw)
        self.assertEqual(out[9]["ZIDENTIFIER"], bytes.fromhex("abcd"))
        self.assertEqual(out[9]["ZDUEDATE"], 123.0)


class TestBannerPolicy(unittest.TestCase):
    """回归 edit_lastmod_completion 的条件式横幅清理（clear_banner='problematic'）。"""

    @classmethod
    def setUpClass(cls):
        import edit_lastmod_completion as m
        cls.m = m

    def setUp(self):
        self.cre = rdb.cd(2026, 11, 1, 7, 0)
        self.due = rdb.cd(2026, 11, 4, 8, 0)
        self.comp = self.due - 30 * 60
        self.late = rdb.cd(2026, 11, 7, 17, 32)
        self.early = rdb.cd(2026, 10, 31, 9, 0)
        self.inside = rdb.cd(2026, 11, 2, 21, 5)

    def test_problematic_interval(self):
        f = self.m.banner_problematic
        self.assertTrue(f(self.late, self.cre, self.comp))     # 完成后还弹过
        self.assertTrue(f(self.early, self.cre, self.comp))    # 创建前就弹过
        self.assertFalse(f(self.inside, self.cre, self.comp))  # 区间内正常
        self.assertFalse(f(None, self.cre, self.comp))         # NULL 不算问题
        self.assertFalse(f(self.cre, self.cre, self.comp))     # 边界闭合
        self.assertFalse(f(self.comp, self.cre, self.comp))

    def test_wants_clear_banner_three_modes(self):
        w = self.m.wants_clear_banner
        cre, comp = self.cre, self.comp
        self.assertTrue(w({"clear_banner": True}, self.late, cre, comp))
        self.assertTrue(w({"clear_banner": True}, self.inside, cre, comp))
        self.assertFalse(w({"clear_banner": False}, self.late, cre, comp))
        self.assertTrue(w({"clear_banner": "problematic"}, self.late, cre, comp))
        self.assertTrue(w({"clear_banner": "problematic"}, self.early, cre, comp))
        self.assertFalse(w({"clear_banner": "problematic"}, self.inside, cre, comp))
        self.assertFalse(w({"clear_banner": "problematic"}, None, cre, comp))

    def test_banner_label(self):
        b = self.m.banner_label
        self.assertEqual(b({"clear_banner": "problematic"}), "按问题清理")
        self.assertEqual(b({"clear_banner": True}), "NULL（整批）")
        self.assertEqual(b({"clear_banner": False}), "保持")


if __name__ == "__main__":
    unittest.main(verbosity=2)
