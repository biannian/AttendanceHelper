# Copyright (c) iGroup.
# All rights reserved.
"""
前台使用时长累计。

@author Kai
@date 2026/09/29 15:12
@description 每两秒看一次桌面；锁屏、发呆、桌面记为休息，断档跨天按自然日拆开
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .activity_capture import ActivitySample, sample_activity
from .activity_classify import (
    CAT_REST,
    CAT_SLACK,
    CAT_UNKNOWN,
    CAT_WORK,
    ACTIVE_HOLD_SECONDS,
    REST_APP_KEY,
    REST_DISPLAY_NAME,
    ActivityIdentity,
    classify_foreground,
    clip_delta,
    default_category_for,
    format_usage_duration,
)
from .activity_store import (
    add_usage_batch,
    clear_rule,
    delete_day,
    is_paused_today,
    list_usage,
    load_rules,
    set_paused_today,
    set_rule,
)
from .paths import LOG

# 内存里的秒数隔这么久写一次库
_FLUSH_EVERY_SECONDS = 15.0


@dataclass(frozen=True)
class UsageView:
    """
    界面上的一行使用记录。

    @author Kai
    @date 2026/09/29 15:12
    @description 秒数已含尚未落库的尾巴；归类已套用手动规则
    """

    # 使用记录键
    app_key: str
    # 软件或站点显示名
    display_name: str
    # 这一天的累计秒数
    seconds: int
    # 生效归类
    category: str
    # 是否用户手动标过
    manual: bool


def apply_sample(
    pending: dict[tuple[str, str], float],
    names: dict[str, str],
    *,
    ended_at: datetime,
    delta: float,
    paused: bool,
    sample: ActivitySample,
) -> None:
    """
    把一次采样折算进内存累计，并按自然日拆开。

    @param pending (day, app_key) → 尚未取整落库的秒数
    @param names app_key → 显示名
    @param ended_at 这次采样结束的本地时间
    @param delta 距上次采样的秒数
    @param paused 暂停时不记账
    @param sample 桌面采样；休息样本不会带标题
    @author Kai
    @date 2026/09/29 15:52
    """
    if paused:
        return
    gained = clip_delta(delta)
    if gained <= 0:
        return
    identity = _identity_for_gap(sample, gained)
    _spread(pending, names, ended_at, gained, identity)


def _identity_for_gap(sample: ActivitySample, gained: float) -> ActivityIdentity:
    """
    决定这段间隔记到休息还是当前软件。

    桌面、开始菜单、读不到窗口，以及隔太久才采到的软件，都记休息，避免秒数丢失或记错软件。

    @param sample 桌面采样
    @param gained 可计入的秒数
    @return 使用身份
    @author Kai
    @date 2026/09/29 15:52
    """
    if not sample.rest and gained <= ACTIVE_HOLD_SECONDS:
        identity = classify_foreground(sample.exe, sample.title, sample.url)
        if identity is not None and identity.app_key != REST_APP_KEY:
            return identity
    return ActivityIdentity(REST_APP_KEY, REST_DISPLAY_NAME, CAT_REST)


def _spread(
    pending: dict[tuple[str, str], float],
    names: dict[str, str],
    ended_at: datetime,
    seconds: float,
    identity: ActivityIdentity,
) -> None:
    """
    从采样结束时刻往回摊秒数，跨过零点的部分记到前一天。

    @param pending 未落库秒数
    @param names 显示名
    @param ended_at 间隔结束时间
    @param seconds 要摊的秒数
    @param identity 记到哪一条
    @author Kai
    @date 2026/09/29 15:52
    """
    remaining = float(seconds)
    end = ended_at
    while remaining > 1e-6:
        day_start = datetime.combine(end.date(), datetime.min.time())
        available = (end - day_start).total_seconds()
        if available <= 0:
            end = day_start - timedelta(seconds=1)
            continue
        chunk = min(remaining, available)
        _add(
            pending,
            names,
            end.date().isoformat(),
            identity.app_key,
            identity.display_name,
            chunk,
        )
        remaining -= chunk
        end = day_start


class ActivityTracker:
    """
    托盘进程里的使用时长累计器。

    @author Kai
    @date 2026/09/29 15:12
    @description 由界面定时器调用 tick；退出前 flush
    """

    def __init__(self) -> None:
        """创建空的内存累计。"""
        self._pending: dict[tuple[str, str], float] = {}
        self._names: dict[str, str] = {}
        self._last_mono: float | None = None
        self._last_flush = time.monotonic()

    def tick(self) -> None:
        """
        采样一次并累加。第一次调用只记时刻，避免把启动前的间隔算进去。

        @author Kai
        @date 2026/09/29 15:12
        """
        now = time.monotonic()
        if self._last_mono is None:
            self._last_mono = now
            return
        delta = now - self._last_mono
        self._last_mono = now
        # 暂停时不再读取前台窗口
        if self.is_paused():
            return
        try:
            apply_sample(
                self._pending,
                self._names,
                ended_at=datetime.now(),
                delta=delta,
                paused=False,
                sample=sample_activity(),
            )
        except Exception:
            LOG.exception("使用时长累计失败")
        if now - self._last_flush >= _FLUSH_EVERY_SECONDS:
            self.flush()

    def flush(self) -> None:
        """
        把内存里满 1 秒的部分写入数据库。

        @author Kai
        @date 2026/09/29 15:12
        """
        rows: list[tuple[str, str, str, int]] = []
        for (day, app_key), seconds in list(self._pending.items()):
            whole = int(seconds)
            if whole <= 0:
                continue
            name = self._names.get(app_key, app_key)
            rows.append((day, app_key, name, whole))
            self._pending[(day, app_key)] = seconds - whole
        try:
            add_usage_batch(rows)
        except Exception:
            LOG.exception("使用时长写入失败")
            return
        self._last_flush = time.monotonic()

    def is_paused(self) -> bool:
        """
        今天是否暂停统计。

        @return 暂停中为 True
        @author Kai
        @date 2026/09/29 15:12
        """
        return is_paused_today()

    def set_paused(self, paused: bool) -> None:
        """
        暂停或恢复今天的统计。暂停前先落库，恢复后不把暂停期间补进去。

        @param paused 是否暂停
        @author Kai
        @date 2026/09/29 15:12
        """
        if paused:
            self.flush()
        set_paused_today(paused)
        self._last_mono = None

    def set_category(self, app_key: str, category: str | None) -> None:
        """
        设置或清除手动归类。

        @param app_key 使用记录键
        @param category work/slack/unknown；None 表示恢复默认
        @author Kai
        @date 2026/09/29 15:12
        """
        if category is None:
            clear_rule(app_key)
            return
        set_rule(app_key, category)

    def clear_day(self, day: date) -> None:
        """
        清空某一天的使用记录，含还在内存里的秒数。

        @param day 日期
        @author Kai
        @date 2026/09/29 15:12
        """
        day_s = day.isoformat()
        for key in list(self._pending):
            if key[0] == day_s:
                self._pending.pop(key, None)
        delete_day(day_s)

    def rows_for(self, day: date) -> list[UsageView]:
        """
        某一天的使用行，含尚未落库的秒数。

        @param day 日期
        @return 按时长从长到短
        @author Kai
        @date 2026/09/29 15:12
        """
        day_s = day.isoformat()
        merged: dict[str, list[object]] = {}
        for app_key, display_name, seconds in list_usage(day_s):
            merged[app_key] = [display_name, int(seconds)]
        for (pending_day, app_key), seconds in self._pending.items():
            if pending_day != day_s:
                continue
            whole = int(seconds)
            slot = merged.get(app_key)
            if slot is None:
                if whole <= 0:
                    continue
                merged[app_key] = [self._names.get(app_key, app_key), whole]
                continue
            slot[1] = int(slot[1]) + whole
            if app_key in self._names:
                slot[0] = self._names[app_key]
        rules = load_rules()
        views: list[UsageView] = []
        for app_key, slot in merged.items():
            seconds = int(slot[1])
            if seconds <= 0:
                continue
            views.append(
                UsageView(
                    app_key=app_key,
                    display_name=str(slot[0]),
                    seconds=seconds,
                    category=_effective_category(app_key, rules),
                    manual=app_key in rules and app_key != REST_APP_KEY,
                )
            )
        views.sort(key=lambda row: row.seconds, reverse=True)
        return views

    def totals_for(self, day: date) -> dict[str, int]:
        """
        某一天按归类合计的秒数。

        @param day 日期
        @return work/slack/unknown/rest → 秒
        @author Kai
        @date 2026/09/29 15:12
        """
        totals = {
            CAT_WORK: 0,
            CAT_SLACK: 0,
            CAT_UNKNOWN: 0,
            CAT_REST: 0,
        }
        for row in self.rows_for(day):
            totals[row.category] = totals.get(row.category, 0) + row.seconds
        return totals

    def menu_text(self) -> str:
        """
        托盘菜单只显示累计总时长，分类明细留在详情窗口。

        @return 一行状态文字
        @author Kai
        @date 2026/10/15 14:17
        """
        totals = self.totals_for(date.today())
        paused = "（已暂停）" if self.is_paused() else ""
        return f"今日使用：{format_usage_duration(sum(totals.values()))}{paused}"


def _add(
    pending: dict[tuple[str, str], float],
    names: dict[str, str],
    day: str,
    app_key: str,
    display_name: str,
    seconds: float,
) -> None:
    """
    往内存累计里加一秒数。

    @param pending 未落库秒数
    @param names 显示名
    @param day 日期
    @param app_key 使用记录键
    @param display_name 显示名
    @param seconds 增加的秒数
    @author Kai
    @date 2026/09/29 15:12
    """
    key = (day, app_key)
    pending[key] = pending.get(key, 0.0) + float(seconds)
    names[app_key] = display_name


def _effective_category(app_key: str, rules: dict[str, str]) -> str:
    """
    手动规则优先，否则用内置默认。

    @param app_key 使用记录键
    @param rules 用户规则
    @return 归类
    @author Kai
    @date 2026/09/29 15:12
    """
    if app_key == REST_APP_KEY:
        return CAT_REST
    chosen = rules.get(app_key)
    if chosen in (CAT_WORK, CAT_SLACK, CAT_UNKNOWN):
        return chosen
    return default_category_for(app_key)


# 托盘和 AI 工具共用一个累计器，避免对话读到另一份内存
_SHARED_TRACKER: ActivityTracker | None = None


def get_activity_tracker() -> ActivityTracker:
    """
    返回进程内唯一的使用时长累计器。

    @return 累计器
    @author Kai
    @date 2026/09/29 15:32
    """
    global _SHARED_TRACKER
    if _SHARED_TRACKER is None:
        _SHARED_TRACKER = ActivityTracker()
    return _SHARED_TRACKER
