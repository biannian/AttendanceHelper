# Copyright (c) iGroup.
# All rights reserved.
"""
带薪回血估算与电子木鱼的本地数据。

@author Kai
@date 2026/10/15 16:11
@description 只使用分类累计时长与手动时薪；功德独立记账，不修改考勤
"""

from __future__ import annotations

import io
import json
import math
import struct
import sys
import threading
import wave
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from typing import Mapping

from .activity_classify import CAT_REST, CAT_SLACK, CAT_UNKNOWN
from .db import db_conn
from .paths import LOG

# 功德使用独立命名空间；保留最近 90 天明细和完整累计总数。
MERIT_KEY = "woodfish_v1"
# 声音不叠加播放，避免快速点击创建大量音频线程。
_SOUND_LOCK = threading.Lock()


def estimate_relaxation_pay(
    totals: Mapping[str, int | float],
    hourly_rate: float,
    *,
    include_slack: bool = True,
    include_rest: bool = True,
    include_unknown: bool = False,
) -> Decimal:
    """
    按选中分类的实际秒数估算金额，四舍五入到分。

    @param totals 当日工作、摸鱼、休息、未分类的累计秒数
    @param hourly_rate 用户手动填写的估算时薪，单位元/小时
    @param include_slack 是否计入摸鱼时长
    @param include_rest 是否计入休息时长
    @param include_unknown 是否计入未分类时长
    @return 娱乐估算金额，不代表实际工资或到账金额
    @author Kai
    @date 2026/10/15 16:11
    """
    try:
        rate = Decimal(str(hourly_rate))
    except InvalidOperation:
        return Decimal("0.00")
    if not rate.is_finite() or rate <= 0:
        return Decimal("0.00")
    seconds = Decimal(0)
    for category, enabled in (
        (CAT_SLACK, include_slack), (CAT_REST, include_rest), (CAT_UNKNOWN, include_unknown),
    ):
        if not enabled:
            continue
        try:
            value = Decimal(str(totals.get(category, 0)))
        except InvalidOperation:
            continue
        if value.is_finite() and value > 0:
            seconds += value
    return (rate * seconds / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def merit_snapshot(day: date | None = None) -> dict[str, int]:
    """
    读取今日与累计功德，不因展示而写库。

    @param day 业务日期，默认当前本地日期
    @return today 为当日点击数，total 为累计点击数
    @author Kai
    @date 2026/10/15 16:11
    """
    selected_day = (day or date.today()).isoformat()
    with db_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (MERIT_KEY,)).fetchone()
    state = json.loads(row["value"]) if row else {"total": 0, "days": {}}
    return {"today": int(state["days"].get(selected_day, 0)), "total": int(state["total"])}


def knock_woodfish(day: date | None = None) -> dict[str, int]:
    """
    原子记录一次主动点击，与考勤和下班倒计时完全独立。

    @param day 点击发生的业务日期，默认当前本地日期
    @return 更新后的今日与累计功德
    @author Kai
    @date 2026/10/15 16:11
    """
    selected_day = (day or date.today()).isoformat()
    with db_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (MERIT_KEY,)).fetchone()
        state = json.loads(row["value"]) if row else {"total": 0, "days": {}}
        state["total"] += 1
        state["days"][selected_day] = int(state["days"].get(selected_day, 0)) + 1
        today = state["days"][selected_day]
        state["days"] = dict(sorted(state["days"].items())[-90:])
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (MERIT_KEY, json.dumps(state)),
        )
    return {"today": today, "total": state["total"]}


@lru_cache(maxsize=1)
def woodfish_sound() -> bytes:
    """
    合成短促的空心敲击声，不依赖音频文件或额外库。

    @return 90 毫秒单声道 PCM WAV 数据
    @author Kai
    @date 2026/10/15 16:11
    """
    sample_rate = 22050
    frames = bytearray()
    for index in range(int(sample_rate * 0.09)):
        moment = index / sample_rate
        envelope = math.exp(-moment * 65) * min(1.0, moment * 2000)
        tone = math.sin(2 * math.pi * 820 * moment) + 0.35 * math.sin(2 * math.pi * 1730 * moment)
        frames.extend(struct.pack("<h", int(12000 * envelope * tone / 1.35)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(sample_rate)
        sound.writeframes(frames)
    return buffer.getvalue()


def play_woodfish_sound() -> None:
    """
    在 Windows 后台播放一次敲击声，快速连点时不堆积播放任务。

    @author Kai
    @date 2026/10/15 16:11
    """
    if sys.platform != "win32" or not _SOUND_LOCK.acquire(blocking=False):
        return

    def play() -> None:
        """
        播放结束后释放音频锁，设备异常不影响点击计数。

        @author Kai
        @date 2026/10/15 16:11
        """
        try:
            import winsound

            winsound.PlaySound(woodfish_sound(), winsound.SND_MEMORY | winsound.SND_SYNC)
        except Exception as exc:
            LOG.debug("木鱼声音未播放：%s", exc)
        finally:
            _SOUND_LOCK.release()

    try:
        threading.Thread(target=play, daemon=True, name="woodfish-sound").start()
    except Exception:
        _SOUND_LOCK.release()
        raise
