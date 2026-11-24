# Copyright (c) iGroup China.
# All rights reserved.
"""
运行时共享状态：最新考勤摘要、开门标记等。

@author Kai
@date 2026/08/05 14:15
@description 供 AI 工具与收尾检查只读访问
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any, Optional

_LOCK = threading.Lock()
_LATEST_SUMMARY: Any = None
_DOOR_OPENED_DATE: str = ""
_CELEBRATE_UNTIL: float = 0.0


def set_latest_summary(summary: Any) -> None:
    """
    更新最新考勤摘要。

    @param summary AttendanceSummary
    @author Kai
    @date 2026/08/05 14:15
    """
    global _LATEST_SUMMARY
    with _LOCK:
        _LATEST_SUMMARY = summary


def get_latest_summary() -> Any:
    """
    读取最新考勤摘要。

    @return AttendanceSummary 或 None
    @author Kai
    @date 2026/08/05 14:15
    """
    with _LOCK:
        return _LATEST_SUMMARY


def mark_door_opened_today() -> None:
    """
    标记今日已开门成功。

    @author Kai
    @date 2026/08/05 14:15
    """
    global _DOOR_OPENED_DATE
    with _LOCK:
        _DOOR_OPENED_DATE = date.today().isoformat()


def door_opened_today() -> bool:
    """
    今日是否已成功开门。

    @return True/False
    @author Kai
    @date 2026/08/05 14:15
    """
    with _LOCK:
        return _DOOR_OPENED_DATE == date.today().isoformat()


def set_celebrate_until(ts: float) -> None:
    """
    设置庆祝动画结束时间戳。

    @param ts Unix 时间戳
    @author Kai
    @date 2026/08/05 14:15
    """
    global _CELEBRATE_UNTIL
    with _LOCK:
        _CELEBRATE_UNTIL = float(ts)


def is_celebrating(now_ts: Optional[float] = None) -> bool:
    """
    当前是否处于庆祝态。

    @param now_ts 可选当前时间戳
    @return True/False
    @author Kai
    @date 2026/08/05 14:15
    """
    import time

    t = time.time() if now_ts is None else float(now_ts)
    with _LOCK:
        return t < _CELEBRATE_UNTIL
