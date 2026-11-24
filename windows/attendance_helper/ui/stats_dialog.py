# Copyright (c) iGroup China.
# All rights reserved.
"""
周 / 月打卡统计对话框：按日查接口，日历表格展示。

@author Kai
    @date 2026/09/01 10:20
    @description 周一行、月整月；顶部平均汇总；可刷新历史缓存
"""

from __future__ import annotations

from calendar import monthcalendar
from datetime import date, timedelta
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..attendance import AttendanceSummary, fetch_attendance_range
from ..holiday import DayHolidayInfo, prefetch_holidays
from ..paths import LOG
from ..util import format_duration, format_hm

WEEKDAY_HEADERS = ["一", "二", "三", "四", "五", "六", "日"]

# 暗色日历配色
C_TODAY_BG = QColor("#1A3D32")
C_EMPTY = QColor("#151A22")
C_DAY_BG = QColor("#1C2430")
C_WEEKEND_BG = QColor("#1A2030")
C_HOLIDAY_BG = QColor("#2A1C24")
C_MAKEUP_BG = QColor("#2A241C")
C_MUTED = QColor("#8B95A5")
C_OK = QColor("#4ADE80")
C_MISS = QColor("#FBBF24")
C_ERR = QColor("#F87171")
C_FUTURE = QColor("#6B7280")
C_HOLIDAY_FG = QColor("#FB7185")
C_WEEKEND_FG = QColor("#94A3B8")
C_VALID = QColor("#34D399")
C_INVALID = QColor("#FB7185")
C_WARN = QColor("#FBBF24")

# 对话框整体暗色样式
DIALOG_QSS = """
QDialog {
    background-color: #0F141B;
    color: #E5E7EB;
}
QLabel {
    color: #E5E7EB;
}
QPushButton {
    background-color: #243044;
    color: #E5E7EB;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: #2E3C54;
}
QPushButton:disabled {
    color: #6B7280;
    background-color: #1A2230;
}
QDialogButtonBox QPushButton {
    min-width: 72px;
}
QFrame#metricsFrame {
    background-color: #161D28;
    border: 1px solid #2A3548;
    border-radius: 8px;
}
QTableWidget {
    background-color: #121820;
    gridline-color: #2A3548;
    border: 1px solid #2A3548;
    outline: none;
    color: #E5E7EB;
}
QHeaderView::section {
    background-color: #1A2332;
    color: #CBD5E1;
    border: none;
    border-right: 1px solid #2A3548;
    border-bottom: 1px solid #2A3548;
    padding: 4px;
    font-weight: 600;
}
QTableWidget::item {
    color: #E5E7EB;
}
"""


def week_days(anchor: Optional[date] = None) -> list[date]:
    """
    本周周一至周日。

    @param anchor 锚点日
    @return 7 天
    @author Kai
    @date 2026/07/23 17:15
    """
    today = anchor or date.today()
    start = today - timedelta(days=today.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def month_days(anchor: Optional[date] = None) -> list[date]:
    """
    本月全部自然日。

    @param anchor 锚点日
    @return 当月日期列表
    @author Kai
    @date 2026/07/23 17:15
    """
    today = anchor or date.today()
    start = today.replace(day=1)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    days: list[date] = []
    cur = start
    while cur < nxt:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _avg_hm(values: list[int]) -> str:
    """分钟列表 → 平均 HH:MM。"""
    if not values:
        return "--"
    avg = int(round(sum(values) / len(values)))
    return f"{avg // 60:02d}:{avg % 60:02d}"


def _hm_to_minutes(text: str) -> Optional[int]:
    """HH:MM → 分钟。"""
    try:
        h, m = text.split(":")
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return None


def stats_worked_seconds(
    summary: AttendanceSummary,
    today: Optional[date] = None,
) -> Optional[int]:
    """
    统计用工时秒数：有下班卡按打卡时段；今日无下班卡按进行中；历史无下班卡不计。

    @param summary 日摘要
    @param today 参照「今天」（用于区分历史日）
    @return 秒数或 None（历史日未下班则未知）
    @author Kai
    @date 2026/08/03 08:50
    """
    if not summary.ok or not summary.has_clock_in or summary.in_time is None:
        return None
    if summary.latest_out_time is not None:
        return max(
            0, int((summary.latest_out_time - summary.in_time).total_seconds())
        )
    today = today or date.today()
    try:
        day_obj = date.fromisoformat(str(summary.date)[:10])
    except ValueError:
        day_obj = None
    # 历史日无下班卡：实际工时未知，不参与展示与均值
    if day_obj is not None and day_obj < today:
        return None
    return max(0, int(summary.worked_seconds))


def format_work_hours(seconds: int) -> str:
    """
    工时展示：优先 X.Xh，整点省略小数。

    @param seconds 秒数
    @return 如 8.5h / 9h
    @author Kai
    @date 2026/07/23 17:55
    """
    sec = max(0, int(seconds))
    hours = sec / 3600
    if abs(hours - round(hours)) < 0.05:
        return f"{int(round(hours))}h"
    return f"{hours:.1f}h"


def _avg_work_hours(values: list[int]) -> str:
    """工时秒列表 → 平均 X.Xh。"""
    if not values:
        return "--"
    avg = int(round(sum(values) / len(values)))
    return format_work_hours(avg)


def build_average_metrics(
    kind: str,
    records: dict[str, AttendanceSummary],
) -> list[tuple[str, str]]:
    """
    生成横向汇总指标 (标签, 数值)。

    @param kind week | month
    @param records 日摘要表
    @return 指标列表
    @author Kai
    @date 2026/07/23 17:55
    """
    punched: list[AttendanceSummary] = [
        s
        for s in records.values()
        if s.ok and s.has_clock_in and s.error != "FUTURE"
    ]

    def hm(m: Optional[int]) -> str:
        if m is None:
            return "--"
        return f"{m // 60:02d}:{m % 60:02d}"

    if not punched:
        scope = "本周" if kind == "week" else "当月"
        return [
            ("平均上班", "--"),
            ("最早上班", "--"),
            ("最晚上班", "--"),
            ("平均可走", "--"),
            ("平均下班", "--"),
            ("平均工时", "--"),
            ("有效考勤", "--"),
            (f"{scope}已达标", "--"),
            ("有打卡", "--"),
        ]

    in_mins = [
        m
        for m in (_hm_to_minutes(format_hm(s.in_time)) for s in punched)
        if m is not None
    ]
    leave_mins = [
        m
        for m in (_hm_to_minutes(format_hm(s.target_time)) for s in punched)
        if m is not None
    ]
    out_mins = [
        m
        for m in (_hm_to_minutes(format_hm(s.latest_out_time)) for s in punched)
        if m is not None
    ]
    work_secs = [
        w for w in (stats_worked_seconds(s) for s in punched) if w is not None
    ]
    valid_days = sum(1 for s in punched if s.is_valid_attendance)
    reached = sum(1 for s in punched if s.target_reached)
    earliest = min(in_mins) if in_mins else None
    latest = max(in_mins) if in_mins else None
    scope = "本周" if kind == "week" else "当月"
    return [
        ("平均上班", _avg_hm(in_mins)),
        ("最早上班", hm(earliest)),
        ("最晚上班", hm(latest)),
        ("平均可走", _avg_hm(leave_mins)),
        ("平均下班", _avg_hm(out_mins)),
        ("平均工时", _avg_work_hours(work_secs)),
        ("有效考勤", f"{valid_days} 天"),
        (f"{scope}已达标", f"{reached} 天"),
        ("有打卡", f"{len(punched)} 天"),
    ]


def cell_text(
    day: date,
    summary: Optional[AttendanceSummary],
    today: date,
    holiday: Optional[DayHolidayInfo] = None,
) -> str:
    """
    单日格子文案（含节假日 / 有效考勤 / 每日工时）。

    @param day 日期
    @param summary 摘要（可空）
    @param today 今日
    @param holiday 节假日信息
    @return 多行文本
    @author Kai
    @date 2026/07/23 17:55
    """
    lines = [f"{day.day}"]
    if holiday and holiday.label:
        lines.append(holiday.label)

    if day > today:
        lines.append("—")
        return "\n".join(lines)
    if summary is None:
        lines.append("…")
        return "\n".join(lines)
    if summary.token_expired:
        lines.append("登录失效")
        return "\n".join(lines)
    if not summary.ok:
        lines.append("异常")
        return "\n".join(lines)

    # 休息日：有打卡也展示工时
    if holiday and not holiday.is_workday:
        if summary.has_clock_in:
            lines.append(f"上 {format_hm(summary.in_time)}")
            if summary.latest_out_time:
                lines.append(f"下 {format_hm(summary.latest_out_time)}")
            ws = stats_worked_seconds(summary, today)
            if ws is not None:
                lines.append(f"工 {format_duration(ws)}")
            elif day < today and not summary.has_clock_out:
                lines.append("未下班")
        else:
            lines.append("—")
        return "\n".join(lines)

    tip = (summary.validity_tip or "").strip()
    if tip:
        short = tip.replace("有效·", "")
        lines.append(short if len(short) <= 10 else short[:10])

    if not summary.has_clock_in:
        if not tip:
            lines.append("未打卡")
        return "\n".join(lines)

    inn = format_hm(summary.in_time)
    leave = format_hm(summary.target_time)
    out = format_hm(summary.latest_out_time)
    lines.append(f"上 {inn}")
    lines.append(f"走 {leave}")
    if out != "--":
        lines.append(f"下 {out}")
    ws = stats_worked_seconds(summary, today)
    if ws is not None:
        lines.append(f"工 {format_duration(ws)}")
    elif day < today and not summary.has_clock_out:
        lines.append("未下班")
    return "\n".join(lines)


def build_validity_notice(
    records: dict[str, AttendanceSummary],
    holidays: dict[str, DayHolidayInfo],
    days: list[date],
    today: date,
) -> str:
    """
    汇总无效 / 带提示的工作日，用于进度区提示。

    @param records 日摘要
    @param holidays 节假日
    @param days 统计范围
    @param today 今日
    @return 提示文案（可空）
    @author Kai
    @date 2026/07/23 17:45
    """
    invalid: list[str] = []
    warned: list[str] = []
    for day in days:
        if day > today:
            continue
        holiday = holidays.get(day.isoformat())
        if holiday and not holiday.is_workday:
            continue
        summary = records.get(day.isoformat())
        if summary is None or not summary.ok or summary.error == "FUTURE":
            continue
        tip = (summary.validity_tip or "").strip()
        label = f"{day.month}/{day.day}"
        if not summary.is_valid_attendance:
            invalid.append(f"{label}{tip or '无效'}")
        elif tip.startswith("有效·"):
            warned.append(f"{label}{tip.replace('有效·', '')}")

    parts: list[str] = []
    if invalid:
        parts.append("无效考勤：" + "、".join(invalid[:8]))
        if len(invalid) > 8:
            parts[-1] += f" 等{len(invalid)}天"
    if warned:
        parts.append("提示：" + "、".join(warned[:6]))
        if len(warned) > 6:
            parts[-1] += f" 等{len(warned)}天"
    return " · ".join(parts)


class _StatsWorker(QThread):
    """后台按日拉接口 + 节假日。"""

    progress = Signal(int, int, str)
    finished_ok = Signal(object)
    finished_err = Signal(str)

    def __init__(self, days: list[date], *, force_refresh: bool = False) -> None:
        super().__init__()
        self._days = days
        # True 时丢掉范围内缓存并重新打接口
        self._force_refresh = force_refresh

    def run(self) -> None:
        try:
            holidays = prefetch_holidays(self._days)

            def on_progress(done: int, total: int, day: date) -> None:
                self.progress.emit(done, total, day.isoformat())

            results = fetch_attendance_range(
                self._days,
                max_workers=4,
                on_progress=on_progress,
                force_refresh=self._force_refresh,
            )
            self.finished_ok.emit({"records": results, "holidays": holidays})
        except Exception as exc:  # noqa: BLE001
            LOG.warning("统计拉取失败: %s", exc)
            self.finished_err.emit(str(exc)[:200])


class StatsDialog(QDialog):
    """
    周 / 月统计：日历表格 + 平均汇总。

    @author Kai
    @date 2026/07/23 17:25
    @description 数据来自打卡接口按日查询；月视图可切换月份
    """

    def __init__(self, kind: str = "week", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._kind = "week" if kind == "week" else "month"
        # 真实「今天」：高亮 / 未来日判断
        self._today = date.today()
        # 当前查看月（取月初）
        self._view_month = self._today.replace(day=1)
        self._days = (
            week_days(self._today)
            if self._kind == "week"
            else month_days(self._view_month)
        )
        self._records: dict[str, AttendanceSummary] = {}
        self._holidays: dict[str, DayHolidayInfo] = {}
        self._worker: Optional[_StatsWorker] = None

        title = "本周统计" if self._kind == "week" else "本月统计"
        self.setWindowTitle(f"考勤助手 · {title}")
        self.setMinimumSize(980 if self._kind == "month" else 1040, 520 if self._kind == "month" else 380)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(DIALOG_QSS)

        range_tip = (
            f"{self._days[0].isoformat()} ~ {self._days[-1].isoformat()}"
            if self._days
            else ""
        )

        # 周视图顶部标题（月视图用导航条年月）
        self.lbl_week_title = QLabel("本周统计")
        self.lbl_week_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_week_title.setStyleSheet("font-size:15px; font-weight:600; color:#F3F4F6;")

        # 横向指标条：标签在上、数值在下
        self._metric_labels: list[QLabel] = []
        self._metric_values: list[QLabel] = []
        self.metrics_frame = QFrame()
        self.metrics_frame.setObjectName("metricsFrame")
        metrics_layout = QHBoxLayout(self.metrics_frame)
        metrics_layout.setContentsMargins(4, 4, 4, 4)
        metrics_layout.setSpacing(0)
        placeholder = build_average_metrics(self._kind, {})
        for idx, (name, _) in enumerate(placeholder):
            cell, lbl_name, lbl_val = self._make_metric_cell(name)
            self._metric_labels.append(lbl_name)
            self._metric_values.append(lbl_val)
            metrics_layout.addWidget(cell, 1)
            if idx < len(placeholder) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet("background:#2A3548; max-width:1px;")
                metrics_layout.addWidget(sep)

        self.lbl_progress = QLabel(f"范围：{range_tip}")
        self.lbl_progress.setStyleSheet("color:#94A3B8; font-size:12px;")
        self.lbl_progress.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # 月份切换条（仅月视图）
        self.nav_row = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 上月")
        self.btn_next = QPushButton("下月 ▶")
        self.lbl_month = QLabel(self._month_label())
        self.lbl_month.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_month.setStyleSheet("font-size:15px; font-weight:600; color:#F3F4F6;")
        self.btn_prev.clicked.connect(lambda: self._shift_month(-1))
        self.btn_next.clicked.connect(lambda: self._shift_month(1))
        self.nav_row.addWidget(self.btn_prev)
        self.nav_row.addStretch(1)
        self.nav_row.addWidget(self.lbl_month)
        self.nav_row.addStretch(1)
        self.nav_row.addWidget(self.btn_next)
        self._sync_nav_buttons()

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self._init_table_skeleton()

        self.btn_reload = QPushButton("刷新历史")
        self.btn_reload.setToolTip("丢掉当前范围的本地缓存，重新向接口拉取（人事补卡后点这里）")
        self.btn_reload.clicked.connect(lambda: self._start(force_refresh=True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_reload)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        if self._kind == "month":
            layout.addLayout(self.nav_row)
        else:
            layout.addWidget(self.lbl_week_title)
        layout.addWidget(self.metrics_frame)
        layout.addWidget(self.lbl_progress)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

        self._start()

    def _make_metric_cell(self, name: str) -> tuple[QWidget, QLabel, QLabel]:
        """
        单个指标格：上标签、下数值。

        @param name 指标名
        @return (容器, 标签控件, 数值控件)
        @author Kai
        @date 2026/07/23 17:30
        """
        cell = QWidget()
        cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        col = QVBoxLayout(cell)
        col.setContentsMargins(6, 8, 6, 8)
        col.setSpacing(4)
        lbl_name = QLabel(name)
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_name.setStyleSheet("color:#94A3B8; font-size:11px;")
        lbl_val = QLabel("--")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_val.setStyleSheet("color:#F8FAFC; font-size:14px; font-weight:600;")
        col.addWidget(lbl_name)
        col.addWidget(lbl_val)
        return cell, lbl_name, lbl_val

    def _apply_metrics(self, records: dict[str, AttendanceSummary]) -> None:
        """
        刷新横向指标条。

        @param records 接口结果
        @author Kai
        @date 2026/07/23 17:30
        """
        items = build_average_metrics(self._kind, records)
        for i, (name, value) in enumerate(items):
            if i >= len(self._metric_values):
                break
            self._metric_labels[i].setText(name)
            self._metric_values[i].setText(value)

    def _month_label(self) -> str:
        """当前查看月标题。"""
        return f"{self._view_month.year} 年 {self._view_month.month} 月"

    def _stats_title(self) -> str:
        """汇总区标题。"""
        if self._kind == "week":
            return "本周统计"
        return f"{self._view_month.year}年{self._view_month.month}月统计"

    def _sync_nav_buttons(self) -> None:
        """
        同步上/下月按钮可用状态（最多切到当前月）。

        @author Kai
        @date 2026/07/23 17:25
        """
        if self._kind != "month":
            return
        cur = self._today.replace(day=1)
        busy = bool(self._worker and self._worker.isRunning())
        self.btn_prev.setEnabled(not busy)
        self.btn_next.setEnabled(not busy and self._view_month < cur)
        self.lbl_month.setText(self._month_label())

    def _shift_month(self, delta: int) -> None:
        """
        切换查看月份并重新拉取。

        @param delta -1 上月 / +1 下月
        @author Kai
        @date 2026/07/23 17:25
        """
        if self._kind != "month":
            return
        if self._worker and self._worker.isRunning():
            return
        y = self._view_month.year
        m = self._view_month.month + delta
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        candidate = date(y, m, 1)
        if candidate > self._today.replace(day=1):
            return
        self._view_month = candidate
        self._days = month_days(self._view_month)
        self._records = {}
        self._holidays = {}
        self.lbl_month.setText(self._month_label())
        self.setWindowTitle(f"考勤助手 · {self._stats_title()}")
        self._init_table_skeleton()
        self._start()

    def _blank_out_of_month_item(self) -> QTableWidgetItem:
        """
        非当月占位格（浅灰底，无交互）。

        @return 表格项
        @author Kai
        @date 2026/07/23 17:20
        """
        item = QTableWidgetItem("")
        item.setBackground(C_EMPTY)
        item.setForeground(C_MUTED)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        return item

    def _init_table_skeleton(self) -> None:
        """初始化空日历骨架。"""
        self.table.clear()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(WEEKDAY_HEADERS)
        if self._kind == "week":
            self.table.setRowCount(1)
            self.table.setRowHeight(0, 110)
            for col, day in enumerate(self._days):
                item = QTableWidgetItem(f"{day.day}\n…")
                item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                item.setFont(QFont("Segoe UI", 10))
                item.setBackground(C_DAY_BG)
                self.table.setItem(0, col, item)
        else:
            grid = monthcalendar(self._view_month.year, self._view_month.month)
            self.table.setRowCount(len(grid))
            for r, week in enumerate(grid):
                self.table.setRowHeight(r, 96)
                for c, day_num in enumerate(week):
                    if day_num == 0:
                        self.table.setItem(r, c, self._blank_out_of_month_item())
                    else:
                        item = QTableWidgetItem(f"{day_num}\n…")
                        item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                        item.setFont(QFont("Segoe UI", 9))
                        item.setBackground(C_DAY_BG)
                        self.table.setItem(r, c, item)

    def _set_busy(self, busy: bool) -> None:
        """拉取中禁用切换 / 刷新。"""
        self.btn_reload.setEnabled(not busy)
        self._sync_nav_buttons()
        if self._kind == "month":
            # _sync 已处理；busy 时再强制禁用以避免竞态
            if busy:
                self.btn_prev.setEnabled(False)
                self.btn_next.setEnabled(False)

    def _start(self, *, force_refresh: bool = False) -> None:
        """
        启动后台拉取。

        @param force_refresh 为 True 时丢掉当前范围缓存再打接口
        @author Kai
        @date 2026/09/01 10:20
        """
        if self._worker and self._worker.isRunning():
            return
        self._set_busy(True)
        self._apply_metrics({})
        self.lbl_progress.setText(
            f"{'正在刷新历史' if force_refresh else '正在拉取'}… 0 / {len(self._days)}"
        )
        self._worker = _StatsWorker(self._days, force_refresh=force_refresh)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.start()

    def _on_progress(self, done: int, total: int, day_iso: str) -> None:
        self.lbl_progress.setText(f"进度：{done} / {total}（最近 {day_iso}）")

    def _on_err(self, msg: str) -> None:
        self._set_busy(False)
        self._apply_metrics({})
        self.lbl_progress.setText(f"拉取失败：{msg}（可点「刷新历史」）")

    def _on_ok(self, payload: object) -> None:
        self._set_busy(False)
        if not isinstance(payload, dict):
            self.lbl_progress.setText("拉取结果异常")
            return
        records = payload.get("records")
        holidays = payload.get("holidays")
        if not isinstance(records, dict):
            # 兼容旧结构
            records = payload
            holidays = {}
        self._records = records  # type: ignore[assignment]
        self._holidays = holidays if isinstance(holidays, dict) else {}
        self._apply_metrics(self._records)
        punched = any(
            s.ok and s.has_clock_in and s.error != "FUTURE"
            for s in self._records.values()
        )
        tip = f"已完成 · {self._days[0].isoformat()} ~ {self._days[-1].isoformat()}"
        if not punched:
            tip += " · 暂无上班卡"
        notice = build_validity_notice(
            self._records, self._holidays, self._days, self._today
        )
        if notice:
            tip = tip + "\n" + notice
            self.lbl_progress.setStyleSheet(
                "color:#FBBF24; font-size:12px;"
                if "无效" in notice
                else "color:#94A3B8; font-size:12px;"
            )
        else:
            self.lbl_progress.setStyleSheet("color:#94A3B8; font-size:12px;")
        self.lbl_progress.setText(tip)
        self._paint_calendar()

    def _day_bg(self, day: date, holiday: Optional[DayHolidayInfo]) -> QColor:
        """
        按节假日类型取格子底色。

        @param day 日期
        @param holiday 节假日信息
        @return 背景色
        @author Kai
        @date 2026/07/23 17:35
        """
        if day == self._today:
            return C_TODAY_BG
        if holiday is None:
            return C_DAY_BG
        if holiday.kind == "holiday":
            return C_HOLIDAY_BG
        if holiday.kind == "weekend":
            return C_WEEKEND_BG
        if holiday.kind == "makeup":
            return C_MAKEUP_BG
        return C_DAY_BG

    def _paint_calendar(self) -> None:
        """把接口结果填进日历格。"""
        today = self._today
        if self._kind == "week":
            self.table.setRowHeight(0, 148)
            for col, day in enumerate(self._days):
                summary = self._records.get(day.isoformat())
                holiday = self._holidays.get(day.isoformat())
                item = QTableWidgetItem(cell_text(day, summary, today, holiday))
                item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                item.setFont(QFont("Segoe UI", 10))
                item.setBackground(self._day_bg(day, holiday))
                self._style_item(item, day, summary, today, holiday)
                self.table.setItem(0, col, item)
            return

        grid = monthcalendar(self._view_month.year, self._view_month.month)
        self.table.setRowCount(len(grid))
        for r, week in enumerate(grid):
            self.table.setRowHeight(r, 126)
            for c, day_num in enumerate(week):
                if day_num == 0:
                    self.table.setItem(r, c, self._blank_out_of_month_item())
                    continue
                day = date(self._view_month.year, self._view_month.month, day_num)
                summary = self._records.get(day.isoformat())
                holiday = self._holidays.get(day.isoformat())
                item = QTableWidgetItem(cell_text(day, summary, today, holiday))
                item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                item.setFont(QFont("Segoe UI", 9))
                item.setBackground(self._day_bg(day, holiday))
                self._style_item(item, day, summary, today, holiday)
                self.table.setItem(r, c, item)

    def _style_item(
        self,
        item: QTableWidgetItem,
        day: date,
        summary: Optional[AttendanceSummary],
        today: date,
        holiday: Optional[DayHolidayInfo] = None,
    ) -> None:
        """按状态与节假日上色。"""
        if day == today:
            item.setBackground(C_TODAY_BG)

        # 未来日
        if day > today:
            if holiday and holiday.kind == "holiday":
                item.setForeground(C_HOLIDAY_FG)
            elif holiday and holiday.kind == "weekend":
                item.setForeground(C_WEEKEND_FG)
            else:
                item.setForeground(C_FUTURE)
            return

        if summary is None:
            item.setForeground(C_MUTED)
            return
        if summary.token_expired or not summary.ok:
            item.setForeground(C_ERR)
            return

        # 休息日
        if holiday and not holiday.is_workday:
            item.setForeground(
                C_HOLIDAY_FG if holiday.kind == "holiday" else C_WEEKEND_FG
            )
            return

        # 工作日：按有效考勤着色
        if not summary.is_valid_attendance:
            item.setForeground(C_INVALID)
            return
        tip = summary.validity_tip or ""
        if tip.startswith("有效·"):
            item.setForeground(C_WARN)
            return
        if summary.has_clock_in:
            item.setForeground(C_VALID)
            return
        item.setForeground(C_MISS)
