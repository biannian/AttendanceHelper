# Copyright (c) iGroup China.
# All rights reserved.
"""
使用时长归类与记账测试。

@author Kai
@date 2026/09/29 15:12
@description 站点标题不入库；锁屏和无操作记为休息
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from attendance_helper.activity_capture import ActivitySample
from attendance_helper.activity_classify import (
    CAT_REST,
    CAT_SLACK,
    CAT_UNKNOWN,
    CAT_WORK,
    IDLE_REST_SECONDS,
    REST_APP_KEY,
    classify_foreground,
    clip_delta,
    host_from_address,
    is_rest_moment,
)
from attendance_helper.activity_tracker import apply_sample


class ActivityClassifyTest(unittest.TestCase):
    """归类规则。"""

    def test_bilibili_keeps_site_not_title(self) -> None:
        """视频标题不能出现在显示名里。"""
        secret = "季度复盘草稿_只此一份"
        identity = classify_foreground(
            "chrome.exe",
            f"{secret}_哔哩哔哩_bilibili - Google Chrome",
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "site:bilibili")
        self.assertEqual(identity.display_name, "哔哩哔哩")
        self.assertEqual(identity.default_category, CAT_SLACK)
        self.assertNotIn(secret, identity.display_name)
        self.assertNotIn(secret, identity.app_key)

    def test_url_keeps_host_not_path(self) -> None:
        """地址栏只留域名，路径和参数不能出现在记录里。"""
        secret = "token=季度工资"
        identity = classify_foreground(
            "msedge.exe",
            "GitHub 教程 - Microsoft Edge",
            f"https://www.bilibili.com/video/BV1xx?{secret}",
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "site:bilibili")
        self.assertEqual(identity.display_name, "哔哩哔哩")
        self.assertEqual(identity.default_category, CAT_SLACK)
        self.assertNotIn(secret, identity.app_key)
        self.assertNotIn(secret, identity.display_name)
        self.assertNotIn("BV1xx", identity.app_key)

    def test_unknown_host_can_be_marked_later(self) -> None:
        """没见过的域名单独成条，默认未分类。"""
        identity = classify_foreground(
            "chrome.exe",
            "",
            "https://docs.example.com/handbook",
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "site:docs.example.com")
        self.assertEqual(identity.display_name, "docs.example.com")
        self.assertEqual(identity.default_category, CAT_UNKNOWN)

    def test_internal_page_uses_tab_title(self) -> None:
        """开发者工具和设置页没有网站，退回用标签标题。"""
        self.assertEqual(
            host_from_address("chrome-devtools://devtools/bundled/inspector.html"),
            "",
        )
        self.assertEqual(host_from_address("edge://settings"), "")
        self.assertEqual(host_from_address("devtools"), "")
        identity = classify_foreground(
            "chrome.exe",
            "哔哩哔哩 - Google Chrome",
            "chrome-devtools://devtools/bundled/inspector.html",
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "site:bilibili")
        self.assertEqual(identity.default_category, CAT_SLACK)

    def test_work_host(self) -> None:
        """代码托管站点按域名算工作。"""
        self.assertEqual(host_from_address("https://github.com/org/repo"), "github.com")
        identity = classify_foreground(
            "chrome.exe", "", "https://github.com/org/private-repo"
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "site:github")
        self.assertEqual(identity.default_category, CAT_WORK)
        self.assertNotIn("private-repo", identity.display_name)

    def test_unknown_page_stays_on_browser(self) -> None:
        """没认出的网页记在浏览器上，标题不保留。"""
        secret = "工资单-三月"
        identity = classify_foreground(
            "chrome.exe", f"{secret} - Google Chrome"
        )
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "exe:chrome.exe")
        self.assertEqual(identity.display_name, "Google Chrome")
        self.assertEqual(identity.default_category, CAT_UNKNOWN)
        self.assertNotIn(secret, identity.display_name)

    def test_cursor_defaults_to_work(self) -> None:
        """编辑器按进程名算工作，不看标题。"""
        identity = classify_foreground("Cursor.exe", "机密文档 - Cursor")
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, "exe:cursor.exe")
        self.assertEqual(identity.display_name, "Cursor")
        self.assertEqual(identity.default_category, CAT_WORK)
        self.assertNotIn("机密", identity.display_name)

    def test_desktop_is_skipped(self) -> None:
        """点在桌面上不计。"""
        self.assertIsNone(classify_foreground("explorer.exe", "Program Manager"))
        self.assertIsNone(classify_foreground("explorer.exe", ""))

    def test_folder_is_explorer(self) -> None:
        """文件夹窗口不把目录名存下来。"""
        identity = classify_foreground("explorer.exe", "工资")
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.display_name, "文件资源管理器")
        self.assertNotIn("工资", identity.display_name)

    def test_lock_and_idle_are_rest(self) -> None:
        """锁屏、发呆满阈值都是休息；摸鱼软件也不能豁免。"""
        self.assertTrue(is_rest_moment(True, 0))
        self.assertFalse(is_rest_moment(False, IDLE_REST_SECONDS - 1))
        self.assertTrue(is_rest_moment(False, IDLE_REST_SECONDS))
        identity = classify_foreground("LockApp.exe", "")
        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.app_key, REST_APP_KEY)
        self.assertEqual(identity.default_category, CAT_REST)

    def test_long_gap_is_dropped(self) -> None:
        """两分钟内的间隔保留，过夜断档不补。"""
        self.assertEqual(clip_delta(2), 2)
        self.assertEqual(clip_delta(0), 0)
        self.assertEqual(clip_delta(3 * 3600), 3 * 3600)
        self.assertEqual(clip_delta(5 * 3600), 0)


class ActivityApplyTest(unittest.TestCase):
    """采样如何进内存。"""

    def _end(self) -> datetime:
        """测试用的当天下午。"""
        return datetime(2026, 9, 29, 16, 0, 0)

    def test_rest_sample_ignores_foreground(self) -> None:
        """锁屏记休息；人还在用的短间隔记到软件上；过夜不补。"""
        pending: dict[tuple[str, str], float] = {}
        names: dict[str, str] = {}
        apply_sample(
            pending,
            names,
            ended_at=self._end(),
            delta=90 * 60,
            paused=False,
            sample=ActivitySample(rest=True, exe="chrome.exe", title="哔哩哔哩"),
        )
        self.assertEqual(pending[("2026-09-29", REST_APP_KEY)], 90 * 60)
        self.assertNotIn("哔哩哔哩", names[REST_APP_KEY])
        pending.clear()
        apply_sample(
            pending,
            names,
            ended_at=self._end(),
            delta=30,
            paused=False,
            sample=ActivitySample(rest=False, exe="Cursor.exe", title="机密"),
        )
        self.assertEqual(pending[("2026-09-29", "exe:cursor.exe")], 30)
        self.assertEqual(names["exe:cursor.exe"], "Cursor")
        pending.clear()
        apply_sample(
            pending,
            names,
            ended_at=self._end(),
            delta=8 * 3600,
            paused=False,
            sample=ActivitySample(rest=True),
        )
        self.assertEqual(pending, {})

    def test_shell_and_stall_become_rest(self) -> None:
        """桌面不丢秒；采样停太久也不把整段算成当前软件。"""
        pending: dict[tuple[str, str], float] = {}
        apply_sample(
            pending,
            {},
            ended_at=self._end(),
            delta=2,
            paused=False,
            sample=ActivitySample(rest=False, exe="explorer.exe", title="Program Manager"),
        )
        self.assertEqual(pending[("2026-09-29", REST_APP_KEY)], 2)
        pending.clear()
        apply_sample(
            pending,
            {},
            ended_at=self._end(),
            delta=200,
            paused=False,
            sample=ActivitySample(rest=False, exe="Cursor.exe", title=""),
        )
        self.assertEqual(list(pending.keys()), [("2026-09-29", REST_APP_KEY)])
        self.assertEqual(pending[("2026-09-29", REST_APP_KEY)], 200)

    def test_gap_splits_at_midnight(self) -> None:
        """跨过零点的休息拆到两天。"""
        pending: dict[tuple[str, str], float] = {}
        apply_sample(
            pending,
            {},
            ended_at=datetime(2026, 9, 30, 0, 10, 0),
            delta=20 * 60,
            paused=False,
            sample=ActivitySample(rest=True),
        )
        self.assertEqual(pending[("2026-09-30", REST_APP_KEY)], 10 * 60)
        self.assertEqual(pending[("2026-09-29", REST_APP_KEY)], 10 * 60)

    def test_paused_records_nothing(self) -> None:
        """暂停期间不记休息也不记软件。"""
        pending: dict[tuple[str, str], float] = {}
        apply_sample(
            pending,
            {},
            ended_at=self._end(),
            delta=2,
            paused=True,
            sample=ActivitySample(rest=True),
        )
        self.assertEqual(pending, {})


class ActivityStoreTest(unittest.TestCase):
    """落到临时库，不碰用户正在用的 helper.db。"""

    def setUp(self) -> None:
        import attendance_helper.db as db

        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        self._old_ready = db._INITIALIZED
        db.DB_PATH = Path(self._tmpdir.name) / "helper.db"
        db._INITIALIZED = False

    def tearDown(self) -> None:
        import attendance_helper.db as db

        db.DB_PATH = self._old_path
        db._INITIALIZED = self._old_ready
        self._tmpdir.cleanup()

    def test_roundtrip_and_rule(self) -> None:
        """累计、手动归类、清空都落在指定日期上。"""
        from attendance_helper.activity_store import (
            add_usage_batch,
            clear_rule,
            delete_day,
            list_usage,
            load_rules,
            set_rule,
        )
        from attendance_helper.activity_tracker import ActivityTracker

        day = date(2026, 9, 29)
        add_usage_batch([(day.isoformat(), "exe:cursor.exe", "Cursor", 90)])
        tracker = ActivityTracker()
        tracker._pending[(day.isoformat(), "exe:cursor.exe")] = 30.4
        tracker._names["exe:cursor.exe"] = "Cursor"
        rows = tracker.rows_for(day)
        self.assertEqual(rows[0].app_key, "exe:cursor.exe")
        self.assertEqual(rows[0].seconds, 120)
        self.assertEqual(rows[0].category, CAT_WORK)
        self.assertFalse(rows[0].manual)

        set_rule("exe:cursor.exe", CAT_SLACK)
        self.assertEqual(tracker.rows_for(day)[0].category, CAT_SLACK)
        self.assertEqual(load_rules()["exe:cursor.exe"], CAT_SLACK)
        clear_rule("exe:cursor.exe")
        self.assertNotIn("exe:cursor.exe", load_rules())

        stored = list_usage(day.isoformat())
        self.assertEqual(stored[0][2], 90)
        delete_day(day.isoformat())
        self.assertEqual(list_usage(day.isoformat()), [])
        set_rule(REST_APP_KEY, CAT_WORK)
        self.assertEqual(load_rules(), {})

    def test_tool_reads_shared_tracker(self) -> None:
        """AI 工具读到同一份累计，且结果里没有窗口标题。"""
        from attendance_helper.activity_tracker import get_activity_tracker
        from attendance_helper.ai_agent import _required_tool_for_request
        from attendance_helper.ai_tools import _tool_get_app_usage

        tracker = get_activity_tracker()
        day = date.today().isoformat()
        tracker._pending[(day, "exe:cursor.exe")] = 125
        tracker._names["exe:cursor.exe"] = "Cursor"
        tracker._pending[(day, "rest:idle")] = 70
        tracker._names["rest:idle"] = "休息"
        result = _tool_get_app_usage({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["days"][0]["date"], day)
        self.assertGreaterEqual(result["days"][0]["work_seconds"], 125)
        self.assertGreaterEqual(result["days"][0]["rest_seconds"], 70)
        names = [item["name"] for item in result["days"][0]["apps"]]
        self.assertEqual(names[:2], ["Cursor", "休息"])
        self.assertNotIn("机密标题", str(result))
        self.assertEqual(_required_tool_for_request("今天摸鱼了多久"), "get_app_usage")
        self.assertEqual(_required_tool_for_request("今天打卡了吗"), "get_attendance")


if __name__ == "__main__":
    unittest.main()
