# Copyright (c) iGroup China.
# All rights reserved.
"""
提醒窗口与接口轮询间隔。

@author Kai
@date 2026/09/02 16:37
@description 只为上班卡打接口；拉到后倒计时本地走，次日 7:00 再开始拉
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from .config import S

if TYPE_CHECKING:
    from .attendance import AttendanceSummary


def within_remind_window(now: datetime) -> bool:
    """
    是否在提醒窗口内（到配置的提醒截止时刻前）。

    @param now 当前时间
    @return 是否可提醒
    @author Kai
    @date 2026/07/23 16:00
    """
    stop = now.replace(
        hour=S.remind_stop_hour,
        minute=S.remind_stop_minute,
        second=0,
        microsecond=0,
    )
    return now < stop


def clock_in_poll_start(now: datetime) -> datetime:
    """
    当天开始找上班卡的时刻（默认 07:00）。

    @param now 当前时间（取日期）
    @return 当天拉卡起点
    @author Kai
    @date 2026/09/02 16:37
    """
    hour = int(getattr(S, "clock_in_poll_hour", 7) or 7)
    minute = int(getattr(S, "clock_in_poll_minute", 0) or 0)
    hour = min(23, max(0, hour))
    minute = min(59, max(0, minute))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def seconds_until_next_clock_in_poll(now: datetime) -> int:
    """
    距离下一次「开始找上班卡」的秒数。

    当天起点未到则等到今天；已过则等到次日同一时刻。

    @param now 当前时间
    @return 间隔秒数，至少 60 秒
    @author Kai
    @date 2026/09/02 16:37
    """
    start = clock_in_poll_start(now)
    target = start if now < start else start + timedelta(days=1)
    return max(60, int((target - now).total_seconds()))


def _low_interval_seconds() -> int:
    """
    尚未拉到上班卡时的轮询间隔（秒）。

    @return 不少于 60 秒
    @author Kai
    @date 2026/09/02 16:37
    """
    return max(60, int(S.low_freq_interval_seconds))


def next_interval_seconds(
    now: datetime,
    summary: Optional["AttendanceSummary"] = None,
) -> int:
    """
    返回下次「拉取打卡接口」的间隔秒数。

    只关心上班卡：拉到之后倒计时按本地时钟走，不再为下班卡打接口；
    次日配置的上班起点（默认 07:00）再开始拉。
    手动点「刷新」仍会立刻打一次接口。

    @param now 当前时间
    @param summary 最近一次打卡摘要
    @return 秒数
    @author Kai
    @date 2026/09/02 16:37
    """
    # 已有今日上班卡：睡到次日 7:00，不再为下班卡打接口
    if (
        summary is not None
        and summary.ok
        and summary.has_clock_in
        and (not summary.date or summary.date == now.date().isoformat())
    ):
        tomorrow = clock_in_poll_start(now) + timedelta(days=1)
        return max(60, int((tomorrow - now).total_seconds()))

    start = clock_in_poll_start(now)
    # 还没到上班起点：等到 7:00 再拉
    if now < start:
        return max(60, int((start - now).total_seconds()))

    # 过了提醒截止仍未打上班卡：等到次日起点
    if not within_remind_window(now):
        return seconds_until_next_clock_in_poll(now)

    return _low_interval_seconds()
