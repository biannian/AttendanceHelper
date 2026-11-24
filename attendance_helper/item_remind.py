# Copyright (c) iGroup China.
# All rights reserved.
"""
事项提醒调度：固定时间 / 截止前 / 工作日。

@author Kai
@date 2026/08/05 15:45
@description 当天内可补弹，避免 2 分钟窄窗口漏提醒
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from . import items_store
from .holiday import is_workday
from .items_store import (
    REMIND_BEFORE_DUE,
    REMIND_FIXED,
    REMIND_WORKDAY,
    ItemRecord,
)
from .paths import LOG


def _parse_dt(value: str | None) -> datetime | None:
    """
    解析 ISO / 空格分隔本地时间。

    @param value 时间字符串
    @return datetime 或 None
    @author Kai
    @date 2026/08/05 14:15
    """
    if not value:
        return None
    raw = str(value).strip().replace("T", " ")
    # 截掉时区尾巴再试常见格式
    raw_main = raw.split("+")[0].split(".")[0].strip()
    for fmt, n in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    ):
        try:
            return datetime.strptime(raw_main[:n], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _due_remind_at(item: ItemRecord) -> datetime | None:
    """
    计算本条事项的应提醒时刻（非工作日模式）。

    @param item 事项
    @return 提醒时刻
    @author Kai
    @date 2026/08/05 15:45
    """
    if item.remind_mode == REMIND_BEFORE_DUE:
        due = _parse_dt(item.due_at)
        if due is None:
            return _parse_dt(item.remind_at)
        return due - timedelta(minutes=max(0, item.before_minutes))
    # fixed：优先 remind_at，缺省时用 due_at 兜底
    at = _parse_dt(item.remind_at)
    if at is not None:
        return at
    return _parse_dt(item.due_at)


def _workday_due_today(item: ItemRecord, now: datetime) -> datetime | None:
    """
    工作日模式下今日应提醒时刻。

    @param item 事项
    @param now 当前时间
    @return 今日 HH:MM 对应 datetime；非工作日 None
    @author Kai
    @date 2026/08/05 14:15
    """
    if not is_workday(now.date()):
        return None
    t = (item.workday_time or "").strip()
    if not t or ":" not in t:
        return None
    try:
        parts = t.replace("：", ":").split(":")
        hh, mm = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except ValueError:
        return None


def _should_fire_now(due: datetime, now: datetime) -> bool:
    """
    是否应在当前时刻触发（当天内到达或过期均可补弹一次）。

    @param due 应提醒时刻
    @param now 现在
    @return 是否触发
    @author Kai
    @date 2026/08/05 15:45
    """
    if now < due:
        return False
    # 仅补弹「提醒日落在今天」的事项，避免历史事项重启后狂弹
    if due.date() != now.date():
        return False
    return True


def evaluate_item_reminders(
    notify: Callable[[str, str], None],
    *,
    now: datetime | None = None,
) -> list[int]:
    """
    扫描到期事项并通知（每项每天最多一次）。

    @param notify (title, body) 回调
    @param now 当前时间
    @return 本次触发的 item id 列表
    @author Kai
    @date 2026/08/05 15:45
    """
    now = now or datetime.now()
    day = now.date().isoformat()
    fired: list[int] = []
    for item in items_store.open_items_for_remind():
        due: datetime | None = None
        if item.remind_mode == REMIND_WORKDAY:
            due = _workday_due_today(item, now)
            if due is None and not (item.workday_time or "").strip():
                LOG.debug(
                    "事项跳过：工作日模式缺 workday_time id=%s",
                    item.id,
                )
        elif item.remind_mode in (REMIND_FIXED, REMIND_BEFORE_DUE):
            due = _due_remind_at(item)
            if due is None:
                LOG.debug(
                    "事项跳过：无 remind_at/due_at id=%s mode=%s",
                    item.id,
                    item.remind_mode,
                )
        else:
            due = _due_remind_at(item)
        if due is None:
            continue
        if not _should_fire_now(due, now):
            continue
        if not items_store.mark_remind_fired(item.id, day):
            continue
        body = item.title
        if item.notes:
            body = f"{item.title}\n{item.notes}"
        notify("事项提醒", body)
        fired.append(item.id)
        LOG.info(
            "事项提醒触发 id=%s title=%s due=%s",
            item.id,
            item.title,
            due.isoformat(sep=" "),
        )
    return fired
