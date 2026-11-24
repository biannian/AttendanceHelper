# Copyright (c) iGroup China.
# All rights reserved.
"""
本地 JSON 缓存（提醒去重、请假时长、节假日）。

@author Kai
@date 2026/07/23 15:25
@description 读写 cache.json / status.json
"""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Any

from .config import MAX_LEAVE_HOURS, S
from .paths import CACHE_PATH, LOG, STATUS_PATH

CACHE_LOCK = threading.Lock()
CACHE: dict[str, Any] = {}


def load_json_file(path: Path, default: Any) -> Any:
    """
    读取 JSON 文件，失败时返回默认值。

    @param path 文件路径
    @param default 失败默认值
    @return 解析结果或默认值
    @author Kai
    @date 2026/07/23 15:25
    """
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def save_json_file(path: Path, data: Any) -> None:
    """
    原子写入 JSON 文件。

    @param path 目标路径
    @param data 可序列化数据
    @author Kai
    @date 2026/07/23 15:25
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_cache() -> None:
    """
    从磁盘加载 CACHE。

    @author Kai
    @date 2026/07/23 15:25
    """
    global CACHE
    with CACHE_LOCK:
        CACHE = load_json_file(CACHE_PATH, {})


def save_cache() -> None:
    """
    持久化 CACHE。

    @author Kai
    @date 2026/07/23 15:25
    """
    with CACHE_LOCK:
        save_json_file(CACHE_PATH, CACHE)


def leave_cache_key(day: date) -> str:
    """
    当日请假缓存键。

    @param day 日期
    @return 缓存键
    @author Kai
    @date 2026/07/23 15:25
    """
    return f"leaveHours-{day.isoformat()}"


def get_leave_hours(day: date | None = None) -> float:
    """
    读取当日请假小时数。

    @param day 日期，默认今天
    @return 请假小时（0 ~ MAX_LEAVE_HOURS）
    @author Kai
    @date 2026/07/23 15:25
    """
    day = day or date.today()
    with CACHE_LOCK:
        raw = CACHE.get(leave_cache_key(day), 0)
    try:
        return max(0.0, min(float(raw), MAX_LEAVE_HOURS))
    except (TypeError, ValueError):
        return 0.0


def set_leave_hours(hours: float, day: date | None = None) -> float:
    """
    写入当日请假小时，并清除当日提醒去重标记。

    @param hours 请假小时
    @param day 日期，默认今天
    @return 规范化后的请假小时
    @author Kai
    @date 2026/07/23 15:25
    """
    day = day or date.today()
    hours = max(0.0, min(float(hours), MAX_LEAVE_HOURS))
    day_key = day.isoformat()
    with CACHE_LOCK:
        CACHE[leave_cache_key(day)] = hours
        CACHE.pop(f"near{int(S.target_hours)}-{day_key}", None)
        CACHE.pop(f"targetReached-{day_key}", None)
    save_cache()
    LOG.info("已设置请假时长 %s -> %.2fh", day_key, hours)
    return hours


def cache_mark_once(key: str) -> bool:
    """
    当天某类提醒只触发一次；返回 True 表示本次应提醒。

    @param key 缓存键
    @return 是否首次标记
    @author Kai
    @date 2026/07/23 15:25
    """
    with CACHE_LOCK:
        if CACHE.get(key):
            return False
        CACHE[key] = True
    save_cache()
    return True


load_cache()
