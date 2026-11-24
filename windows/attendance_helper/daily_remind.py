# Copyright (c) iGroup China.
# All rights reserved.
"""
日常定点提醒（如午间点外卖）。

@author Kai
@date 2026/08/06 10:58
@description 按配置时刻触发，工作日每天一次
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .cache_store import cache_mark_once
from .config import S
from .holiday import is_workday
from .paths import LOG


def evaluate_takeout_reminder(on_notify: Callable[[str, str], None]) -> None:
    """
    到达配置时刻后提醒点外卖（仅工作日，每天一次）。

    @param on_notify 通知回调 (标题, 正文)
    @author Kai
    @date 2026/08/06 10:58
    """
    if not bool(getattr(S, "takeout_remind_enable", True)):
        return
    now = datetime.now()
    try:
        if not is_workday(now.date()):
            return
    except Exception:
        LOG.exception("外卖提醒：工作日判断失败")
        return

    hour = int(getattr(S, "takeout_remind_hour", 10) or 10)
    minute = int(getattr(S, "takeout_remind_minute", 40) or 40)
    target = hour * 60 + minute
    if now.hour * 60 + now.minute < target:
        return

    day_key = now.date().isoformat()
    if not cache_mark_once(f"takeout-remind-{day_key}"):
        return

    text = (getattr(S, "takeout_remind_text", "") or "").strip()
    if not text:
        text = "该点外卖啦，别饿着干活～"
    try:
        on_notify("外卖提醒", text)
        LOG.info("已触发外卖提醒 %s %02d:%02d", day_key, hour, minute)
    except Exception:
        LOG.exception("外卖提醒通知失败")
