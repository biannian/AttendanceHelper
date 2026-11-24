# Copyright (c) iGroup China.
# All rights reserved.
"""
分级下班提醒文案与触发判断。

@author Kai
@date 2026/07/23 17:40
@description 60/30/20/5/0 分钟节点 + 加班提醒；按秒阈值，避免提前近 1 分钟误触发
"""

from __future__ import annotations

from typing import Callable

from .attendance import AttendanceSummary
from .cache_store import cache_mark_once
from .config import S
from .paths import LOG
from .util import format_hm


# 节点文案（标题, 正文模板，{mins} 可替换）
NODE_COPY: dict[int, tuple[str, str]] = {
    60: ("还差约 1 小时", "还差 {mins} 分钟可以走，普通提醒"),
    30: ("准备收尾", "还差 {mins} 分钟，可以开始收尾了"),
    20: ("快可以走了", "还差 {mins} 分钟，快可以走了"),
    5: ("准备下班", "还差 {mins} 分钟，准备下班"),
    0: ("可以走了", "应出勤已满，可以下班了"),
}


def remind_nodes() -> list[int]:
    """
    返回排序后的提醒节点（大→小）。

    @return 分钟列表
    @author Kai
    @date 2026/07/23 17:05
    """
    raw = list(S.remind_nodes_minutes or [60, 30, 20, 5, 0])
    return sorted({int(x) for x in raw}, reverse=True)


def node_message(node: int, remain_mins: int, *, target_hm: str = "") -> tuple[str, str]:
    """
    取节点提醒文案（尊重趣味人格）。

    @param node 节点分钟
    @param remain_mins 当前剩余分钟（向上取整展示）
    @param target_hm 预计可走时间
    @return (标题, 正文)
    @author Kai
    @date 2026/08/05 15:03
    """
    if getattr(S, "fun_enable", True):
        from .fun_copy import persona_remind_message

        return persona_remind_message(node, remain_mins, target_hm=target_hm)
    title, body = NODE_COPY.get(node, (f"还差 {node} 分钟", "还差 {mins} 分钟可走"))
    return title, body.format(mins=max(0, remain_mins))


def _display_remain_mins(remaining_seconds: int) -> int:
    """
    剩余秒数 → 展示用分钟（向上取整，还差 4:01 显示 5 分钟）。

    @param remaining_seconds 剩余秒
    @return 分钟
    @author Kai
    @date 2026/07/23 17:40
    """
    sec = max(0, int(remaining_seconds))
    if sec <= 0:
        return 0
    return (sec + 59) // 60


def evaluate_reminders(
    summary: AttendanceSummary,
    date_str: str,
    notify: Callable[[str, str], None],
) -> list[int | str]:
    """
    按节点触发提醒（每个节点每天最多一次）。

    阈值按「剩余秒 ≤ 节点×60」判断，避免 //60 在还差 5:59 就提前触发 5 分钟节点。

    @param summary 本地秒刷后的摘要
    @param date_str 日期键
    @param notify 回调 (title, msg)
    @return 本次实际弹出的节点（int 分钟或 \"overtime\"）
    @author Kai
    @date 2026/07/23 17:40
    """
    fired: list[int | str] = []
    if not summary.ok or not summary.has_clock_in:
        return fired

    required = max(0, summary.required_seconds)
    if summary.target_reached:
        key0 = f"remind-0-{date_str}"
        if 0 in remind_nodes() and cache_mark_once(key0):
            title, body = node_message(
                0, 0, target_hm=format_hm(summary.target_time)
            )
            req_h = required / 3600 if required else S.target_hours
            notify(title, f"{body}（应出勤 {req_h:g}h）")
            fired.append(0)
            LOG.info("提醒触发 node=0 date=%s", date_str)

        overtime_mins = max(0, (summary.worked_seconds - required) // 60)
        ov = int(S.overtime_remind_minutes)
        if ov > 0 and overtime_mins >= ov:
            key_ov = f"remind-overtime-{ov}-{date_str}"
            if cache_mark_once(key_ov):
                notify(
                    f"已加班 {ov} 分钟",
                    f"已超过可走时间 {overtime_mins} 分钟，注意休息",
                )
                fired.append("overtime")
                LOG.info("提醒触发 overtime=%s date=%s", ov, date_str)
        return fired

    remaining_seconds = max(0, int(summary.remaining_seconds))
    remain_mins = _display_remain_mins(remaining_seconds)
    positive_nodes = [n for n in remind_nodes() if n > 0]
    # 按秒阈值：还差 ≤ N 分钟整才进入该节点（例如 5 分钟 = remaining ≤ 300）
    applicable = [n for n in positive_nodes if remaining_seconds <= n * 60]
    if not applicable:
        return fired

    # 只弹「当前最紧」节点；更大的节点静默标记，避免晚启动连弹
    tight = min(applicable)
    for n in applicable:
        key = f"remind-{n}-{date_str}"
        if n == tight:
            if cache_mark_once(key):
                title, body = node_message(
                    n,
                    remain_mins,
                    target_hm=format_hm(summary.target_time),
                )
                notify(title, body)
                fired.append(n)
                LOG.info(
                    "提醒触发 node=%s remain_sec=%s remain_mins=%s date=%s",
                    n,
                    remaining_seconds,
                    remain_mins,
                    date_str,
                )
        else:
            cache_mark_once(key)
    return fired
