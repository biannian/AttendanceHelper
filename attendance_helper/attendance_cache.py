# Copyright (c) iGroup China.
# All rights reserved.
"""
历史打卡按日缓存。

@author Kai
@date 2026/09/01 10:20
@description 仅缓存「今天之前」的日期；近 7 天有 TTL，今日始终走接口
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any, Iterable, Optional

from .cache_store import load_json_file, save_json_file
from .paths import ATT_CACHE_PATH, LOG

# 近 7 天可能被人事补卡，过期后下次查询重新拉接口
RECENT_CACHE_DAYS = 7
# 近 7 天缓存有效期（秒）
RECENT_CACHE_TTL_SECONDS = 6 * 3600

_LOCK = threading.Lock()
_DAYS: dict[str, Any] = {}
_DIRTY = False
_LOADED = False


def _is_recent_day(day: date, today: date) -> bool:
    """
    是否属于「近 7 天」历史日（不含今天）。

    @param day 业务日
    @param today 今天
    @return 是否套用 TTL
    @author Kai
    @date 2026/09/01 10:20
    """
    delta = (today - day).days
    return 1 <= delta <= RECENT_CACHE_DAYS


def _ensure_loaded() -> None:
    """首次使用时从磁盘载入。"""
    global _DAYS, _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        data = load_json_file(ATT_CACHE_PATH, {"days": {}})
        days = data.get("days") if isinstance(data, dict) else None
        _DAYS = days if isinstance(days, dict) else {}
        _LOADED = True


def get_settled_payload(
    day: date,
    *,
    today: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """
    读取已结算历史日的缓存摘要字典。

    近 7 天超过 TTL 视为未命中，便于人事补卡后自动刷新。

    @param day 业务日期
    @param today 今天（可测）
    @return summary 字典；未命中返回 None
    @author Kai
    @date 2026/09/01 10:20
    """
    _ensure_loaded()
    key = day.isoformat()
    today = today or date.today()
    with _LOCK:
        entry = _DAYS.get(key)
    if not isinstance(entry, dict):
        return None
    if not entry.get("settled", True):
        return None
    summary = entry.get("summary")
    if not isinstance(summary, dict):
        return None
    if bool(summary.get("token_expired")):
        return None
    if _is_recent_day(day, today):
        saved_at = float(entry.get("savedAt") or 0)
        if saved_at <= 0 or (time.time() - saved_at) > RECENT_CACHE_TTL_SECONDS:
            return None
    return summary


def put_settled_payload(day: date, summary: dict[str, Any]) -> None:
    """
    写入已结算历史日（仅内存，需再 flush）。

    @param day 业务日期
    @param summary 可序列化摘要
    @author Kai
    @date 2026/09/01 10:00
    """
    global _DIRTY
    _ensure_loaded()
    key = day.isoformat()
    with _LOCK:
        _DAYS[key] = {
            "settled": True,
            "savedAt": time.time(),
            "summary": summary,
        }
        _DIRTY = True


def drop_days(days: Iterable[date]) -> None:
    """
    删除指定日期的缓存（刷新历史时先清再拉）。

    @param days 要丢掉的日期
    @author Kai
    @date 2026/09/01 10:20
    """
    global _DIRTY
    _ensure_loaded()
    with _LOCK:
        for day in days:
            key = day.isoformat()
            if key in _DAYS:
                del _DAYS[key]
                _DIRTY = True


def flush_attendance_cache() -> None:
    """
    把脏缓存落到 attendance_cache.json。

    @author Kai
    @date 2026/09/01 10:00
    """
    global _DIRTY
    _ensure_loaded()
    with _LOCK:
        if not _DIRTY:
            return
        payload = {"days": dict(_DAYS)}
        try:
            save_json_file(ATT_CACHE_PATH, payload)
            _DIRTY = False
        except Exception as exc:  # noqa: BLE001
            LOG.warning("写入考勤缓存失败: %s", exc)
