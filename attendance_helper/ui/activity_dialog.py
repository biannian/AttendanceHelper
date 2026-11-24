# Copyright (c) iGroup.
# All rights reserved.
"""
使用时长对话框。

@author Kai
@date 2026/09/29 15:12
@description 按天查看工作、摸鱼、休息、未分类，并可改归类、暂停、清空
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..activity_classify import (
    CAT_LABELS,
    CAT_REST,
    CAT_SLACK,
    CAT_UNKNOWN,
    CAT_WORK,
    IDLE_REST_SECONDS,
    REST_APP_KEY,
    format_usage_duration,
)
from ..activity_tracker import ActivityTracker, UsageView
from .. import playground
from ..config import S

# 与周月统计同一套暗色，避免使用时长窗口突出来一块白底
_DIALOG_QSS = """
QDialog { background-color: #0F141B; color: #E5E7EB; }
QLabel { color: #E5E7EB; }
QPushButton {
    background-color: #243044;
    color: #E5E7EB;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #2E3C54; }
QPushButton:disabled { color: #6B7280; background-color: #1A2230; }
QHeaderView::section {
    background-color: #1A2332;
    color: #CBD5E1;
    border: none;
    border-bottom: 1px solid #2A3548;
    padding: 6px;
    font-weight: 600;
}
QTableWidget {
    background-color: #121820;
    border: 1px solid #2A3548;
    gridline-color: #2A3548;
    color: #E5E7EB;
    outline: none;
}
QTableWidget::item:selected { background-color: #1A3D32; }
"""

_CAT_COLOR = {
    CAT_WORK: QColor("#4ADE80"),
    CAT_SLACK: QColor("#FBBF24"),
    CAT_REST: QColor("#93C5FD"),
    CAT_UNKNOWN: QColor("#94A3B8"),
}


class ActivityDialog(QDialog):
    """
    每天的前台软件时长。

    @author Kai
    @date 2026/09/29 15:12
    @description 休息来自锁屏和超过 1 分钟无操作，不能改归类
    """

    def __init__(self, tracker: ActivityTracker) -> None:
        """
        创建紧凑的分类明细与今日宠物联动入口。

        @param tracker 与托盘共用的使用时长累计器
        @author Kai
        @date 2026/10/15 14:17
        """
        super().__init__()
        # 统计日期及累计器保留原有操作语义；游乐场窗口按需创建。
        self._tracker = tracker
        self._day = date.today()
        self.setWindowTitle("使用时长")
        self.setMinimumSize(520, 520)
        self.resize(560, 620)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(_DIALOG_QSS)

        self._btn_prev = QPushButton("◀ 前一天")
        self._btn_next = QPushButton("后一天 ▶")
        self._lbl_day = QLabel()
        self._lbl_day.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_day.setStyleSheet("font-size:15px; font-weight:600;")

        nav = QHBoxLayout()
        nav.addWidget(self._btn_prev)
        nav.addWidget(self._lbl_day, 1)
        nav.addWidget(self._btn_next)

        self._lbl_work = self._metric(CAT_WORK)
        self._lbl_slack = self._metric(CAT_SLACK)
        self._lbl_rest = self._metric(CAT_REST)
        self._lbl_unknown = self._metric(CAT_UNKNOWN)
        # 四类数据分成两列，避免长时长数值把整个窗口撑宽。
        metrics = QGridLayout()
        for index, label in enumerate((
            self._lbl_work,
            self._lbl_slack,
            self._lbl_rest,
            self._lbl_unknown,
        )):
            metrics.addWidget(label, index // 2, index % 2)
        metrics.setColumnStretch(0, 1)
        metrics.setColumnStretch(1, 1)

        # 只提示今天的故事场景，不再引入独立养成面板。
        self._lbl_growth = QLabel()
        self._lbl_growth.setWordWrap(True)
        self._lbl_growth.setStyleSheet("color:#4FD1A5; font-size:12px;")

        idle_minutes = max(1, IDLE_REST_SECONDS // 60)
        self._lbl_hint = QLabel(
            f"锁屏、超过 {idle_minutes} 分钟没有操作、桌面和开始菜单，都记为休息。"
            "助手没开着、手动暂停，或一次断档超过 4 小时，不会补进总额。"
            "浏览器按当前标签的网址区分工作和摸鱼，只记域名，不保存完整地址。"
        )
        self._lbl_hint.setWordWrap(True)
        self._lbl_hint.setStyleSheet("color:#94A3B8; font-size:12px;")

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["软件", "时长", "归类"])
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self._btn_work = QPushButton("标为工作")
        self._btn_slack = QPushButton("标为摸鱼")
        self._btn_unknown = QPushButton("标为未分类")
        self._btn_reset = QPushButton("恢复默认")
        mark_row = QHBoxLayout()
        for button in (
            self._btn_work,
            self._btn_slack,
            self._btn_unknown,
            self._btn_reset,
        ):
            mark_row.addWidget(button)
        mark_row.addStretch(1)

        self._btn_pause = QPushButton("暂停今日统计")
        self._btn_clear = QPushButton("清空这天")
        self._btn_close = QPushButton("关闭")
        action_row = QHBoxLayout()
        action_row.addWidget(self._btn_pause)
        action_row.addWidget(self._btn_clear)
        action_row.addStretch(1)
        action_row.addWidget(self._btn_close)

        layout = QVBoxLayout(self)
        layout.addLayout(nav)
        layout.addLayout(metrics)
        layout.addWidget(self._lbl_growth)
        layout.addWidget(self._lbl_hint)
        layout.addWidget(self._table, 1)
        layout.addLayout(mark_row)
        layout.addLayout(action_row)

        self._btn_prev.clicked.connect(lambda: self._shift_day(-1))
        self._btn_next.clicked.connect(lambda: self._shift_day(1))
        self._btn_work.clicked.connect(lambda: self._mark(CAT_WORK))
        self._btn_slack.clicked.connect(lambda: self._mark(CAT_SLACK))
        self._btn_unknown.clicked.connect(lambda: self._mark(CAT_UNKNOWN))
        self._btn_reset.clicked.connect(lambda: self._mark(None))
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_clear.clicked.connect(self._clear_day)
        self._btn_close.clicked.connect(self.accept)
        self._table.itemSelectionChanged.connect(self._sync_mark_buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.reload)
        self._timer.start()
        self.reload()

    def reload(self) -> None:
        """
        按当前查看日重画表格和合计。

        @author Kai
        @date 2026/10/15 14:17
        """
        selected = self._selected_key()
        today = date.today()
        if self._day == today:
            self._lbl_day.setText(f"今天  {self._day.isoformat()}")
        else:
            self._lbl_day.setText(self._day.isoformat())
        self._btn_next.setEnabled(self._day < today)
        self._btn_pause.setText(
            "恢复今日统计" if self._tracker.is_paused() else "暂停今日统计"
        )

        totals = self._tracker.totals_for(self._day)
        context = playground.usage_context(self._day, totals)
        prefix = "今日" if self._day == today else "这天"
        self._lbl_growth.setText(
            f"{prefix}使用时长可积累 {context['growth_target']} 点宠物成长\n"
            "左键卡片可以随手来一题海龟汤。"
        )
        self._lbl_growth.setVisible(S.fun_enable and S.fun_usage_link and S.fun_card_mode != "off")
        self._lbl_work.setText(
            f"工作  {format_usage_duration(totals[CAT_WORK])}"
        )
        self._lbl_slack.setText(
            f"摸鱼  {format_usage_duration(totals[CAT_SLACK])}"
        )
        self._lbl_rest.setText(
            f"休息  {format_usage_duration(totals[CAT_REST])}"
        )
        self._lbl_unknown.setText(
            f"未分类  {format_usage_duration(totals[CAT_UNKNOWN])}"
        )

        rows = self._tracker.rows_for(self._day)
        self._table.clearSpans()
        self._table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self._set_row(index, row)
        if not rows:
            self._table.setRowCount(1)
            empty = QTableWidgetItem("这一天还没有记录")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._table.setItem(0, 0, empty)
            self._table.setSpan(0, 0, 1, 3)
        else:
            self._restore_selection(selected)
        self._sync_mark_buttons()

    def _metric(self, category: str) -> QLabel:
        """
        做一个合计标签。

        @param category 归类
        @return 带颜色的标签
        @author Kai
        @date 2026/09/29 15:12
        """
        label = QLabel()
        color = _CAT_COLOR[category].name()
        label.setStyleSheet(f"color:{color}; font-size:16px; font-weight:600;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _set_row(self, index: int, row: UsageView) -> None:
        """
        填表格的一行。

        @param index 行号
        @param row 使用记录
        @author Kai
        @date 2026/09/29 15:12
        """
        name_item = QTableWidgetItem(row.display_name)
        name_item.setData(Qt.ItemDataRole.UserRole, row.app_key)
        duration_item = QTableWidgetItem(format_usage_duration(row.seconds))
        if row.app_key == REST_APP_KEY:
            category_text = CAT_LABELS[CAT_REST]
        elif row.manual:
            category_text = f"{CAT_LABELS[row.category]} · 已标"
        elif row.category == CAT_UNKNOWN:
            category_text = CAT_LABELS[CAT_UNKNOWN]
        else:
            category_text = f"{CAT_LABELS[row.category]} · 默认"
        category_item = QTableWidgetItem(category_text)
        category_item.setForeground(_CAT_COLOR.get(row.category, QColor("#E5E7EB")))
        self._table.setItem(index, 0, name_item)
        self._table.setItem(index, 1, duration_item)
        self._table.setItem(index, 2, category_item)

    def _shift_day(self, step: int) -> None:
        """
        切换查看的日期，不能看到未来。

        @param step -1 前一天，1 后一天
        @author Kai
        @date 2026/09/29 15:12
        """
        target = self._day + timedelta(days=step)
        if target > date.today():
            return
        self._day = target
        self.reload()

    def _selected_key(self) -> str:
        """
        当前选中行的软件键。

        @return app_key；没选中时为空串
        @author Kai
        @date 2026/09/29 15:12
        """
        row = self._table.currentRow()
        if row < 0:
            return ""
        item = self._table.item(row, 0)
        if item is None:
            return ""
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else ""

    def _restore_selection(self, app_key: str) -> None:
        """
        刷新后尽量还选中原来的软件。

        @param app_key 刷新前的键
        @author Kai
        @date 2026/09/29 15:12
        """
        if not app_key:
            return
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) == app_key:
                self._table.selectRow(row)
                return

    def _sync_mark_buttons(self) -> None:
        """
        休息行和空选中不能改归类。

        @author Kai
        @date 2026/09/29 15:12
        """
        key = self._selected_key()
        enabled = bool(key) and key != REST_APP_KEY
        for button in (
            self._btn_work,
            self._btn_slack,
            self._btn_unknown,
            self._btn_reset,
        ):
            button.setEnabled(enabled)

    def _mark(self, category: str | None) -> None:
        """
        把选中软件标成工作、摸鱼、未分类，或恢复默认。

        @param category 目标归类；None 表示清除手动标记
        @author Kai
        @date 2026/09/29 15:12
        """
        key = self._selected_key()
        if not key or key == REST_APP_KEY:
            return
        self._tracker.set_category(key, category)
        self.reload()

    def _toggle_pause(self) -> None:
        """
        暂停或恢复今天的统计。看历史日期时也只影响今天。

        @author Kai
        @date 2026/09/29 15:12
        """
        self._tracker.set_paused(not self._tracker.is_paused())
        self.reload()

    def _clear_day(self) -> None:
        """
        清空当前查看日的记录。

        @author Kai
        @date 2026/09/29 15:12
        """
        answer = QMessageBox.question(
            self,
            "清空使用记录",
            f"清空 {self._day.isoformat()} 的使用时长？软件归类会保留。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._tracker.clear_day(self._day)
        self.reload()
