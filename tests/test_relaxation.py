# Copyright (c) iGroup.
# All rights reserved.
"""
带薪回血与电子木鱼业务回归。

@author Kai
@date 2026/10/15 16:16
@description 验证分类口径、金额舍入、功德持久化与合成音频格式
"""

from __future__ import annotations

import io
import tempfile
import unittest
import wave
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from attendance_helper import db
from attendance_helper.config import normalize_hourly_rate
from attendance_helper.relaxation import (
    estimate_relaxation_pay, knock_woodfish, merit_snapshot, woodfish_sound,
)


class PayEstimateTest(unittest.TestCase):
    """
    娱乐估算使用明确分类和手动时薪。

    @author Kai
    @date 2026/10/15 16:16
    @description 不涉及真实薪资发放、工作日折算或外部数据
    """

    def test_defaults_include_slack_rest_not_unknown_or_work(self) -> None:
        """
        默认只把摸鱼和休息计入金额。

        @author Kai
        @date 2026/10/15 16:16
        """
        totals = {"work": 28800, "slack": 1800, "rest": 900, "unknown": 7200}
        self.assertEqual(estimate_relaxation_pay(totals, 40), Decimal("30.00"))
        self.assertEqual(estimate_relaxation_pay(totals, 40, include_unknown=True), Decimal("110.00"))
        self.assertEqual(
            estimate_relaxation_pay(totals, 40, include_slack=False, include_rest=False), Decimal("0.00"),
        )

    def test_only_selected_category_changes_amount(self) -> None:
        """
        工作或未选分类增加时金额不变，选中分类增加才增长。

        @author Kai
        @date 2026/10/15 16:16
        """
        totals = {"rest": 1800}
        before = estimate_relaxation_pay(totals, 60)
        totals.update(work=9000, unknown=7200)
        self.assertEqual(estimate_relaxation_pay(totals, 60), before)
        totals["slack"] = 60
        self.assertEqual(estimate_relaxation_pay(totals, 60), before + Decimal("1.00"))

    def test_rounding_invalid_rates_and_negative_durations(self) -> None:
        """
        金额按分四舍五入，非法时薪与负秒数不产生负值或异常。

        @author Kai
        @date 2026/10/15 16:16
        """
        self.assertEqual(estimate_relaxation_pay({"rest": 18}, 1), Decimal("0.01"))
        self.assertEqual(estimate_relaxation_pay({"rest": -1800}, 40), Decimal("0.00"))
        for rate in (0, -1, float("nan"), float("inf")):
            self.assertEqual(estimate_relaxation_pay({"slack": 1800}, rate), Decimal("0.00"))
        self.assertEqual(normalize_hourly_rate("bad"), 0)
        self.assertEqual(normalize_hourly_rate(float("nan")), 0)
        self.assertEqual(normalize_hourly_rate("35.25"), 35.25)


class MeritStoreTest(unittest.TestCase):
    """
    只在临时数据库验证敲击记录。

    @author Kai
    @date 2026/10/15 16:16
    @description 测试不会发出声音或修改用户考勤数据
    """

    def setUp(self) -> None:
        """
        隔离功德与游戏存档。

        @author Kai
        @date 2026/10/15 16:16
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for key, value in (("DB_PATH", Path(directory.name) / "merit.db"), ("_INITIALIZED", False)):
            replacement = patch.object(db, key, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_each_click_once_and_restart_preserves_total(self) -> None:
        """
        连点按次数准确记录，重新连接后仍可读取。

        @author Kai
        @date 2026/10/15 16:16
        """
        self.assertEqual(merit_snapshot(), {"today": 0, "total": 0})
        for index in range(8):
            self.assertEqual(knock_woodfish()["today"], index + 1)
        db._INITIALIZED = False
        self.assertEqual(merit_snapshot(), {"today": 8, "total": 8})

    def test_new_day_resets_daily_count_not_lifetime(self) -> None:
        """
        跨日只重置当日计数，累计功德持续保留。

        @author Kai
        @date 2026/10/15 16:16
        """
        knock_woodfish()
        tomorrow = date.today() + timedelta(days=1)
        self.assertEqual(merit_snapshot(tomorrow), {"today": 0, "total": 1})
        self.assertEqual(knock_woodfish(tomorrow), {"today": 1, "total": 2})

    def test_sound_is_short_valid_wav_without_files(self) -> None:
        """
        音频在内存中生成，时长短且 PCM 格式可播放。

        @author Kai
        @date 2026/10/15 16:16
        """
        with wave.open(io.BytesIO(woodfish_sound()), "rb") as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 0.09, places=3)


if __name__ == "__main__":
    # 独立执行时同样只用临时存档，不播放声音。
    unittest.main()
