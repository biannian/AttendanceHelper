# Copyright (c) iGroup China.
# All rights reserved.
"""
显示策略：预设映射与倒计时可见性判断。

@author Kai
@date 2026/08/31 17:15
@description 托盘三档显示模式 + 临近阈值；远离下班时弱化倒计时 UI
"""

from __future__ import annotations

from typing import Any

# 注意：不要在模块顶层 import config.S，避免与 config.reload_settings 循环依赖。


# 显示模式预设
MODE_QUIET = "quiet"
MODE_NEAR = "near"
MODE_ALWAYS = "always"
DISPLAY_MODES = (MODE_QUIET, MODE_NEAR, MODE_ALWAYS)

# 远离下班时详情样式
FAR_HIDDEN = "hidden"
FAR_TODAY_NORMAL = "today_normal"
FAR_CLOCK_IN = "clock_in"
FAR_FULL = "full"
FAR_DISPLAYS = (FAR_HIDDEN, FAR_TODAY_NORMAL, FAR_CLOCK_IN, FAR_FULL)

# 预设只绑定远离样式；倒计时是否露出由 display_mode + near_minutes 决定
PRESET_FIELDS: dict[str, dict[str, Any]] = {
    # 安静：远离时隐藏工时事实；临近阈值内才露倒计时；不主动弹详情。
    MODE_QUIET: {
        "far_display": FAR_HIDDEN,
    },
    # 临近下班：远离时仍显示上班时间；临近阈值内进入倒计时 UI。
    MODE_NEAR: {
        "far_display": FAR_CLOCK_IN,
    },
    MODE_ALWAYS: {
        "far_display": FAR_FULL,
    },
}

MODE_LABELS: dict[str, str] = {
    MODE_QUIET: "安静模式",
    MODE_NEAR: "临近下班显示",
    MODE_ALWAYS: "始终显示倒计时",
}

MODE_HINTS: dict[str, str] = {
    MODE_QUIET: "少打扰：详情以宠物说话为主，剩余 ≤ 临近阈值才露倒计时",
    MODE_NEAR: "平衡：平时显示上班时间，剩余 ≤ 临近阈值时突出可走倒计时",
    MODE_ALWAYS: "全程可见可走时间、进度条与完整信息，不受临近阈值限制",
}


def normalize_display_mode(raw: str) -> str:
    """
    规范化显示模式。

    @param raw 原始值
    @return quiet / near / always
    @author Kai
    @date 2026/08/31 17:15
    """
    mode = (raw or "").strip().lower()
    if mode in DISPLAY_MODES:
        return mode
    return MODE_NEAR


def normalize_far_display(raw: str) -> str:
    """
    规范化远离下班显示样式。

    @param raw 原始值
    @return far_display 枚举
    @author Kai
    @date 2026/08/31 17:15
    """
    value = (raw or "").strip().lower()
    if value in FAR_DISPLAYS:
        return value
    return FAR_TODAY_NORMAL


def apply_display_preset(mode: str) -> dict[str, Any]:
    """
    按预设展开要写入 config 的字段。

    @param mode 预设名
    @return 含 display_mode + 远离样式的字典
    @author Kai
    @date 2026/08/31 17:15
    """
    m = normalize_display_mode(mode)
    fields = dict(PRESET_FIELDS[m])
    fields["display_mode"] = m
    return fields


def infer_display_mode(far_display: str) -> str:
    """
    由远离样式反推最近预设（仅旧配置缺 display_mode 时使用）。

    @param far_display 远离样式
    @return 预设名
    @author Kai
    @date 2026/08/31 17:15
    """
    fd = normalize_far_display(far_display)
    if fd == FAR_FULL:
        return MODE_ALWAYS
    if fd == FAR_HIDDEN:
        return MODE_QUIET
    return MODE_NEAR


def is_quiet_mode() -> bool:
    """
    当前是否为安静显示模式。

    @return True 表示安静模式
    @author Kai
    @date 2026/08/31 17:15
    """
    from .config import S

    return normalize_display_mode(getattr(S, "display_mode", MODE_NEAR)) == MODE_QUIET


def is_always_mode() -> bool:
    """
    当前是否为始终显示倒计时模式。

    @return True 表示始终模式
    @author Kai
    @date 2026/08/31 17:15
    """
    from .config import S

    return normalize_display_mode(getattr(S, "display_mode", MODE_NEAR)) == MODE_ALWAYS


def near_threshold_minutes() -> int:
    """
    临近下班阈值（分钟）：倒计时露出与橙色标示共用。

    @return 分钟阈值，至少 1
    @author Kai
    @date 2026/08/31 17:15
    """
    from .config import S

    return max(1, int(getattr(S, "near_minutes", 20) or 20))


def show_countdown_ui(remaining_seconds: int) -> bool:
    """
    是否应展示倒计时视觉（大号可走时间 / 还差 N 分钟）。

    始终模式全程显示；其余模式仅在剩余 ≤ 临近阈值时显示。

    @param remaining_seconds 剩余秒数
    @return True 表示进入临近倒计时 UI
    @author Kai
    @date 2026/08/31 17:15
    """
    if is_always_mode():
        return True
    return max(0, int(remaining_seconds)) <= near_threshold_minutes() * 60


def orange_near_threshold() -> int:
    """
    托盘橙色「快到了」色调阈值（分钟）。

    与倒计时露出共用临近阈值，避免两套互不生效的时机配置。

    @return 分钟阈值
    @author Kai
    @date 2026/08/31 17:15
    """
    return near_threshold_minutes()


def should_auto_popup_detail() -> bool:
    """
    提醒触发时是否主动弹出详情卡。

    安静模式：不主动弹详情（改走应用内提醒卡片）；其它模式：临近节点仍可弹。

    @return 是否允许主动弹详情
    @author Kai
    @date 2026/08/31 17:15
    """
    return not is_quiet_mode()
