# Copyright (c) iGroup China.
# All rights reserved.
"""
本地 Agent 工具定义与分发。

@author Kai
@date 2026/09/01 10:12
@description 事项/今日、按日、本月考勤/使用时长/搜网/读文件与列目录；受配置开关与白名单约束
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from calendar import monthrange
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote

from . import items_store
from .activity_classify import CAT_LABELS, format_usage_duration
from .activity_tracker import get_activity_tracker
from .attendance import (
    AttendanceSummary,
    fetch_attendance_range,
    get_attendance_for_day,
    live_tick_summary,
)
from .config import S, has_attendance_login
from .holiday import prefetch_holidays
from .paths import LOG
from .runtime_state import get_latest_summary
from .util import format_duration, format_hm

# 先加载 paths 以持久化 CA 证书，再让 requests 缓存 bundle 路径
import requests

# 读文件大小上限（不限制扩展名）
READ_FILE_MAX_BYTES = 64 * 1024
# 单日返回给模型的软件行数上限，合计仍按全部软件算
_MAX_USAGE_APPS = 40
# 列目录上限，避免一次扫爆上下文
LIST_DIR_MAX_ENTRIES = 200
LIST_DIR_MAX_DEPTH = 3
_SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv"}

# 搜网浏览器头（Lite / RSS 需要桌面 UA）
_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def tool_schemas() -> list[dict[str, Any]]:
    """
    返回当前启用的 OpenAI tools schema。

    @return tools 列表
    @author Kai
    @date 2026/08/05 14:15
    """
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "create_item",
                "description": "创建待办或提醒事项",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "事项标题"},
                        "kind": {
                            "type": "string",
                            "enum": ["todo", "reminder"],
                        },
                        "due_at": {
                            "type": "string",
                            "description": "截止时间 ISO8601，可空",
                        },
                        "remind_at": {
                            "type": "string",
                            "description": "提醒时间 ISO8601，可空",
                        },
                        "remind_mode": {
                            "type": "string",
                            "enum": ["fixed", "before_due", "workday"],
                        },
                        "before_minutes": {
                            "type": "integer",
                            "description": "截止前提醒分钟数",
                        },
                        "workday_time": {
                            "type": "string",
                            "description": "工作日提醒 HH:MM",
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_items",
                "description": "列出未完成事项",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "today_only": {
                            "type": "boolean",
                            "description": "仅今日相关",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "complete_item",
                "description": "完成事项（按 id 或标题关键字）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer"},
                        "title_query": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_attendance",
                "description": (
                    "查询今日打卡与剩余工时（实时拉当日接口）。"
                    "指定某一天请用 get_day_attendance。"
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_day_attendance",
                "description": (
                    "按日期查询打卡（底层按日接口）。"
                    "可查某一天、多天或起止区间（最多 31 天，不含未来日）。"
                    "昨天/上周请先换成 YYYY-MM-DD。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "某一天，YYYY-MM-DD；不传则查今天",
                        },
                        "dates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "多个日期 YYYY-MM-DD",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "区间开始 YYYY-MM-DD，需与 end_date 一起",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "区间结束 YYYY-MM-DD，含当天",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_month_attendance",
                "description": (
                    "查询本月考勤：每日上下班、工时、有效天数与均值。"
                    "用户问这个月/本月/当月打卡、出勤、工时统计时必须调用。"
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_app_usage",
                "description": (
                    "查询前台软件使用时长：工作、摸鱼、休息、未分类，以及各软件时长。"
                    "用户问摸鱼、休息、用了什么软件、使用时长时必须调用。"
                    "这不是打卡工时。可查某一天或一段日期（最多 31 天，不含未来）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "某一天 YYYY-MM-DD；不传则查今天",
                        },
                        "dates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "多个日期 YYYY-MM-DD",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "区间开始 YYYY-MM-DD，需与 end_date 一起",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "区间结束 YYYY-MM-DD，含当天",
                        },
                    },
                },
            },
        },
    ]
    if S.ai_enable_web_search:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": (
                        "搜索互联网并返回标题/链接/摘要。"
                        "请使用具体关键词；可用于新闻、文档、产品信息等。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                },
            }
        )
    if S.ai_enable_read_file:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": (
                        "列出白名单目录内容，相当于 ls / dir。"
                        "path 为空则列出已配置的白名单根目录；"
                        "也可传目录、相对白名单的路径，或 *.md 这类 glob。"
                        "不确定文件名时必须先调用本工具，再 read_file。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "目录、相对路径或 glob；空=白名单根",
                            },
                            "recursive": {
                                "type": "boolean",
                                "description": "是否递归子目录，默认 false",
                            },
                            "glob": {
                                "type": "string",
                                "description": "可选过滤，如 *.md",
                            },
                        },
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "ls",
                    "description": (
                        "list_dir 的别名，列出白名单目录（ls）。"
                        "path 为空列出白名单根。不要因为没有 shell 就放弃列目录。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "recursive": {"type": "boolean"},
                            "glob": {"type": "string"},
                        },
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": (
                        "读取白名单内的文件，不限制扩展名。"
                        "path 可以是绝对路径、相对白名单的文件名，或 glob。"
                        "若 path 指向目录，自动改为列出该目录。"
                        "不知道确切文件名时先 list_dir / ls。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                },
            }
        )
    return tools


def _tool_create_item(args: dict[str, Any]) -> dict[str, Any]:
    """
    执行 create_item。

    @param args 工具参数
    @return 结果字典
    @author Kai
    @date 2026/08/05 16:12
    """
    from .achievements import bump_achievement

    mode = str(args.get("remind_mode") or "fixed")
    remind_at = args.get("remind_at") or None
    due_at = args.get("due_at") or None
    workday_time = args.get("workday_time") or None
    warn = ""
    if mode == "workday" and not workday_time:
        warn = "缺少 workday_time，到点不会提醒"
    elif mode != "workday" and not remind_at and not due_at:
        if str(args.get("kind") or "") == "reminder" or mode in (
            "fixed",
            "before_due",
        ):
            warn = "缺少 remind_at/due_at，到点不会提醒"
    item = items_store.create_item(
        str(args.get("title") or ""),
        kind=str(args.get("kind") or "todo"),
        due_at=due_at,
        remind_at=remind_at,
        remind_mode=mode,
        before_minutes=int(args.get("before_minutes") or 30),
        workday_time=workday_time,
        notes=str(args.get("notes") or ""),
    )
    bump_achievement("first_capture")
    out: dict[str, Any] = {"ok": True, "item": item.to_dict()}
    if warn:
        out["warning"] = warn
    return out


def _tool_list_items(args: dict[str, Any]) -> dict[str, Any]:
    """执行 list_items。"""
    today_only = bool(args.get("today_only", False))
    items = items_store.list_items(status="open", today_only=today_only)
    return {"ok": True, "count": len(items), "items": [i.to_dict() for i in items]}


def _tool_complete_item(args: dict[str, Any]) -> dict[str, Any]:
    """执行 complete_item。"""
    item_id = args.get("item_id")
    title_query = args.get("title_query")
    item = items_store.complete_item(
        item_id=int(item_id) if item_id is not None else None,
        title_query=str(title_query) if title_query else None,
    )
    if not item:
        return {"ok": False, "error": "未找到匹配的未完成事项"}
    return {"ok": True, "item": item.to_dict()}


def _tool_get_attendance(_args: dict[str, Any]) -> dict[str, Any]:
    """
    拉今日打卡接口并按本地时钟重算倒计时。

    @param _args 无业务参数
    @return 今日考勤摘要；Token 过期时 ok=false
    @author Kai
    @date 2026/09/01 10:12
    """
    now = datetime.now()
    summary: Optional[AttendanceSummary] = None
    stale = False
    if S.attendance_token or has_attendance_login():
        try:
            summary = get_attendance_for_day(now.date(), now)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("get_attendance 拉取失败: %s", exc)
            summary = None
    # 接口失败（非 Token 过期）时回退内存中的最新摘要，并标 stale
    if summary is None or (not summary.ok and not summary.token_expired):
        cached = get_latest_summary()
        if isinstance(cached, AttendanceSummary):
            summary = cached
            stale = True
    if summary is None:
        return {"ok": False, "error": "尚无考勤数据，请配置 Token 或稍后刷新"}
    live = live_tick_summary(summary, now) if summary.has_clock_in else summary
    if live.token_expired:
        return {
            "ok": False,
            "error": live.error or "登录已过期，请更新 Token",
            "token_expired": True,
            "date": live.date or now.date().isoformat(),
        }
    payload: dict[str, Any] = {
        "ok": bool(live.ok),
        "date": live.date or now.date().isoformat(),
        "in": format_hm(live.in_time),
        "out": format_hm(live.latest_out_time),
        "target": format_hm(live.target_time),
        "has_clock_in": bool(live.has_clock_in),
        "target_reached": bool(live.target_reached),
        "remaining": format_duration(int(live.remaining_seconds or 0)),
        "worked": format_duration(int(live.worked_seconds or 0)),
        "leave_hours": float(live.leave_hours or 0),
        "token_expired": False,
        "error": str(live.error or ""),
        "validity_tip": str(live.validity_tip or ""),
        "cached": bool(getattr(live, "cached", False)),
    }
    if stale:
        payload["stale"] = True
    if not live.ok:
        payload["ok"] = False
        payload["error"] = payload["error"] or "拉取考勤失败"
    return payload


_WEEKDAY_CN = "一二三四五六日"


def _month_days_until_today(anchor: Optional[date] = None) -> list[date]:
    """
    本月 1 号至今天（不含未来日，避免空请求）。

    @param anchor 锚点日，默认今天
    @return 日期列表
    @author Kai
    @date 2026/08/31 17:40
    """
    today = anchor or date.today()
    last = min(today.day, monthrange(today.year, today.month)[1])
    return [date(today.year, today.month, day) for day in range(1, last + 1)]


def _day_worked_text(summary: AttendanceSummary, today: date) -> str:
    """
    单日工时文案：有下班卡按打卡时段；今日进行中用工时；历史未下班留空。

    @param summary 日摘要
    @param today 今天
    @return 工时字符串，未知则为空
    @author Kai
    @date 2026/08/31 17:40
    """
    if not summary.ok or not summary.has_clock_in or summary.in_time is None:
        return ""
    if summary.latest_out_time is not None:
        seconds = max(
            0, int((summary.latest_out_time - summary.in_time).total_seconds())
        )
        return format_duration(seconds)
    try:
        day_obj = date.fromisoformat(str(summary.date)[:10])
    except ValueError:
        day_obj = None
    if day_obj is not None and day_obj < today:
        return ""
    return format_duration(max(0, int(summary.worked_seconds)))


def _parse_iso_date(text: str) -> Optional[date]:
    """
    解析 YYYY-MM-DD（也接受 2026/09/01）。

    @param text 日期字符串
    @return date 或 None
    @author Kai
    @date 2026/09/01 09:50
    """
    raw = str(text or "").strip().replace("/", "-")
    if len(raw) < 8:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _attendance_day_row(
    day: date,
    summary: Optional[AttendanceSummary],
    holiday: Any,
    today: date,
) -> dict[str, Any]:
    """
    把单日摘要压成工具返回行。

    @param day 日期
    @param summary 打卡摘要，可空
    @param holiday 节假日信息，可空
    @param today 今天
    @return 单日字典
    @author Kai
    @date 2026/09/01 09:50
    """
    kind = holiday.kind if holiday else "work"
    label = (holiday.label if holiday else "") or ""
    base = {
        "date": day.isoformat(),
        "weekday": _WEEKDAY_CN[day.weekday()],
        "kind": kind,
        "label": label,
    }
    if summary is None:
        base["status"] = "无数据"
        return base
    if summary.error == "FUTURE":
        base["status"] = "未来日"
        return base
    base.update(
        {
            "in": format_hm(summary.in_time) if summary.has_clock_in else "--",
            "out": format_hm(summary.latest_out_time)
            if summary.has_clock_out
            else "--",
            "target": format_hm(summary.target_time) if summary.target_time else "--",
            "worked": _day_worked_text(summary, today) or "--",
            "status": str(summary.validity_tip or "").strip()
            or ("未打卡" if not summary.has_clock_in else "正常"),
            "valid": bool(summary.is_valid_attendance),
            "leave_h": float(summary.leave_hours or 0),
            "remaining": format_duration(int(summary.remaining_seconds or 0))
            if day == today and not summary.target_reached
            else "",
            "cached": bool(getattr(summary, "cached", False)),
        }
    )
    if not summary.ok and summary.error and summary.error != "FUTURE":
        base["error"] = str(summary.error)[:80]
    return base


_MAX_DAY_QUERY = 31


def _collect_query_days(args: dict[str, Any], today: date) -> list[date]:
    """
    从工具参数收集要查询的日期（去重、排序、去掉未来、最多 31 天）。

    @param args date / dates / start_date / end_date
    @param today 今天
    @return 日期列表
    @author Kai
    @date 2026/09/01 09:50
    """
    days: list[date] = []
    raw_dates = args.get("dates")
    if isinstance(raw_dates, list):
        for item in raw_dates:
            parsed = _parse_iso_date(str(item))
            if parsed is not None:
                days.append(parsed)
    start = _parse_iso_date(str(args.get("start_date") or ""))
    end = _parse_iso_date(str(args.get("end_date") or ""))
    one = _parse_iso_date(str(args.get("date") or ""))
    if start is not None and end is not None:
        if end < start:
            start, end = end, start
        cursor = start
        while cursor <= end:
            days.append(cursor)
            cursor += timedelta(days=1)
    elif one is not None:
        days.append(one)
    if not days:
        days = [today]
    unique: list[date] = []
    seen: set[date] = set()
    for day in sorted(days):
        if day in seen or day > today:
            continue
        seen.add(day)
        unique.append(day)
        if len(unique) >= _MAX_DAY_QUERY:
            break
    return unique


def _tool_get_day_attendance(args: dict[str, Any]) -> dict[str, Any]:
    """
    按日拉取打卡，对应 get_attendance_for_day / 批量按日接口。

    @param args date / dates / start_date / end_date
    @return 单日或逐日列表
    @author Kai
    @date 2026/09/01 09:50
    """
    if not S.attendance_token and not has_attendance_login():
        return {"ok": False, "error": "未配置 Token"}
    today = date.today()
    days = _collect_query_days(args, today)
    if not days:
        return {"ok": False, "error": "日期无效或都在未来"}
    if len(days) == 1:
        records = {days[0].isoformat(): get_attendance_for_day(days[0])}
    else:
        records = fetch_attendance_range(days)
    holidays = prefetch_holidays(days)
    rows: list[dict[str, Any]] = []
    for day in days:
        summary = records.get(day.isoformat())
        if summary is not None and summary.token_expired:
            return {"ok": False, "error": "登录已过期，请更新 Token"}
        rows.append(
            _attendance_day_row(day, summary, holidays.get(day.isoformat()), today)
        )
    if len(rows) == 1:
        return {"ok": True, "today": today.isoformat(), "day": rows[0]}
    return {
        "ok": True,
        "today": today.isoformat(),
        "range": f"{days[0].isoformat()} ~ {days[-1].isoformat()}",
        "count": len(rows),
        "days": rows,
    }


def _hm_to_minutes(text: str) -> Optional[int]:
    """HH:MM → 自 0 点起的分钟数。"""
    try:
        hour, minute = text.split(":")
        return int(hour) * 60 + int(minute)
    except Exception:  # noqa: BLE001
        return None


def _avg_hm(values: list[int]) -> str:
    """分钟列表 → 平均 HH:MM。"""
    if not values:
        return "--"
    avg = int(round(sum(values) / len(values)))
    return f"{avg // 60:02d}:{avg % 60:02d}"


def _tool_get_month_attendance(_args: dict[str, Any]) -> dict[str, Any]:
    """
    拉取本月打卡并汇总，供对话回答本月考勤。

    @param _args 无参数
    @return 月度摘要与逐日列表
    @author Kai
    @date 2026/08/31 17:40
    """
    if not S.attendance_token and not has_attendance_login():
        return {"ok": False, "error": "未配置 Token"}
    today = date.today()
    days = _month_days_until_today(today)
    if not days:
        return {"ok": False, "error": "无法确定本月日期"}
    records = fetch_attendance_range(days)
    holidays = prefetch_holidays(days)
    day_rows: list[dict[str, Any]] = []
    punched: list[AttendanceSummary] = []
    for day in days:
        key = day.isoformat()
        summary = records.get(key)
        if summary is not None and summary.token_expired:
            return {"ok": False, "error": "登录已过期，请更新 Token"}
        day_rows.append(
            _attendance_day_row(day, summary, holidays.get(key), today)
        )
        if (
            summary is not None
            and summary.ok
            and summary.has_clock_in
            and summary.error != "FUTURE"
        ):
            punched.append(summary)

    in_mins = [
        m
        for m in (_hm_to_minutes(format_hm(s.in_time)) for s in punched)
        if m is not None
    ]
    out_mins = [
        m
        for m in (_hm_to_minutes(format_hm(s.latest_out_time)) for s in punched)
        if m is not None
    ]
    target_mins = [
        m
        for m in (_hm_to_minutes(format_hm(s.target_time)) for s in punched)
        if m is not None
    ]
    valid_days = sum(1 for s in punched if s.is_valid_attendance)
    reached = sum(1 for s in punched if s.target_reached)
    return {
        "ok": True,
        "year_month": today.strftime("%Y-%m"),
        "range": f"{days[0].isoformat()} ~ {days[-1].isoformat()}",
        "today": today.isoformat(),
        "metrics": {
            "punched_days": len(punched),
            "valid_days": valid_days,
            "reached_days": reached,
            "avg_in": _avg_hm(in_mins),
            "avg_out": _avg_hm(out_mins),
            "avg_target": _avg_hm(target_mins),
            "avg_work": _avg_work_from_summaries(punched, today),
        },
        "days": day_rows,
    }


def _avg_work_from_summaries(
    punched: list[AttendanceSummary],
    today: date,
) -> str:
    """
    有打卡日的平均工时。

    @param punched 有上班卡的摘要
    @param today 今天
    @return 平均工时文案
    @author Kai
    @date 2026/08/31 17:40
    """
    seconds_list: list[int] = []
    for summary in punched:
        if not summary.has_clock_in or summary.in_time is None:
            continue
        if summary.latest_out_time is not None:
            seconds_list.append(
                max(
                    0,
                    int((summary.latest_out_time - summary.in_time).total_seconds()),
                )
            )
            continue
        try:
            day_obj = date.fromisoformat(str(summary.date)[:10])
        except ValueError:
            day_obj = None
        if day_obj is not None and day_obj < today:
            continue
        seconds_list.append(max(0, int(summary.worked_seconds)))
    if not seconds_list:
        return "--"
    avg = int(round(sum(seconds_list) / len(seconds_list)))
    return format_duration(avg)


def _strip_html(text: str) -> str:
    """去掉简单 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", unescape(text or "")).strip()


def _search_ddg_instant(query: str, top_k: int) -> list[dict[str, str]]:
    """
    DuckDuckGo Instant Answer（百科摘要类较好，新闻类常为空）。

    @param query 查询词
    @param top_k 条数
    @return 结果列表
    @author Kai
    @date 2026/08/05 14:59
    """
    resp = requests.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        headers=_SEARCH_HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results: list[dict[str, str]] = []
    abstract = str(data.get("AbstractText") or "").strip()
    if abstract:
        results.append(
            {
                "title": str(data.get("Heading") or query),
                "url": str(data.get("AbstractURL") or ""),
                "snippet": abstract[:400],
            }
        )
    for topic in data.get("RelatedTopics") or []:
        if len(results) >= top_k:
            break
        if isinstance(topic, dict) and topic.get("Text"):
            results.append(
                {
                    "title": str(topic.get("Text") or "")[:80],
                    "url": str(topic.get("FirstURL") or ""),
                    "snippet": str(topic.get("Text") or "")[:300],
                }
            )
        elif isinstance(topic, dict) and isinstance(topic.get("Topics"), list):
            for sub in topic["Topics"]:
                if len(results) >= top_k:
                    break
                if isinstance(sub, dict) and sub.get("Text"):
                    results.append(
                        {
                            "title": str(sub.get("Text") or "")[:80],
                            "url": str(sub.get("FirstURL") or ""),
                            "snippet": str(sub.get("Text") or "")[:300],
                        }
                    )
    return results[:top_k]


def _search_ddg_lite(query: str, top_k: int) -> list[dict[str, str]]:
    """
    DuckDuckGo Lite HTML 解析（适合通用检索与中文热点）。

    @param query 查询词
    @param top_k 条数
    @return 结果列表
    @author Kai
    @date 2026/08/05 14:59
    """
    resp = requests.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": query},
        headers=_SEARCH_HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    html = resp.text
    blocks = re.findall(
        r'<a rel="nofollow" href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.S | re.I,
    )
    snips = re.findall(
        r'class="result-snippet">(.*?)</td>',
        html,
        re.S | re.I,
    )
    snip_texts = [_strip_html(s)[:300] for s in snips]
    results: list[dict[str, str]] = []
    for idx, (href, title_html) in enumerate(blocks):
        href_u = unescape(href)
        m = re.search(r"uddg=([^&]+)", href_u)
        url = unquote(m.group(1)) if m else href_u
        if "duckduckgo.com" in url:
            continue
        title = _strip_html(title_html)[:120]
        if not title:
            continue
        results.append(
            {
                "title": title,
                "url": url if url.startswith("http") else f"https:{url}",
                "snippet": snip_texts[idx] if idx < len(snip_texts) else "",
            }
        )
        if len(results) >= top_k:
            break
    return results


def _search_bing_rss(query: str, top_k: int) -> list[dict[str, str]]:
    """
    Bing 搜索 RSS（补充源，对中文新闻较稳）。

    @param query 查询词
    @param top_k 条数
    @return 结果列表
    @author Kai
    @date 2026/08/05 14:59
    """
    resp = requests.get(
        "https://www.bing.com/search",
        params={"q": query, "format": "rss"},
        headers=_SEARCH_HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    results: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description") or "")[:300]
        if not title or not link:
            continue
        results.append({"title": title, "url": link, "snippet": desc})
        if len(results) >= top_k:
            break
    return results


def _merge_search_results(
    *batches: list[dict[str, str]],
    top_k: int,
) -> list[dict[str, str]]:
    """
    按 URL 去重合并多路结果。

    @param batches 多批结果
    @param top_k 上限
    @return 合并列表
    @author Kai
    @date 2026/08/05 14:59
    """
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for batch in batches:
        for item in batch:
            url = (item.get("url") or "").strip()
            key = url or (item.get("title") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= top_k:
                return out
    return out


def _tool_web_search(args: dict[str, Any]) -> dict[str, Any]:
    """
    搜网：自定义 endpoint → DDG Instant → DDG Lite → Bing RSS。

    @param args query / top_k
    @return 结果字典；无结果时 ok=false，避免模型误报「联网成功但无内容」
    @author Kai
    @date 2026/08/05 14:59
    """
    if not S.ai_enable_web_search:
        return {"ok": False, "error": "搜网未启用"}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query 为空"}
    top_k = max(1, min(8, int(args.get("top_k") or 5)))
    endpoint = (S.ai_search_endpoint or "").strip()
    sources_tried: list[str] = []
    try:
        if endpoint:
            sources_tried.append("custom")
            headers = dict(_SEARCH_HEADERS)
            headers["Accept"] = "application/json"
            if S.ai_search_api_key:
                headers["Authorization"] = f"Bearer {S.ai_search_api_key}"
            resp = requests.get(
                endpoint,
                params={"q": query, "query": query},
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "query": query, "raw": data, "source": "custom"}

        instant: list[dict[str, str]] = []
        lite: list[dict[str, str]] = []
        bing: list[dict[str, str]] = []
        try:
            sources_tried.append("duckduckgo_instant")
            instant = _search_ddg_instant(query, top_k)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("DDG Instant 失败: %s", exc)
        try:
            sources_tried.append("duckduckgo_lite")
            lite = _search_ddg_lite(query, top_k)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("DDG Lite 失败: %s", exc)
        try:
            sources_tried.append("bing_rss")
            bing = _search_bing_rss(query, top_k)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Bing RSS 失败: %s", exc)

        results = _merge_search_results(lite, bing, instant, top_k=top_k)
        if not results:
            return {
                "ok": False,
                "query": query,
                "error": (
                    "各搜索源均未返回有效结果。"
                    f"已尝试：{', '.join(sources_tried)}。"
                    "可换更具体的关键词，或在设置中配置 search_endpoint。"
                ),
                "results": [],
            }
        return {
            "ok": True,
            "query": query,
            "results": results,
            "source": "+".join(sources_tried),
            "count": len(results),
        }
    except Exception as exc:  # noqa: BLE001
        LOG.warning("web_search 失败: %s", exc)
        return {"ok": False, "error": str(exc)}


def _whitelist_roots() -> list[Path]:
    """
    解析已配置的读文件白名单根目录。

    @return 规范化后的根路径列表
    @author Kai
    @date 2026/09/02 16:43
    """
    roots: list[Path] = []
    seen: set[str] = set()
    for d in S.ai_file_whitelist_dirs:
        try:
            root = Path(d).expanduser().resolve(strict=False)
        except OSError:
            continue
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _normalize_path_arg(path_str: str) -> str:
    """
    去掉引号、file:// 前缀，便于模型乱填路径时仍能解析。

    @param path_str 工具传入的原始路径
    @return 清理后的路径字符串
    @author Kai
    @date 2026/09/02 16:43
    """
    raw = str(path_str or "").strip().strip('"').strip("'")
    if raw.lower().startswith("file:"):
        raw = unquote(raw[5:].lstrip("/\\"))
        # file:///D:/Notes → D:/Notes
        if re.match(r"^[A-Za-z]%3A", raw) or (
            len(raw) >= 2 and raw[1] == ":"
        ):
            pass
        elif re.match(r"^[A-Za-z]:", raw) is None and len(raw) >= 2:
            # /D:/Notes
            if re.match(r"^[A-Za-z]:", raw.lstrip("/\\")):
                raw = raw.lstrip("/\\")
    if raw in {".", "./", ".\\", "ls", "dir"}:
        return ""
    return raw


def _is_glob_pattern(text: str) -> bool:
    """
    是否为 glob 模式（含 * ? [）。

    @param text 路径或过滤串
    @return 是否 glob
    @author Kai
    @date 2026/09/02 16:43
    """
    return bool(text) and any(ch in text for ch in "*?[")


def _under_whitelist(target: Path, roots: list[Path]) -> bool:
    """
    目标是否落在任一白名单根下。

    @param target 已 resolve 的路径
    @param roots 白名单根
    @return 是否允许
    @author Kai
    @date 2026/09/02 16:43
    """
    for root in roots:
        try:
            if target == root or target.is_relative_to(root):
                return True
        except (ValueError, OSError):
            continue
    return False


def _resolve_whitelisted(path_str: str) -> Path:
    """
    解析并校验白名单路径；相对路径会依次拼到各白名单根上。

    @param path_str 用户给出的路径
    @return 规范化 Path
    @author Kai
    @date 2026/09/02 16:43
    """
    raw = _normalize_path_arg(path_str)
    if not raw:
        raise PermissionError("路径为空")
    roots = _whitelist_roots()
    if not roots:
        raise PermissionError("未配置读文件白名单目录")

    candidates: list[Path] = []
    direct = Path(raw).expanduser()
    try_paths: list[Path] = []
    if direct.is_absolute():
        try_paths.append(direct)
    else:
        try_paths.extend(root / raw for root in roots)
        # 只给了文件名时，在白名单内浅层搜索
        name = Path(raw).name
        if name and name == raw.replace("\\", "/").rstrip("/"):
            for root in roots:
                if not root.is_dir():
                    continue
                try:
                    try_paths.extend(root.rglob(name))
                except OSError:
                    continue

    for item in try_paths:
        try:
            target = item.resolve(strict=False)
        except OSError:
            continue
        if target.is_symlink():
            continue
        if not _under_whitelist(target, roots):
            continue
        if target.exists():
            candidates.append(target)
            if len(candidates) >= 8:
                break

    # 去重并保持顺序
    uniq: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    if len(uniq) == 1:
        return uniq[0]
    if len(uniq) > 1:
        listed = "；".join(str(p) for p in uniq[:6])
        raise PermissionError(f"匹配到多个路径，请写得更具体：{listed}")

    # 允许尚不存在的绝对路径（便于报「不存在」而不是「不在白名单」）
    if direct.is_absolute():
        try:
            target = direct.resolve(strict=False)
        except OSError as exc:
            raise PermissionError(f"无法解析路径: {exc}") from exc
        if target.is_symlink():
            raise PermissionError("拒绝读取符号链接")
        if not _under_whitelist(target, roots):
            raise PermissionError("路径不在白名单目录内")
        return target

    roots_hint = "、".join(str(r) for r in roots[:4])
    raise PermissionError(
        f"路径不在白名单目录内或不存在。白名单根：{roots_hint}。"
        "可先 list_dir 查看。"
    )


def _entry_payload(path: Path, root: Optional[Path] = None) -> dict[str, Any]:
    """
    单条目录项摘要。

    @param path 文件或目录
    @param root 用于计算相对路径的根
    @return 展示用字典
    @author Kai
    @date 2026/09/02 16:43
    """
    rel = path.name
    if root is not None:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
    kind = "dir" if path.is_dir() else "file"
    item: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "relative": rel.replace("\\", "/"),
        "type": kind,
    }
    if kind == "file":
        try:
            item["size"] = path.stat().st_size
        except OSError:
            item["size"] = None
        item["suffix"] = path.suffix.lower()
    return item


def _collect_dir_entries(
    directory: Path,
    *,
    recursive: bool,
    glob_pat: str,
    limit: int,
) -> list[dict[str, Any]]:
    """
    收集目录条目（跳过常见垃圾目录与符号链接）。

    @param directory 要列的目录
    @param recursive 是否递归
    @param glob_pat 可选 glob，空则列出全部
    @param limit 最多条数
    @return 条目列表
    @author Kai
    @date 2026/09/02 16:43
    """
    entries: list[dict[str, Any]] = []
    if not directory.is_dir():
        return entries
    pattern = glob_pat.strip() if glob_pat else ""
    if recursive:
        walker = (
            directory.rglob(pattern or "*")
            if pattern
            else directory.rglob("*")
        )
    else:
        walker = (
            directory.glob(pattern) if pattern else directory.iterdir()
        )
    for item in walker:
        if len(entries) >= limit:
            break
        try:
            if item.is_symlink():
                continue
            # 限制递归深度，避免扫到很深的树
            if recursive:
                try:
                    depth = len(item.relative_to(directory).parts)
                except ValueError:
                    depth = LIST_DIR_MAX_DEPTH + 1
                if depth > LIST_DIR_MAX_DEPTH:
                    continue
            if item.is_dir() and item.name in _SKIP_DIR_NAMES:
                continue
            if any(p in _SKIP_DIR_NAMES for p in item.parts):
                continue
            entries.append(_entry_payload(item, directory))
        except OSError:
            continue
    entries.sort(key=lambda x: (x.get("type") != "dir", str(x.get("relative") or "")))
    return entries


def _list_glob_under_roots(
    roots: list[Path],
    glob_pat: str,
    *,
    recursive: bool,
    limit: int,
) -> list[dict[str, Any]]:
    """
    在各白名单根下按 glob 找文件。

    @param roots 白名单根
    @param glob_pat glob 表达式
    @param recursive 是否用 rglob
    @param limit 上限
    @return 条目列表
    @author Kai
    @date 2026/09/02 16:43
    """
    entries: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            walker = root.rglob(glob_pat) if recursive else root.glob(glob_pat)
        except OSError:
            continue
        for item in walker:
            if len(entries) >= limit:
                return entries
            try:
                if item.is_symlink() or not _under_whitelist(item.resolve(strict=False), roots):
                    continue
                if any(p in _SKIP_DIR_NAMES for p in item.parts):
                    continue
                entries.append(_entry_payload(item, root))
            except OSError:
                continue
    return entries


def _tool_list_dir(args: dict[str, Any]) -> dict[str, Any]:
    """
    列出白名单目录（ls）。

    @param args path / recursive / glob
    @return 结果字典
    @author Kai
    @date 2026/09/02 16:43
    """
    if not S.ai_enable_read_file:
        return {"ok": False, "error": "读文件未启用"}
    roots = _whitelist_roots()
    if not roots:
        return {
            "ok": False,
            "error": "未配置读文件白名单目录。请在设置 → AI → 读文件白名单中填写目录。",
        }
    raw = _normalize_path_arg(str(args.get("path") or args.get("dir") or ""))
    glob_pat = str(args.get("glob") or args.get("pattern") or "").strip()
    recursive = bool(args.get("recursive") or args.get("r") or False)
    limit = LIST_DIR_MAX_ENTRIES

    # 空路径：列出白名单根，便于模型知道从哪 ls
    if not raw and not glob_pat:
        return {
            "ok": True,
            "kind": "roots",
            "hint": "对某个 path 再调用 list_dir / ls 查看里面的文件",
            "roots": [
                {
                    "path": str(root),
                    "exists": root.is_dir(),
                    "type": "dir" if root.is_dir() else "missing",
                }
                for root in roots
            ],
        }

    try:
        if glob_pat or _is_glob_pattern(raw):
            pattern = glob_pat or raw
            entries = _list_glob_under_roots(
                roots, pattern, recursive=recursive or _is_glob_pattern(raw), limit=limit
            )
            return {
                "ok": True,
                "kind": "glob",
                "pattern": pattern,
                "count": len(entries),
                "truncated": len(entries) >= limit,
                "entries": entries,
            }

        target = _resolve_whitelisted(raw)
        if target.is_file():
            return {
                "ok": True,
                "kind": "file",
                "hint": "这是文件，请用 read_file 读取内容",
                "entry": _entry_payload(target),
            }
        if not target.exists():
            return {"ok": False, "error": f"路径不存在：{target}"}
        if not target.is_dir():
            return {"ok": False, "error": "不是目录"}
        entries = _collect_dir_entries(
            target, recursive=recursive, glob_pat=glob_pat, limit=limit
        )
        return {
            "ok": True,
            "kind": "dir",
            "path": str(target),
            "count": len(entries),
            "truncated": len(entries) >= limit,
            "entries": entries,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _tool_read_file(args: dict[str, Any]) -> dict[str, Any]:
    """
    执行 read_file；目录或 glob 时自动改列目录。

    @param args 含 path
    @return 结果字典
    @author Kai
    @date 2026/09/02 16:43
    """
    if not S.ai_enable_read_file:
        return {"ok": False, "error": "读文件未启用"}
    path_str = str(args.get("path") or args.get("file") or "").strip()
    if not path_str:
        listed = _tool_list_dir({"path": ""})
        listed["hint"] = "path 为空，已改为列出白名单根目录。请指定文件后再 read_file。"
        return listed
    raw = _normalize_path_arg(path_str)
    if _is_glob_pattern(raw):
        return _tool_list_dir({"path": raw, "recursive": True})
    try:
        target = _resolve_whitelisted(path_str)
        if target.is_dir():
            listed = _tool_list_dir({"path": str(target)})
            listed["hint"] = "path 是目录，已改为列出内容。请对具体文件再调用 read_file。"
            return listed
        if not target.is_file():
            return {
                "ok": False,
                "error": f"不是文件或不存在：{target}。可先 list_dir / ls。",
            }
        size = target.stat().st_size
        if size > READ_FILE_MAX_BYTES:
            return {
                "ok": False,
                "error": f"文件过大（{size} > {READ_FILE_MAX_BYTES}）",
            }
        data = target.read_bytes()
        binary = b"\x00" in data[:4096]
        text = data.decode("utf-8", errors="replace")
        result: dict[str, Any] = {
            "ok": True,
            "path": str(target),
            "size": size,
            "content": text,
        }
        if binary:
            result["binary"] = True
            result["hint"] = "文件含二进制内容，已按 UTF-8 尽量解码，可能有乱码。"
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _tool_get_app_usage(args: dict[str, Any]) -> dict[str, Any]:
    """
    把使用时长压成工具结果。只含软件名和归类，不含窗口标题。

    @param args date / dates / start_date / end_date
    @return 逐日合计与软件列表
    @author Kai
    @date 2026/09/29 15:32
    """
    today = date.today()
    days = _collect_query_days(args, today)
    tracker = get_activity_tracker()
    payload: list[dict[str, Any]] = []
    for day in days:
        totals = tracker.totals_for(day)
        rows = tracker.rows_for(day)
        apps = [
            {
                "name": row.display_name,
                "category": CAT_LABELS.get(row.category, row.category),
                "duration": format_usage_duration(row.seconds),
                "seconds": row.seconds,
            }
            for row in rows[:_MAX_USAGE_APPS]
        ]
        payload.append(
            {
                "date": day.isoformat(),
                "weekday": _WEEKDAY_CN[day.weekday()],
                "work": format_usage_duration(totals.get("work", 0)),
                "slack": format_usage_duration(totals.get("slack", 0)),
                "rest": format_usage_duration(totals.get("rest", 0)),
                "unknown": format_usage_duration(totals.get("unknown", 0)),
                "work_seconds": int(totals.get("work", 0)),
                "slack_seconds": int(totals.get("slack", 0)),
                "rest_seconds": int(totals.get("rest", 0)),
                "unknown_seconds": int(totals.get("unknown", 0)),
                "apps": apps,
                "apps_truncated": len(rows) > _MAX_USAGE_APPS,
            }
        )
    return {
        "ok": True,
        "note": (
            "只统计本程序运行期间的时间。"
            "锁屏、超过 1 分钟无操作、桌面和开始菜单记为休息。"
            "手动暂停，以及一次断档超过 4 小时，不补记。"
            "浏览器按当前标签的域名归类，不保存完整网址和窗口标题。"
        ),
        "days": payload,
    }


_DISPATCH: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "create_item": _tool_create_item,
    "list_items": _tool_list_items,
    "complete_item": _tool_complete_item,
    "get_attendance": _tool_get_attendance,
    "get_day_attendance": _tool_get_day_attendance,
    "get_month_attendance": _tool_get_month_attendance,
    "get_app_usage": _tool_get_app_usage,
    "web_search": _tool_web_search,
    "read_file": _tool_read_file,
    "list_dir": _tool_list_dir,
    "ls": _tool_list_dir,
    "dir": _tool_list_dir,
}


def dispatch_tool(name: str, arguments: Any) -> str:
    """
    执行工具并返回 JSON 字符串。

    @param name 工具名
    @param arguments 参数（dict 或 JSON 字符串）
    @return JSON 文本
    @author Kai
    @date 2026/08/05 14:15
    """
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            args = {}
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}
    fn = _DISPATCH.get(name)
    if not fn:
        result: dict[str, Any] = {"ok": False, "error": f"未知工具: {name}"}
    else:
        try:
            result = fn(args)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("工具执行失败 name=%s", name)
            result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False)
