# Copyright (c) iGroup.
# All rights reserved.
"""
托盘悬浮详情卡：考勤事实、宠物动画与单事件轻互动。

@author Kai
@date 2026/10/15 15:25
@description 看一眼考勤、原地推进小事件；无配置表单和二级面板
"""

from __future__ import annotations

import ctypes
import sys
import time
from datetime import date
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget

from ..attendance import AttendanceSummary
from ..activity_tracker import get_activity_tracker
from ..config import S
from ..display_strategy import (
    FAR_CLOCK_IN,
    FAR_FULL,
    FAR_HIDDEN,
    FAR_TODAY_NORMAL,
    is_always_mode,
    is_quiet_mode,
    normalize_far_display,
    orange_near_threshold,
    show_countdown_ui,
)
from ..items_store import STATUS_OPEN, list_items
from ..relaxation import estimate_relaxation_pay
from ..tray_pet import (
    MOOD_COOL,
    MOOD_TYPE,
    normalize_pet,
    paint_tray_pet,
    pet_animation_controller,
    resolve_pet_mood,
)
from ..util import format_countdown, format_duration, format_hm
from .companion_card import CARD_HEIGHT, CompanionCard
from .woodfish import MeritFloat, WoodfishButton


# 配色（深色卡片）
C_BG = QColor("#0F141B")
C_BG2 = QColor("#152033")
C_BORDER = QColor("#2A3A4D")
C_TEXT = QColor("#F9FAFB")
C_MUTED = QColor("#9CA3AF")
C_WEAK = QColor("#6B7280")
C_GREEN = QColor("#4FD1A5")
C_ORANGE = QColor("#F59E0B")
C_DONE = QColor("#22C55E")
C_RED = QColor("#EF4444")
C_GRAY = QColor("#9CA3AF")
C_TRACK = QColor("#1F2937")
C_TODO_DOT = QColor("#60A5FA")

# 详情卡只预览两条待办，完整列表保留在右键“今日事项”。
_TODO_PREVIEW_MAX = 2
# 主内容区高度：远离下班更紧凑，倒计时与时刻同一行
_DETAIL_MAIN_FAR_H = 88
_DETAIL_MAIN_H = 100
_DETAIL_MAIN_NEAR_H = 116
# 底栏只保留考勤事实；没有事实行时仅保留卡片底部留白。
_DETAIL_FOOTER_FULL_H = 34
_DETAIL_FOOTER_MIN_H = 8
_TODO_PAD_TOP = 8
_TODO_TITLE_H = 16
_TODO_ROW_H = 15
_TODO_PAD_BOTTOM = 6
_DETAIL_WIDTH = 340
# 金额是一行可选的小字，不挤占原有倒计时和进度条。
_SALARY_ROW_H = 20


def _todo_block_height(todo_count: int) -> int:
    """
    待办预览区实际占用高度（含上下内边距）。

    @param todo_count 待办条数；零条时不占空间
    @return 像素高度
    @author Kai
    @date 2026/08/06 11:21
    """
    if todo_count <= 0:
        return 0
    lines = int(todo_count)
    return int(
        _TODO_PAD_TOP + _TODO_TITLE_H + _TODO_ROW_H * lines + _TODO_PAD_BOTTOM
    )


def _detail_card_height(
    todo_count: int,
    *,
    main_h: int,
    footer_h: int,
) -> int:
    """
    按主内容 / 待办 / 底栏计算详情卡高度。

    @param todo_count 展示中的待办行数，允许为零
    @param main_h 主内容区高度
    @param footer_h 底栏高度
    @return 窗口高度
    @author Kai
    @date 2026/08/06 11:21
    """
    return int(10 + main_h + _todo_block_height(todo_count) + footer_h)

LAYOUT_ALERT = "alert"
LAYOUT_FAR = "far"
LAYOUT_NEAR = "near"
LAYOUT_DONE = "done"
LAYOUT_REST = "rest"


def _menu_is_open() -> bool:
    """是否有托盘/普通菜单正在显示。"""
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QMenu) and w.isVisible():
            return True
    return False


class _OutsideClickFilter(QObject):
    """
    拦截应用内鼠标按下：点在详情卡外则关闭。

    @author Kai
    @date 2026/07/23 16:45
    @description 菜单打开时不抢点击
    """

    def __init__(self, popup: "TrayDetailPopup") -> None:
        super().__init__(popup)
        self._popup = popup

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if not self._popup.isVisible():
            return False
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if self._popup._should_ignore_outside():
            return False
        if _menu_is_open():
            return False
        if isinstance(obj, QMenu):
            return False
        if obj is self._popup or (
            isinstance(obj, QWidget) and self._popup.isAncestorOf(obj)
        ):
            return False
        if hasattr(event, "globalPosition"):
            gp = event.globalPosition().toPoint()
        elif hasattr(event, "globalPos"):
            gp = event.globalPos()
        else:
            gp = QCursor.pos()
        if not self._popup.frameGeometry().contains(gp):
            self._popup.dismiss()
        return False


class TrayDetailPopup(QWidget):
    """
    托盘旁悬浮详情卡。

    @author Kai
    @date 2026/08/06 10:32
    @description 左侧大尺寸宠物，右侧状态与考勤事实
    """

    def __init__(self) -> None:
        """
        创建紧凑考勤、宠物和单事件互动区域。

        @author Kai
        @date 2026/10/15 15:25
        """
        super().__init__()
        self.setWindowTitle("考勤详情")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # 左宠右文 + 底部待办预览（高度随内容收缩）。
        self.setFixedSize(
            _DETAIL_WIDTH,
            _detail_card_height(
                0,
                main_h=_DETAIL_MAIN_FAR_H,
                footer_h=_DETAIL_FOOTER_MIN_H,
            ),
        )
        self.setMouseTracking(True)

        self._summary: Optional[AttendanceSummary] = None
        self._non_workday = False
        self._paused = False
        self._layout = LAYOUT_FAR
        self._show_bar = False
        self._show_pet = True

        self._badge = "工作中"
        self._hero = "--:--"
        self._subtitle = "加载中"
        self._fun_line = ""
        self._mood = MOOD_TYPE
        self._progress = 0.0
        self._pct_text = ""
        # 与下班时刻、进度条同时露出的秒级倒计时（空串表示不画）
        self._countdown_text = ""
        self._footer_left = ""
        self._footer_right = ""
        self._accent = C_GREEN
        # 待办预览：标题列表 + 未完成总数
        self._todo_titles: list[str] = []
        self._todo_total = 0

        self._hover_inside = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(450)
        self._hide_timer.timeout.connect(self._try_hide)

        self._ignore_outside_until = 0.0
        self._outside_filter = _OutsideClickFilter(self)
        self._outside_poll = QTimer(self)
        self._outside_poll.setInterval(80)
        self._outside_poll.timeout.connect(self._poll_outside_click)

        # 详情可见时跟随 sprite 帧刷新。
        pet_animation_controller().frame_changed.connect(self._on_pet_frame)
        # 木鱼和功德飘字均为卡片子控件，不创建额外窗口。
        self._woodfish = WoodfishButton(self)
        self._woodfish.knocked.connect(self._on_woodfish_knocked)
        self._merit_float = MeritFloat(self)
        # 金额只在可见期间从共享累计器取真实统计，不外推未记录秒数。
        self._salary_label = QLabel(self)
        self._salary_label.setTextFormat(Qt.TextFormat.PlainText)
        self._salary_label.setStyleSheet("color: #74C9AE; font-size: 11px; background: transparent;")
        self._salary_timer = QTimer(self)
        self._salary_timer.setInterval(1000)
        self._salary_timer.timeout.connect(self._refresh_salary)
        # 单个轻互动原地推进，没有二级窗口或配置控件。
        self._play_panel = CompanionCard(self)
        self._refresh_playground()
        self._sync_card_size()

    def _on_woodfish_knocked(self, today: int, total: int) -> None:
        """
        在宠物旁播放一次功德飘字，真实考勤数据不作任何修改。

        @param today 今日累计敲击次数
        @param total 历史累计敲击次数
        @author Kai
        @date 2026/10/15 16:16
        """
        self._merit_float.pop(QPoint(14, 10))

    def _refresh_salary(self) -> None:
        """
        按当前选中分类的实际累计秒数刷新娱乐估算金额。

        @author Kai
        @date 2026/10/15 16:16
        """
        if not (S.fun_enable and S.fun_salary_enable):
            return
        if S.fun_hourly_rate <= 0:
            self._salary_label.setText("带薪回血：请先在设置填写估算时薪")
            self._salary_label.setToolTip("在设置 → 趣味中填写估算时薪后即可显示金额。")
            return
        totals = get_activity_tracker().totals_for(date.today())
        amount = estimate_relaxation_pay(
            totals, S.fun_hourly_rate, include_slack=S.fun_salary_slack,
            include_rest=S.fun_salary_rest, include_unknown=S.fun_salary_unknown,
        )
        self._salary_label.setText(f"今日带薪回血：¥ {amount:,.2f}")
        categories = "、".join(
            label for label, enabled in (
                ("摸鱼", S.fun_salary_slack), ("休息", S.fun_salary_rest), ("未分类", S.fun_salary_unknown),
            ) if enabled
        )
        self._salary_label.setToolTip(
            f"娱乐估算，不代表工资到账。\n估算时薪：¥ {S.fun_hourly_rate:,.2f} / 小时\n"
            f"计算范围：{categories or '未选择'}\n金额 = 已记录的选中分类秒数 ÷ 3600 × 时薪。\n"
            "休息包括离开电脑或无操作；暂停统计时不会增加新时长。"
        )

    def _refresh_playground(self) -> None:
        """
        同步当前小事件，不触发网络请求。

        @author Kai
        @date 2026/10/15 15:25
        """
        self._play_panel.refresh()

    def _on_pet_frame(self) -> None:
        """
        宠物动画推进一帧时重绘详情卡。

        @author Kai
        @date 2026/08/06 09:32
        """
        if self.isVisible() and self._show_pet:
            self.update()

    def _refresh_todos(self) -> None:
        """
        拉取未完成事项，供详情卡预览（最多 2 条）。

        @author Kai
        @date 2026/08/06 10:46
        """
        try:
            items = list_items(status=STATUS_OPEN)
        except Exception:
            self._todo_titles = []
            self._todo_total = 0
            self._sync_card_size()
            return
        self._todo_total = len(items)
        titles: list[str] = []
        for it in items[:_TODO_PREVIEW_MAX]:
            title = (it.title or "").strip() or "未命名事项"
            titles.append(title)
        self._todo_titles = titles
        self._sync_card_size()

    def _sync_card_size(self) -> None:
        """
        按布局与待办条数同步卡片高度，压掉临近模式白天大片留白。

        @author Kai
        @date 2026/10/15 14:02
        """
        rows = len(self._todo_titles)
        if self._layout == LAYOUT_NEAR and not is_quiet_mode():
            main_h = _DETAIL_MAIN_NEAR_H if self._show_bar else _DETAIL_MAIN_H
        elif self._layout == LAYOUT_FAR:
            # @author Kai @date 2026/10/23 15:47：无倒计时时按宠物占位压缩主区。
            main_h = _DETAIL_MAIN_FAR_H if self._show_pet else 76
        else:
            main_h = _DETAIL_MAIN_H
        footer_h = (
            _DETAIL_FOOTER_FULL_H
            if (self._footer_left or self._footer_right)
            else _DETAIL_FOOTER_MIN_H
        )
        # 把金额行放在考勤主区下方，原来的绘制区域仍保持原高度。
        salary_h = _SALARY_ROW_H if S.fun_enable and S.fun_salary_enable else 0
        self._salary_label.setVisible(bool(salary_h))
        self._salary_label.setGeometry(14, 10 + main_h - 2, _DETAIL_WIDTH - 28, salary_h)
        self._refresh_salary()
        if self.isVisible() and salary_h and not self._salary_timer.isActive():
            self._salary_timer.start()
        elif not self.isVisible() or not salary_h:
            self._salary_timer.stop()
        wood_visible = S.fun_enable and S.fun_pet_enable and S.fun_woodfish_enable and self._show_pet
        self._woodfish.setVisible(wood_visible)
        compact = self._layout == LAYOUT_FAR
        self._woodfish.move(66 if compact else 78, 67 if compact else 79)
        play_h = CARD_HEIGHT if S.fun_enable and S.fun_card_mode != "off" else 0
        self._play_panel.setVisible(bool(play_h))
        self._play_panel.setGeometry(14, 10 + main_h + salary_h, _DETAIL_WIDTH - 28, play_h)
        h = _detail_card_height(rows, main_h=main_h, footer_h=footer_h) + play_h + salary_h
        if self.width() != _DETAIL_WIDTH or self.height() != h:
            self.setFixedSize(_DETAIL_WIDTH, h)

    def show_non_workday(self, *, from_api: bool = False) -> None:
        """展示非工作日状态。"""
        self._non_workday = True
        self._summary = None
        self._layout = LAYOUT_REST
        self._show_bar = False
        self._show_pet = bool(getattr(S, "fun_enable", True) and S.fun_pet_enable)
        self._badge = "休息日"
        self._hero = "今天不用提醒"
        self._subtitle = "非工作日 / 节假日"
        self._fun_line = ""
        self._mood = MOOD_COOL
        self._progress = 0.0
        self._pct_text = ""
        self._countdown_text = ""
        self._footer_left = ""
        self._footer_right = ""
        self._accent = C_GRAY
        self._refresh_todos()
        self.update()

    def update_summary(
        self,
        summary: AttendanceSummary,
        *,
        from_api: bool = False,
        paused: bool = False,
    ) -> None:
        """
        根据摘要刷新卡片。

        @param summary 打卡摘要
        @param from_api 是否刚拉过接口
        @param paused 今日是否暂停提醒
        @author Kai
        @date 2026/08/06 10:42
        """
        self._non_workday = False
        self._paused = paused
        self._summary = summary
        self._rebuild_view(summary)
        self._refresh_todos()
        self.update()

    def _apply_fun_meta(self, summary: AttendanceSummary) -> None:
        """
        根据趣味开关同步宠物情绪，趣味内容由单事件卡片承载。

        @param summary 摘要
        @author Kai
        @date 2026/10/15 14:02
        """
        fun_on = bool(getattr(S, "fun_enable", True))
        self._show_pet = fun_on and bool(getattr(S, "fun_pet_enable", True))
        # 原 AI 短句由轻互动替代；宠物情绪仍跟随考勤。
        self._fun_line = ""
        if fun_on:
            self._mood = resolve_pet_mood(summary)
        else:
            self._fun_line = ""
            self._mood = MOOD_TYPE

    def _rebuild_view(self, summary: AttendanceSummary) -> None:
        """
        按状态与显示模式组装主文案 / 进度 / 配色。

        @param summary 打卡摘要
        @author Kai
        @date 2026/09/21 16:39
        """
        required = max(1, summary.required_seconds or int(S.target_hours * 3600))
        long_ot = max(1, int(S.overtime_remind_minutes or 30))
        req_h = required / 3600
        self._apply_fun_meta(summary)
        self._pct_text = ""
        self._countdown_text = ""
        self._show_bar = False
        self._footer_left = ""
        self._footer_right = ""

        if summary.token_expired:
            self._layout = LAYOUT_ALERT
            self._badge = "登录失效"
            self._hero = "Token 已过期"
            self._subtitle = "请到设置更新 authorization"
            self._accent = C_RED
            return

        if not summary.ok:
            self._layout = LAYOUT_ALERT
            self._badge = "异常"
            self._hero = "接口失败"
            self._subtitle = (summary.error or "拉取失败")[:28]
            self._accent = C_RED
            return

        if not summary.has_clock_in:
            self._layout = LAYOUT_ALERT
            self._badge = "未打卡"
            self._hero = self._fun_line or "还没打上班卡"
            self._subtitle = (
                f"请假 {summary.leave_hours:g}h"
                if summary.leave_hours > 0
                else "未查到今日上班记录"
            )
            self._accent = C_RED
            return

        in_hm = format_hm(summary.in_time)
        target_hm = format_hm(summary.target_time)
        worked = format_duration(summary.worked_seconds)
        self._progress = min(1.0, summary.worked_seconds / required)

        if summary.target_reached:
            self._layout = LAYOUT_DONE
            overtime = max(0, summary.worked_seconds - required)
            over_mins = overtime // 60
            self._badge = "可以走"
            # 宠物说话作主文案；事实放副标题 / 底栏
            if over_mins >= long_ot:
                fact = f"目标 {target_hm}" if target_hm != "--" else "已超时"
            elif over_mins > 0:
                fact = f"已超 {over_mins} 分钟"
            else:
                fact = f"已满 {req_h:g} 小时"
            if not summary.has_clock_out:
                fact = f"{fact} · 记得打下班卡"
            self._hero = self._fun_line or (
                f"已加班 {over_mins} 分钟" if over_mins >= long_ot else "可以下班了"
            )
            self._subtitle = fact
            self._footer_left = f"上班 {in_hm}"
            self._footer_right = (
                f"目标 {target_hm}" if target_hm != "--" else f"已上 {worked}"
            )
            self._accent = C_DONE
            if self._paused:
                self._badge = "已暂停"
                self._accent = C_GRAY
            return

        if show_countdown_ui(summary.remaining_seconds):
            remain_mins = summary.remaining_seconds // 60
            is_near = remain_mins <= orange_near_threshold()
            quiet = is_quiet_mode()
            always = is_always_mode()
            self._layout = LAYOUT_NEAR
            # 始终模式全程显示进度；临近模式仅「快到了」时显示；安静不显示
            self._show_bar = bool((always or is_near) and not quiet)
            self._footer_left = f"上班 {in_hm}"
            leave_bit = (
                f" · 假 {summary.leave_hours:g}h"
                if summary.leave_hours > 0
                else ""
            )
            self._footer_right = f"已上 {worked}{leave_bit}"
            self._pct_text = (
                f"{int(round(self._progress * 100))}%" if self._show_bar else ""
            )
            # 进度条与可走时刻同时出现时，旁路给出秒级倒计时
            if self._show_bar:
                self._countdown_text = (
                    f"还差 {format_countdown(summary.remaining_seconds)}"
                )
            self._badge = "快到了" if is_near else ("陪你" if quiet else "工作中")
            self._accent = C_ORANGE if is_near else C_GREEN
            remain_line = f"还差 {remain_mins} 分钟"
            pet_say = self._fun_line or remain_line
            if quiet:
                # @author Kai @date 2026/10/23 15:47：安静模式采用紧凑布局，可走时刻以小字展示。
                self._layout = LAYOUT_FAR
                self._hero = pet_say
                self._subtitle = (
                    f"可走 {target_hm}" if target_hm != "--" else remain_line
                )
                self._footer_left = ""
                self._footer_right = ""
            elif always:
                # 始终：可走时间突出，宠物说话紧跟一句（不另开人格栏）。
                self._hero = target_hm if target_hm != "--" else "--:--"
                self._subtitle = pet_say
            else:
                # 临近：可走时刻 + 宠物说话。
                self._hero = target_hm if target_hm != "--" else "--:--"
                self._subtitle = pet_say
            if self._paused:
                self._badge = "已暂停"
                self._accent = C_GRAY
            return

        self._apply_far_layout(in_hm, target_hm, worked, req_h, summary)
        # @author Kai @date 2026/10/23 15:47：隐藏倒计时仍保留小字可走时刻，不额外占用底栏。
        if target_hm != "--":
            self._subtitle = f"可走 {target_hm}"
            self._footer_left = ""
            self._footer_right = ""
        if self._paused:
            self._badge = "已暂停"
            self._accent = C_GRAY

    def _apply_far_layout(
        self,
        in_hm: str,
        target_hm: str,
        worked: str,
        req_h: float,
        summary: AttendanceSummary,
    ) -> None:
        """
        远离下班时段：严格按 far_display 控制可见事实信息。

        @param in_hm 上班时刻
        @param target_hm 可走时刻
        @param worked 已上时长文案
        @param req_h 目标工时（小时）
        @param summary 摘要（请假等）
        @author Kai
        @date 2026/08/06 09:32
        """
        far = normalize_far_display(S.far_display)
        self._layout = LAYOUT_FAR
        self._accent = C_GREEN
        # 安静模式徽标更软，强调陪伴而非督工。
        self._badge = "陪你" if is_quiet_mode() else "工作中"
        leave = (
            f"请假 {summary.leave_hours:g}h" if summary.leave_hours > 0 else ""
        )
        # 宠物说话 = 人格短句，只展示一次作主文案；事实放副标题 / 底栏。
        pet_say = "今日考勤"

        if far == FAR_HIDDEN:
            self._hero = pet_say
            self._subtitle = leave or "少打扰模式"
            return

        if far == FAR_TODAY_NORMAL:
            self._hero = "今日已打卡"
            self._subtitle = leave or f"已上 {worked}"
            return

        if far == FAR_CLOCK_IN:
            # 事实并到副标题，减少底栏占用与右侧空洞
            self._hero = f"上班 {in_hm}"
            bits = [f"已上 {worked}"]
            if leave:
                bits.append(leave)
            self._subtitle = " · ".join(bits)
            self._footer_left = ""
            self._footer_right = ""
            return

        if far == FAR_FULL:
            self._hero = f"可走 {target_hm}" if target_hm != "--" else pet_say
            self._subtitle = f"上班 {in_hm} · 已上 {worked}"
            self._footer_left = (
                f"可走 {target_hm}" if target_hm != "--" else f"目标 {req_h:g}h"
            )
            self._footer_right = leave
            return

        self._hero = pet_say
        self._subtitle = leave or f"已上 {worked}"

    def _pos_for_tray_icon(self, icon_geo: QRect) -> QPoint:
        """
        按托盘图标贴任务栏一侧定位，避免提醒触发时跟鼠标跑到屏幕中间。

        @param icon_geo 托盘图标矩形；无效时落在主屏工作区贴任务栏角
        @return 详情卡左上角全局坐标
        @author Kai
        @date 2026/08/31 17:45
        """
        width = self.width()
        height = self.height()
        gap = 8
        valid = (
            icon_geo.isValid()
            and icon_geo.width() > 0
            and icon_geo.height() > 0
        )
        if valid:
            screen = QGuiApplication.screenAt(icon_geo.center())
        else:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QPoint(80, 80)
        avail = screen.availableGeometry()
        full = screen.geometry()

        def _clamp(x: int, y: int) -> QPoint:
            x = max(avail.left() + gap, min(x, avail.right() - width - gap))
            y = max(avail.top() + gap, min(y, avail.bottom() - height - gap))
            return QPoint(x, y)

        if not valid:
            return _clamp(avail.right() - width - gap, avail.bottom() - height - gap)

        dist = {
            "bottom": full.bottom() - icon_geo.bottom(),
            "top": icon_geo.top() - full.top(),
            "right": full.right() - icon_geo.right(),
            "left": icon_geo.left() - full.left(),
        }
        edge = min(dist, key=dist.get)
        if edge == "bottom":
            x = icon_geo.center().x() - width // 2
            y = icon_geo.top() - height - gap
        elif edge == "top":
            x = icon_geo.center().x() - width // 2
            y = icon_geo.bottom() + gap
        elif edge == "right":
            x = icon_geo.left() - width - gap
            y = icon_geo.center().y() - height // 2
        else:
            x = icon_geo.right() + gap
            y = icon_geo.center().y() - height // 2
        return _clamp(x, y)

    def _present_at(self, pos: QPoint) -> None:
        """
        把详情卡放到指定坐标并显示。

        @param pos 左上角全局坐标
        @author Kai
        @date 2026/08/31 17:45
        """
        self._hide_timer.stop()
        self.move(pos)
        self._ignore_outside_until = time.time() + 0.35
        self.show()
        self.raise_()
        self._install_outside_watch()

    def show_at_tray(self, icon_geo: QRect) -> None:
        """
        贴着托盘图标弹出详情卡。

        @param icon_geo QSystemTrayIcon.geometry()
        @author Kai
        @date 2026/08/31 17:45
        """
        # 打开时再刷一次待办，避免事项窗口改完后详情仍旧。
        self._refresh_todos()
        self._refresh_playground()
        self._present_at(self._pos_for_tray_icon(icon_geo))

    def show_near(self, global_pos: QPoint) -> None:
        """兼容旧接口：按点估算，内部仍按托盘矩形逻辑夹到工作区。"""
        self.show_at_tray(QRect(global_pos.x(), global_pos.y(), 1, 1))

    def showEvent(self, event) -> None:  # noqa: N802
        """
        显示时同步金额与功德，启动可见期间的金额刷新。

        @param event Qt 显示事件
        @author Kai
        @date 2026/10/15 16:16
        """
        self._woodfish.refresh_count()
        self._refresh_salary()
        if S.fun_enable and S.fun_salary_enable:
            self._salary_timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        """
        隐藏时停止金额刷新和飘字，拆除外部点击监听。

        @param event Qt 隐藏事件
        @author Kai
        @date 2026/10/15 16:16
        """
        self._remove_outside_watch()
        self._salary_timer.stop()
        self._merit_float.stop()
        super().hideEvent(event)

    def _install_outside_watch(self) -> None:
        """监听应用内点击 + 轮询系统级点击。"""
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._outside_filter)
        if not self._outside_poll.isActive():
            self._outside_poll.start()

    def _remove_outside_watch(self) -> None:
        """停止外部点击监听。"""
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._outside_filter)
        self._outside_poll.stop()

    def dismiss(self) -> None:
        """立刻隐藏详情。"""
        self._hide_timer.stop()
        self.hide()

    def _should_ignore_outside(self) -> bool:
        """刚打开时忽略外部点击。"""
        return time.time() < self._ignore_outside_until

    def _cursor_outside(self) -> bool:
        """光标是否在弹窗外。"""
        return not self.frameGeometry().contains(QCursor.pos())

    def _poll_outside_click(self) -> None:
        """轮询鼠标左键：点在弹窗外则关闭。"""
        if not self.isVisible() or self._should_ignore_outside():
            return
        if _menu_is_open():
            return
        if not self._cursor_outside():
            return
        pressed = False
        if sys.platform == "win32":
            pressed = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        else:
            pressed = bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
        if pressed:
            self.dismiss()

    def schedule_hide(self) -> None:
        """鼠标离开后延迟隐藏。"""
        self._hide_timer.start()

    def cancel_hide(self) -> None:
        """取消隐藏。"""
        self._hide_timer.stop()

    def _try_hide(self) -> None:
        if not self._hover_inside:
            self.dismiss()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover_inside = True
        self.cancel_hide()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_inside = False
        self.schedule_hide()
        super().leaveEvent(event)

    def _draw_wrapped_text(
        self,
        painter: QPainter,
        rect: QRectF,
        text: str,
        *,
        max_lines: int = 3,
    ) -> float:
        """
        在矩形内绘制自动换行文本，返回实际占用高度。

        中文无空格时用 WrapAnywhere，避免单行冲出卡片。

        @param painter 画笔（字体/颜色已设好）
        @param rect 可用区域
        @param text 文案
        @param max_lines 最多行数
        @return 绘制高度
        @author Kai
        @date 2026/08/06 10:40
        """
        content = (text or "").strip()
        if not content or rect.width() <= 1 or rect.height() <= 1:
            return 0.0
        flags = int(
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap
        )
        wrap_anywhere = getattr(Qt.TextFlag, "TextWrapAnywhere", None)
        # 中文短句优先按词/字宽换行；WrapAnywhere 容易把半句甩到下一行，右侧留白难看
        use_anywhere = wrap_anywhere is not None and len(content) > 18
        if use_anywhere:
            flags |= int(wrap_anywhere)

        metrics = painter.fontMetrics()
        line_h = float(max(1, metrics.lineSpacing()))
        max_h = min(float(rect.height()), line_h * max_lines + 2.0)
        draw_rect = QRectF(rect.x(), rect.y(), rect.width(), max_h)
        bounds = painter.boundingRect(draw_rect, flags, content)
        used_h = min(max_h, max(line_h, float(bounds.height()) + 2.0))
        clip = QRectF(rect.x(), rect.y(), rect.width(), used_h)
        painter.save()
        painter.setClipRect(clip)
        painter.drawText(clip, flags, content)
        painter.restore()
        return used_h

    def paintEvent(self, event) -> None:  # noqa: N802
        """
        绘制详情卡：紧凑主区 + 待办 + 底栏；倒计时贴在可走时刻右侧。

        @param event 绘制事件
        @author Kai
        @date 2026/09/21 16:50
        """
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card = QRectF(4, 4, self.width() - 8, self.height() - 8)
        path = QPainterPath()
        path.addRoundedRect(card, 16, 16)
        grad = QLinearGradient(card.topLeft(), card.bottomRight())
        grad.setColorAt(0.0, C_BG)
        grad.setColorAt(1.0, C_BG2)
        painter.fillPath(path, grad)
        painter.setPen(QPen(C_BORDER, 1))
        painter.drawPath(path)

        strip = QRectF(card.x(), card.y() + 16, 3, card.height() - 32)
        strip_path = QPainterPath()
        strip_path.addRoundedRect(strip, 2, 2)
        painter.fillPath(strip_path, self._accent)

        badge = QRectF(self.width() - 80, 12, 64, 20)
        self._paint_badge(painter, badge)

        # 临近白天（FAR）用更小宠物，把主内容区压紧
        compact = self._layout == LAYOUT_FAR
        pet_size = 72.0 if compact else 84.0
        pad = 14.0
        todo_line_count = len(self._todo_titles)
        todo_block_h = float(_todo_block_height(todo_line_count))
        footer_h = float(
            _DETAIL_FOOTER_FULL_H
            if (self._footer_left or self._footer_right)
            else _DETAIL_FOOTER_MIN_H
        )
        # 自下而上：底栏 → 待办 → 主内容
        footer_top = float(self.height()) - footer_h
        todo_top = footer_top - todo_block_h
        play_h = CARD_HEIGHT if S.fun_enable and S.fun_card_mode != "off" else 0
        salary_h = _SALARY_ROW_H if S.fun_enable and S.fun_salary_enable else 0
        content_bottom = todo_top - play_h - salary_h - 2.0

        text_left = pad + 2
        text_top = 34.0

        if self._show_pet:
            pet_x = 12.0
            pet_y = 20.0
            pet_box = QRectF(pet_x, pet_y, pet_size, pet_size)
            stage = QRectF(pet_x - 2, pet_y - 2, pet_size + 4, pet_size + 4)
            stage_path = QPainterPath()
            stage_path.addRoundedRect(stage, 14, 14)
            stage_bg = QColor("#0B1220")
            stage_bg.setAlpha(120)
            painter.fillPath(stage_path, stage_bg)
            paint_tray_pet(
                painter,
                pet_box,
                pet=normalize_pet(getattr(S, "fun_pet", "shiba")),
                mood=self._mood,
            )
            text_left = pet_x + pet_size + 10.0
            text_top = 32.0

        text_right = float(self.width()) - pad
        text_width = max(72.0, text_right - text_left)
        text_max_bottom = content_bottom - 2.0

        hero = self._hero or ""
        countdown = self._countdown_text or ""
        if self._layout == LAYOUT_NEAR and len(hero) <= 8:
            hero_size = 24
        elif len(hero) > 16:
            hero_size = 11
        elif self._layout == LAYOUT_FAR:
            hero_size = 12
        else:
            hero_size = 14
        hero_font = QFont("Microsoft YaHei UI", hero_size)
        hero_font.setBold(True)
        painter.setFont(hero_font)
        painter.setPen(C_TEXT)
        hero_max_h = min(52.0, max(18.0, text_max_bottom - text_top))
        hero_metrics = painter.fontMetrics()
        # 时刻右侧留给「还差 H:MM:SS」，倒计时紧跟数字而不是另起一行
        hero_w = float(hero_metrics.horizontalAdvance(hero)) if hero else 0.0
        hero_line_h = float(max(hero_metrics.height(), 22))
        hero_box_w = text_width
        if countdown:
            hero_box_w = min(text_width, max(hero_w + 4.0, 56.0))
        hero_h = self._draw_wrapped_text(
            painter,
            QRectF(text_left, text_top, hero_box_w, hero_max_h),
            hero,
            max_lines=2 if compact or hero_size >= 14 else 3,
        )
        if countdown:
            cd_x = text_left + hero_box_w + 8.0
            cd_w = max(48.0, text_right - cd_x)
            painter.setPen(self._accent)
            painter.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(cd_x, text_top, cd_w, max(hero_line_h, min(hero_h, 32.0))),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                countdown,
            )

        y = text_top + hero_h + 4.0
        if self._subtitle and y < text_max_bottom - 14:
            sub_is_pet = bool(
                self._fun_line
                and self._subtitle
                and self._fun_line in self._subtitle
            )
            painter.setPen(self._accent if sub_is_pet else C_MUTED)
            painter.setFont(
                QFont(
                    "Microsoft YaHei UI",
                    9,
                    QFont.Weight.DemiBold if sub_is_pet else QFont.Weight.Normal,
                )
            )
            sub_h = self._draw_wrapped_text(
                painter,
                QRectF(text_left, y, text_width, text_max_bottom - y),
                self._subtitle,
                max_lines=2,
            )
            y += sub_h + 6.0

        if self._show_bar and y + 14 < text_max_bottom:
            bar_w = max(64.0, text_width - 42)
            bar = QRectF(text_left, y + 1, bar_w, 8)
            self._paint_bar(painter, bar, self._progress, self._accent)
            painter.setPen(C_MUTED)
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(bar.right() + 4, y - 2, 36, 14),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self._pct_text,
            )

        # 没有待办时整段收起，不用“暂无事项”占据卡片空间。
        self._paint_todos(painter, pad, todo_top)

        # 底栏仅绘制考勤事实，避免移除更新时间后留下空分隔栏。
        if not (self._footer_left or self._footer_right):
            return
        painter.setPen(QPen(C_BORDER))
        painter.drawLine(
            int(pad),
            int(footer_top),
            int(self.width() - pad),
            int(footer_top),
        )
        footer_y = footer_top + 8.0
        if self._footer_left or self._footer_right:
            painter.setPen(C_MUTED)
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            half = (self.width() - pad * 2) / 2.0 - 4.0
            left_rect = QRectF(pad, footer_y, half, 16)
            elided_l = painter.fontMetrics().elidedText(
                self._footer_left or "",
                Qt.TextElideMode.ElideRight,
                int(left_rect.width()),
            )
            painter.drawText(
                left_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                elided_l,
            )
            right_rect = QRectF(self.width() - pad - half, footer_y, half, 16)
            elided_r = painter.fontMetrics().elidedText(
                self._footer_right or "",
                Qt.TextElideMode.ElideRight,
                int(right_rect.width()),
            )
            painter.drawText(
                right_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                elided_r,
            )

    def _paint_todos(self, painter: QPainter, pad: float, top: float) -> None:
        """
        仅在存在待办时绘制紧凑的两条预览。

        @param painter 卡片画笔
        @param pad 水平边距
        @param top 待办区顶部坐标
        @author Kai
        @date 2026/10/15 15:25
        """
        if not self._todo_titles:
            return
        painter.setPen(QPen(C_BORDER))
        painter.drawLine(int(pad), int(top), int(self.width() - pad), int(top))
        y = top + _TODO_PAD_TOP
        painter.setPen(C_MUTED)
        painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(pad, y, self.width() - pad * 2, _TODO_TITLE_H),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"待办 · {self._todo_total}",
        )
        y += _TODO_TITLE_H
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        for index, title in enumerate(self._todo_titles):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(C_TODO_DOT)
            painter.drawEllipse(QRectF(pad + 2, y + 5, 6, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(C_TEXT)
            if index == len(self._todo_titles) - 1 and self._todo_total > len(self._todo_titles):
                title = f"{title} · +{self._todo_total - len(self._todo_titles)}"
            text = painter.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideRight, int(self.width() - pad * 2 - 14),
            )
            painter.drawText(
                QRectF(pad + 14, y, self.width() - pad * 2 - 14, _TODO_ROW_H),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text,
            )
            y += _TODO_ROW_H

    def _paint_badge(self, painter: QPainter, rect: QRectF) -> None:
        """
        右上角状态徽标。

        @param painter 画笔
        @param rect 徽标区域
        @author Kai
        @date 2026/08/06 09:32
        """
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        bg = QColor(self._accent)
        bg.setAlpha(40)
        painter.fillPath(path, bg)
        painter.setPen(QPen(self._accent, 1))
        painter.drawPath(path)
        painter.setPen(self._accent)
        painter.setFont(QFont("Microsoft YaHei UI", 8, QFont.Weight.DemiBold))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._badge)

    def _paint_bar(
        self,
        painter: QPainter,
        rect: QRectF,
        progress: float,
        color: QColor,
    ) -> None:
        """
        横向进度条。

        @param painter 画笔
        @param rect 轨道区域
        @param progress 0~1 进度
        @param color 填充色
        @author Kai
        @date 2026/08/06 09:32
        """
        track = QPainterPath()
        track.addRoundedRect(rect, 4, 4)
        painter.fillPath(track, C_TRACK)
        p = max(0.0, min(1.0, float(progress)))
        if p <= 0.001:
            return
        fill = QRectF(rect.x(), rect.y(), rect.width() * p, rect.height())
        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill, 4, 4)
        painter.fillPath(fill_path, color)
