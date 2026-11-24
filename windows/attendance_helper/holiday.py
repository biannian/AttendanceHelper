# Copyright (c) iGroup China.
# All rights reserved.
"""
中国节假日判断（timor.tech）。

@author Kai
@date 2026/07/23 17:35
@description type in [0,3] 视为工作日（含调休补班）；提供日历展示用日信息
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from .cache_store import CACHE, CACHE_LOCK, save_cache
from .config import S
from .paths import DEFAULT_USER_AGENT, LOG

# 先加载 paths 以持久化 CA 证书，再让 requests 缓存 bundle 路径
import requests


@dataclass
class DayHolidayInfo:
    """
    单日节假日展示信息。

    @author Kai
    @date 2026/07/23 17:35
    """

    # work | weekend | holiday | makeup
    kind: str
    # 日历短标签：元旦 / 休 / 补班；工作日为空
    label: str
    is_workday: bool


def _http_headers() -> dict[str, str]:
    """节假日接口请求头。"""
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://timor.tech/",
    }


def ensure_year_holiday_map(year: int) -> dict[str, Any]:
    """
    拉取并缓存某年节假日表（MM-DD → 条目）。

    @param year 年份
    @return 当年 holiday 字典
    @author Kai
    @date 2026/07/23 17:35
    """
    cache_key = f"holiday-year-{year}"
    with CACHE_LOCK:
        cached = CACHE.get(cache_key)
        if isinstance(cached, dict):
            saved_at = cached.get("savedAt", 0)
            age_h = (time.time() - saved_at) / 3600
            holiday = cached.get("holiday")
            if age_h < S.holiday_cache_hours and isinstance(holiday, dict):
                return holiday

    holiday: dict[str, Any] = {}
    try:
        resp = requests.get(
            f"https://timor.tech/api/holiday/year/{year}",
            headers=_http_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        raw = payload.get("holiday") or {}
        if isinstance(raw, dict):
            holiday = raw
        with CACHE_LOCK:
            CACHE[cache_key] = {
                "year": year,
                "holiday": holiday,
                "savedAt": time.time(),
            }
        save_cache()
        LOG.info("已缓存 %s 年节假日 %s 条", year, len(holiday))
    except Exception as exc:  # noqa: BLE001
        LOG.warning("年份节假日接口失败 %s: %s", year, exc)
        with CACHE_LOCK:
            cached = CACHE.get(cache_key)
            if isinstance(cached, dict) and isinstance(cached.get("holiday"), dict):
                return cached["holiday"]
    return holiday


def get_day_holiday_info(day: date) -> DayHolidayInfo:
    """
    获取单日节假日展示信息（供日历格子）。

    @param day 日期
    @return DayHolidayInfo
    @author Kai
    @date 2026/07/23 17:35
    """
    year_map = ensure_year_holiday_map(day.year)
    entry = year_map.get(day.strftime("%m-%d"))
    if isinstance(entry, dict):
        name = str(entry.get("name") or "").strip()
        if entry.get("holiday"):
            label = name or "节假日"
            if len(label) > 4:
                label = label[:4]
            return DayHolidayInfo(kind="holiday", label=label, is_workday=False)
        label = "补班"
        if name and "补班" not in name:
            label = name[:4]
        return DayHolidayInfo(kind="makeup", label=label, is_workday=True)

    if day.weekday() >= 5:
        return DayHolidayInfo(kind="weekend", label="休", is_workday=False)
    return DayHolidayInfo(kind="work", label="", is_workday=True)


def prefetch_holidays(days: list[date]) -> dict[str, DayHolidayInfo]:
    """
    批量预取日期范围内的节假日信息。

    @param days 日期列表
    @return date_iso → DayHolidayInfo
    @author Kai
    @date 2026/07/23 17:35
    """
    years = {d.year for d in days}
    for y in years:
        ensure_year_holiday_map(y)
    return {d.isoformat(): get_day_holiday_info(d) for d in days}


def is_workday(day: date) -> bool:
    """
    判断是否为中国工作日（含调休补班）。

    @param day 日期
    @return 是否需要提醒的工作日
    @author Kai
    @date 2026/07/23 15:25
    """
    date_key = day.isoformat()
    cache_key = f"holiday-{date_key}"

    with CACHE_LOCK:
        cached = CACHE.get(cache_key)
        if isinstance(cached, dict):
            saved_at = cached.get("savedAt", 0)
            age_h = (time.time() - saved_at) / 3600
            if age_h < S.holiday_cache_hours and "isWorkday" in cached:
                return bool(cached["isWorkday"])

    try:
        info = get_day_holiday_info(day)
        result = info.is_workday
        with CACHE_LOCK:
            CACHE[cache_key] = {
                "date": date_key,
                "isWorkday": result,
                "kind": info.kind,
                "name": info.label,
                "savedAt": time.time(),
            }
        save_cache()
        return result
    except Exception as exc:  # noqa: BLE001
        LOG.warning("节假日年份判断失败，尝试日接口: %s", exc)

    try:
        resp = requests.get(
            f"https://timor.tech/api/holiday/info/{date_key}",
            headers=_http_headers(),
            timeout=6,
        )
        resp.raise_for_status()
        payload = resp.json()
        type_obj = payload.get("type") or {}
        type_code = int(type_obj.get("type"))
        result = type_code in (0, 3)

        with CACHE_LOCK:
            CACHE[cache_key] = {
                "date": date_key,
                "isWorkday": result,
                "type": type_code,
                "name": type_obj.get("name", ""),
                "savedAt": time.time(),
            }
        save_cache()
        LOG.info("节假日判断 %s type=%s is_workday=%s", date_key, type_code, result)
        return result
    except Exception as exc:  # noqa: BLE001
        LOG.warning("节假日接口失败，回退周一至周五: %s", exc)
        return day.weekday() < 5
