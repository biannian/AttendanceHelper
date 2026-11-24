# Copyright (c) iGroup.
# All rights reserved.
"""
连续海龟汤卡片的界面回归。

@author Kai
@date 2026/10/15 15:53
@description 验证原地换题、重新打开自动刷新和设置迁移，使用临时数据库
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# 离屏检查不会打开用户桌面窗口。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget, QComboBox

from attendance_helper import activity_tracker, config, db, playground as game
from attendance_helper.activity_store import add_usage_batch
from attendance_helper.attendance import AttendanceSummary
from attendance_helper.config import S
from attendance_helper.display_strategy import MODE_NEAR, FAR_CLOCK_IN
from attendance_helper.items_store import create_item
from attendance_helper.ui.activity_dialog import ActivityDialog
from attendance_helper.ui.companion_card import CompanionCard
from attendance_helper.ui.detail_popup import TrayDetailPopup
from attendance_helper.ui.settings_dialog import SettingsDialog
from attendance_helper.relaxation import merit_snapshot


class PuzzleCardUiTest(unittest.TestCase):
    """
    真实 Qt 控件上的连续推理检查。

    @author Kai
    @date 2026/10/15 15:53
    @description 只读写临时存档，不访问网络
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        加载离屏应用与中文字体。

        @author Kai
        @date 2026/10/15 15:53
        """
        cls.app = QApplication.instance() or QApplication([])
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            font = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        cls.app.setFont(QFont("Microsoft YaHei", 9))

    def setUp(self) -> None:
        """
        隔离数据库、累计器及显示配置。

        @author Kai
        @date 2026/10/15 15:53
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for target, key, value in (
            (db, "DB_PATH", Path(directory.name) / "ui.db"), (db, "_INITIALIZED", False),
            (activity_tracker, "_SHARED_TRACKER", activity_tracker.ActivityTracker()),
            (S, "fun_enable", True), (S, "fun_card_mode", "puzzle"), (S, "fun_usage_link", True),
            (S, "display_mode", MODE_NEAR), (S, "far_display", FAR_CLOCK_IN),
            (S, "fun_salary_enable", False), (S, "fun_hourly_rate", 0),
            (S, "fun_salary_slack", True), (S, "fun_salary_rest", True), (S, "fun_salary_unknown", False),
            (S, "fun_woodfish_enable", True), (S, "fun_woodfish_sound", False), (S, "fun_pet_enable", True),
            (S, "attendance_token", ""), (S, "ai_api_token", ""),
        ):
            replacement = patch.object(target, key, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def _capture(self, widget: object, name: str) -> None:
        """
        按需保存示例数据预览。

        @param widget Qt 卡片或窗口
        @param name 预览名称
        @author Kai
        @date 2026/10/15 15:53
        """
        directory = os.getenv("PLAYGROUND_PREVIEW_DIR")
        if directory:
            self.app.processEvents()
            folder = Path(directory)
            folder.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(folder / (name + ".png"))))

    def test_reveal_then_next_without_new_window(self) -> None:
        """
        一次揭晓后立即可换题，计数和线索不会串到下一题。

        @author Kai
        @date 2026/10/15 15:53
        """
        card = CompanionCard()
        self.addCleanup(card.close)
        card.show()
        first = card._state["puzzle"]["title"]
        card.action.click()
        self.assertEqual(card.action.text(), "揭晓谜底")
        card.action.click()
        self.assertEqual(card.action.text(), "再来一题")
        self.assertTrue(card.action.isEnabled())
        self.assertIn("已揭晓 1 题", card.note.text())
        self._capture(card, "puzzle-revealed")
        card.action.click()
        self.assertNotEqual(card._state["puzzle"]["title"], first)
        self.assertEqual(card.action.text(), "给点线索")
        self.assertFalse(card._hint_shown)

    def test_reopen_advances_finished_but_keeps_unfinished(self) -> None:
        """
        未完成题重新打开继续，已揭晓题重新打开自动换新。

        @author Kai
        @date 2026/10/15 15:53
        """
        card = CompanionCard()
        self.addCleanup(card.close)
        card.show()
        first = card._round
        card.hide()
        card.show()
        self.assertEqual(card._round, first)
        card.action.click()
        card.action.click()
        card.hide()
        self.assertFalse(card._timer.isActive())
        card.show()
        self.assertEqual(card._round, first + 1)
        self.assertEqual(card.action.text(), "给点线索")

    def test_popup_is_compact_and_has_only_one_action(self) -> None:
        """
        考勤、两条待办和海龟汤保持在一张小卡片里。

        @author Kai
        @date 2026/10/15 15:53
        """
        now = datetime.now()
        popup = TrayDetailPopup()
        self.addCleanup(popup.close)
        summary = AttendanceSummary(ok=True, in_time=now - timedelta(hours=3),
                                    worked_seconds=10800, remaining_seconds=21600,
                                    required_seconds=32400, target_time=now + timedelta(hours=6))
        popup.update_summary(summary)
        popup.show()
        self.app.processEvents()
        self.assertLessEqual(popup.height(), 250)
        self.assertEqual(len(popup._play_panel.findChildren(QPushButton)), 1)
        self.assertTrue(popup._woodfish.isVisible())
        self.assertEqual(popup.findChildren(QTabWidget), [])
        self.assertEqual(popup.findChildren(QComboBox), [])
        self._capture(popup, "puzzle-card")
        for title in ("点午饭", "带上充电器", "取快递"):
            create_item(title)
        popup.update_summary(summary)
        self.assertEqual(len(popup._todo_titles), 2)
        with patch.object(S, "fun_card_mode", "off"):
            popup.update_summary(summary)
            self.assertFalse(popup._play_panel.isVisible())

    def test_settings_retire_adventure_and_save_puzzle(self) -> None:
        """
        设置不再提供冒险入口，旧冒险配置自动迁移到海龟汤。

        @author Kai
        @date 2026/10/15 15:53
        """
        settings = SettingsDialog()
        self.addCleanup(settings.close)
        self.assertEqual(settings.cb_fun_card.count(), 2)
        self.assertFalse(hasattr(settings, "cb_fun_trip"))
        self.assertFalse(hasattr(settings, "ck_fun_story"))
        settings.ed_token.setText("test-token")
        settings.cb_fun_card.setCurrentIndex(settings.cb_fun_card.findData("puzzle"))
        namespace = "attendance_helper.ui.settings_dialog."
        with patch(namespace + "save_env_map"), patch(namespace + "save_config_dict") as save:
            with patch(namespace + "reload_settings"), patch(namespace + "QMessageBox.information"):
                settings._save()
        self.assertEqual(save.call_args.args[0]["fun"]["card_mode"], "puzzle")
        with patch.object(config, "S", config.AppSettings()) as loaded:
            with patch.object(config, "load_config_dict", return_value={"fun": {"card_mode": "adventure"}}):
                config.reload_settings()
            self.assertEqual(loaded.fun_card_mode, "puzzle")

    def test_growth_and_usage_details_still_work(self) -> None:
        """
        移除冒险入口不影响已有成长和使用统计。

        @author Kai
        @date 2026/10/15 15:53
        """
        today = datetime.now().date().isoformat()
        add_usage_batch([(today, "exe:code.exe", "编辑器", 10800)])
        card = CompanionCard()
        self.addCleanup(card.close)
        self.assertEqual(card._state["growth"]["xp"], 6)
        details = ActivityDialog(activity_tracker.get_activity_tracker())
        self.addCleanup(details.close)
        details.show()
        self.app.processEvents()
        self.assertLessEqual(details.width(), 600)

    def test_woodfish_counts_animates_and_keeps_real_countdown(self) -> None:
        """
        真实鼠标点击只加功德，默认静音，考勤摘要不变。

        @author Kai
        @date 2026/10/15 16:16
        """
        now = datetime.now()
        summary = AttendanceSummary(ok=True, in_time=now - timedelta(hours=8),
                                    worked_seconds=28800, remaining_seconds=3600,
                                    required_seconds=32400, target_time=now + timedelta(hours=1))
        popup = TrayDetailPopup()
        self.addCleanup(popup.close)
        popup.update_summary(summary)
        popup.show()
        self.app.processEvents()
        with patch("attendance_helper.ui.woodfish.play_woodfish_sound") as sound:
            for _ in range(3):
                QTest.mouseClick(popup._woodfish, Qt.MouseButton.LeftButton)
            sound.assert_not_called()
            with patch.object(S, "fun_woodfish_sound", True):
                popup._woodfish.click()
            sound.assert_called_once()
        self.assertEqual(merit_snapshot()["today"], 4)
        self.assertTrue(popup._merit_float.isVisible())
        self.assertEqual(popup._summary.remaining_seconds, 3600)
        self.assertEqual(popup._summary.target_time, summary.target_time)
        self.assertIn("今日 4 次", popup._woodfish.toolTip())
        with patch.object(S, "fun_woodfish_enable", False):
            popup._woodfish.click()
        self.assertEqual(merit_snapshot()["today"], 4)
        self._capture(popup, "woodfish-click")
        popup.hide()
        self.assertFalse(popup._merit_float.isVisible())

    def test_money_uses_pending_selected_usage_and_stops_when_hidden(self) -> None:
        """
        金额包含内存秒数，工作和未选分类增加时保持原值。

        @author Kai
        @date 2026/10/15 16:16
        """
        today = datetime.now().date().isoformat()
        tracker = activity_tracker.get_activity_tracker()
        tracker._pending[(today, "rest:idle")] = 900
        tracker._pending[(today, "site:bilibili")] = 1800
        tracker._pending[(today, "exe:custom.exe")] = 7200
        with patch.object(S, "fun_salary_enable", True), patch.object(S, "fun_hourly_rate", 40):
            popup = TrayDetailPopup()
            self.addCleanup(popup.close)
            popup.update_summary(AttendanceSummary(ok=True, in_time=datetime.now() - timedelta(hours=8, minutes=50),
                                                   worked_seconds=31800, remaining_seconds=600,
                                                   required_seconds=32400, target_time=datetime.now() + timedelta(minutes=10)))
            popup.show()
            self.app.processEvents()
            self.assertTrue(popup._salary_label.isVisible())
            self.assertIn("¥ 30.00", popup._salary_label.text())
            tracker._pending[(today, "exe:code.exe")] = 900
            popup._refresh_salary()
            self.assertIn("¥ 30.00", popup._salary_label.text())
            tracker._pending[(today, "rest:idle")] = tracker._pending.get((today, "rest:idle"), 0) + 90
            popup._refresh_salary()
            self.assertIn("¥ 31.00", popup._salary_label.text())
            self.assertLess(popup._salary_label.geometry().bottom(), popup._play_panel.y())
            self.assertLessEqual(popup.height(), 300)
            self.assertTrue(popup._salary_timer.isActive())
            self._capture(popup, "money-card")
            with patch("attendance_helper.ui.detail_popup.date") as clock:
                clock.today.return_value = datetime.now().date() + timedelta(days=1)
                popup._refresh_salary()
                self.assertIn("¥ 0.00", popup._salary_label.text())
            popup.hide()
            self.assertFalse(popup._salary_timer.isActive())

    def test_salary_settings_validate_and_roundtrip(self) -> None:
        """
        启用金额必须填写时薪和选择分类，保存后按同一口径加载。

        @author Kai
        @date 2026/10/15 16:16
        """
        settings = SettingsDialog()
        self.addCleanup(settings.close)
        settings.ed_token.setText("test-token")
        settings.ck_fun.setChecked(True)
        settings.ck_salary.setChecked(True)
        namespace = "attendance_helper.ui.settings_dialog."
        with patch(namespace + "save_env_map"), patch(namespace + "save_config_dict") as save:
            with patch(namespace + "QMessageBox.warning") as warning:
                settings._save()
                warning.assert_called_once()
                save.assert_not_called()
            settings.sp_hourly_rate.setValue(40)
            for checkbox in (settings.ck_salary_slack, settings.ck_salary_rest, settings.ck_salary_unknown):
                checkbox.setChecked(False)
            with patch(namespace + "QMessageBox.warning") as warning:
                settings._save()
                warning.assert_called_once()
                save.assert_not_called()
            settings.ck_salary_slack.setChecked(True)
            settings.ck_salary_rest.setChecked(True)
            with patch(namespace + "reload_settings"), patch(namespace + "QMessageBox.information"):
                settings._save()
        values = save.call_args.args[0]["fun"]
        self.assertEqual(values["hourly_rate"], 40)
        self.assertTrue(values["salary_slack"])
        self.assertTrue(values["salary_rest"])
        self.assertFalse(values["salary_unknown"])
        with patch.object(config, "S", config.AppSettings()) as loaded:
            with patch.object(config, "load_config_dict", return_value={"fun": values}):
                config.reload_settings()
            self.assertTrue(loaded.fun_salary_enable)
            self.assertEqual(loaded.fun_hourly_rate, 40)
            self.assertTrue(loaded.fun_salary_slack)
            self.assertTrue(loaded.fun_salary_rest)
            self.assertFalse(loaded.fun_salary_unknown)
        settings.findChild(QTabWidget).setCurrentIndex(3)
        settings.show()
        self.app.processEvents()
        self._capture(settings, "relax-settings")


if __name__ == "__main__":
    # 独立执行轻卡片检查，不启动真实托盘。
    unittest.main()
