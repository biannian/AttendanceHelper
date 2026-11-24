# Copyright (c) iGroup China.
# All rights reserved.
"""
通用工具函数。

@author Kai
@date 2026/07/23 15:25
@description 脱敏、时间格式化、嵌套 JSON 取值
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional


def mask_token(token: str) -> str:
    """
    脱敏 Token，仅保留前后少量字符。

    @param token 原始 Token
    @return 脱敏后的字符串
    @author Kai
    @date 2026/07/23 15:25
    """
    if not token:
        return "(empty)"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def format_hm(dt: Optional[datetime]) -> str:
    """
    格式化为 HH:MM。

    @param dt 时间对象
    @return 时间字符串或 --
    @author Kai
    @date 2026/07/23 15:25
    """
    if not dt:
        return "--"
    return dt.strftime("%H:%M")


def format_duration(seconds: int) -> str:
    """
    将秒数格式化为 XhYm。

    @param seconds 秒数
    @return 短时长文案
    @author Kai
    @date 2026/07/23 15:25
    """
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h{m}m"


def format_countdown(seconds: int) -> str:
    """
    将剩余秒数格式化为倒计时时钟。

    满 1 小时用 H:MM:SS，否则用 MM:SS，便于详情卡按秒跳动。

    @param seconds 剩余秒数
    @return 倒计时字符串
    @author Kai
    @date 2026/09/21 16:39
    """
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_time_on_date(date_str: str, time_str: Optional[str]) -> Optional[datetime]:
    """
    将接口返回的时间（如 08:29）解析为当天 datetime。

    @param date_str 业务日期 yyyy-MM-dd
    @param time_str 时间字符串
    @return datetime 或 None
    @author Kai
    @date 2026/07/23 15:25
    """
    if not time_str:
        return None
    s = str(time_str).strip()
    if not s:
        return None

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s, fmt).time()
            d = date.fromisoformat(date_str)
            return datetime.combine(d, t)
        except ValueError:
            pass

    normalized = s.replace("/", "-").replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def deep_pick(obj: Any, keys: list[str], depth: int = 0) -> Any:
    """
    在嵌套结构中按候选字段名查找首个非空值。

    @param obj 任意 JSON 对象
    @param keys 候选字段名（小写匹配）
    @param depth 当前递归深度
    @return 找到的值或 None
    @author Kai
    @date 2026/07/23 15:25
    """
    if obj is None or depth > 6:
        return None

    key_set = {k.lower() for k in keys}

    if isinstance(obj, dict):
        for name, value in obj.items():
            if str(name).lower() in key_set and value not in (None, ""):
                return value
        for value in obj.values():
            found = deep_pick(value, keys, depth + 1)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = deep_pick(item, keys, depth + 1)
            if found not in (None, ""):
                return found

    return None
