# Copyright (c) iGroup.
# All rights reserved.
"""
门禁刷脸与下班倒计时回归测试。

@author Kai
@date 2026/11/25 10:47
@description 验证短暂外出、目标时刻及历史打卡的处理
"""

from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

from attendance_helper.attendance import (
    apply_leave_hours_to_summary,
    build_menu_status_text,
    live_tick_summary,
    normalize_attendance,
)
from attendance_helper.config import S


class AttendanceCountdownTest(TestCase):
    """
验证门禁记录在实时与历史考勤中的表现。

    @author Kai
    @date 2026/11/25 10:47
    @description 使用模拟班次响应覆盖接口解析和本地倒计时
    """

    def test_midday_swipe_keeps_countdown_visible_and_running(self) -> None:
        """
        午间刷脸之后仍从首张上班卡继续倒计时。

        @author Kai
        @date 2026/11/25 10:47
        """
        now = datetime(2026, 11, 25, 12)
        raw = {
            "dailyDetail": {
                "shiftDetails": [{
                    "inClocked": 1,
                    "offClocked": 1,
                    "clockInTime": "09:00",
                    "clockOffTime": "11:55",
                    "clockOffStatusDesc": "早退",
                }],
            },
        }
        with (
            patch("attendance_helper.attendance.get_leave_hours", return_value=0),
            patch.object(S, "target_hours", 9),
            patch.object(S, "display_mode", "always"),
        ):
            summary = normalize_attendance(raw, now, day_hint=now.date())
            ticked = live_tick_summary(summary, now + timedelta(minutes=1))
            self.assertFalse(summary.has_clock_out)
            self.assertEqual(summary.target_time, now.replace(hour=18))
            self.assertEqual(summary.remaining_seconds, 6 * 3600)
            self.assertFalse(ticked.has_clock_out)
            self.assertEqual(ticked.remaining_seconds, 6 * 3600 - 60)
            self.assertIn("进行中", ticked.validity_tip)
            self.assertIn("还差 359 分钟", build_menu_status_text(ticked))

    def test_target_swipe_and_leave_adjustment(self) -> None:
        """
        达标后的刷脸计为下班卡，请假变更按新目标重新判断。

        @author Kai
        @date 2026/11/25 10:47
        """
        now = datetime(2026, 11, 25, 18, 5)
        raw = {"clockInTime": "09:00", "clockOffTime": "18:00"}
        with (
            patch("attendance_helper.attendance.get_leave_hours", return_value=0),
            patch.object(S, "target_hours", 9),
        ):
            completed = normalize_attendance(raw, now, day_hint=now.date())
            self.assertTrue(completed.has_clock_out)
            self.assertTrue(completed.target_reached)

            raw["clockOffTime"] = "17:00"
            summary = normalize_attendance(raw, now, day_hint=now.date())
            self.assertFalse(summary.has_clock_out)
            adjusted = apply_leave_hours_to_summary(summary, 1, now)
            self.assertEqual(adjusted.latest_out_time, now.replace(hour=17, minute=0))
            self.assertFalse(apply_leave_hours_to_summary(adjusted, 0, now).has_clock_out)

    def test_past_day_uses_recorded_checkout(self) -> None:
        """
        历史日仍按接口提供的打卡时段统计工时。

        @author Kai
        @date 2026/11/25 10:47
        """
        now = datetime(2026, 11, 25, 12)
        day = now.date() - timedelta(days=1)
        raw = {"clockInTime": "09:00", "clockOffTime": "16:00"}
        with (
            patch("attendance_helper.attendance.get_leave_hours", return_value=0),
            patch.object(S, "target_hours", 9),
        ):
            summary = normalize_attendance(raw, now, day_hint=day)
        self.assertTrue(summary.has_clock_out)
        self.assertEqual(summary.worked_seconds, 7 * 3600)
        self.assertFalse(summary.is_valid_attendance)
