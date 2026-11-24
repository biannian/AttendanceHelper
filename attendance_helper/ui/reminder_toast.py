# Copyright (c) iGroup China.
# All rights reserved.
"""
事项提醒前台弹窗（托盘气泡被系统屏蔽时的兜底）。

@author Kai
@date 2026/08/05 16:58
@description 置顶卡片通知，避免只依赖 showMessage
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

TOAST_QSS = """
QDialog#ReminderToast {
    background: transparent;
}
QFrame#ToastCard {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 20px;
}
QLabel#ToastIcon {
    background: #E8F0FE;
    color: #2563EB;
    border: 1px solid #BFDBFE;
    border-radius: 18px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    font-size: 18px;
    font-weight: 700;
}
QLabel#ToastBadge {
    background: #F3F4F6;
    color: #4B5563;
    border: 1px solid #E5E7EB;
    border-radius: 11px;
    padding: 2px 9px;
    font-size: 12px;
    font-weight: 600;
}
QLabel#ToastTitle {
    color: #111827;
    font-size: 16px;
    font-weight: 700;
}
QLabel#ToastBody {
    color: #374151;
    font-size: 13px;
    line-height: 1.45;
}
QPushButton#ToastClose {
    background: #FFFFFF;
    color: #111827;
    border: 1px solid #D1D5DB;
    border-radius: 12px;
    padding: 8px 18px;
    font-weight: 600;
}
QPushButton#ToastClose:hover {
    background: #F3F4F6;
    border-color: #9CA3AF;
}
QPushButton#ToastPrimary {
    background: #111827;
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    padding: 8px 18px;
    font-weight: 700;
}
QPushButton#ToastPrimary:hover {
    background: #374151;
}
"""


class ReminderToast(QDialog):
    """
    提醒兜底弹窗。

    @author Kai
    @date 2026/08/31 17:45
    @description 贴工作区右下角的置顶卡片，不走系统托盘气泡
    """

    def __init__(
        self,
        title: str,
        message: str,
        *,
        badge: str = "",
        auto_close_ms: int = 12000,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReminderToast")
        self.setWindowTitle(title or "提醒")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)
        self.setStyleSheet(TOAST_QSS)

        card = QFrame()
        card.setObjectName("ToastCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(15, 23, 42, 55))
        card.setGraphicsEffect(shadow)

        icon = QLabel("⏰")
        icon.setObjectName("ToastIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 角标按提醒类型区分：事项 / 外卖 / 下班
        badge_text = (badge or "").strip() or title or "提醒"
        badge_lbl = QLabel(badge_text)
        badge_lbl.setObjectName("ToastBadge")

        lbl_t = QLabel(title or "提醒")
        lbl_t.setObjectName("ToastTitle")
        lbl_b = QLabel(message or "")
        lbl_b.setObjectName("ToastBody")
        lbl_b.setWordWrap(True)

        btn = QPushButton("知道了")
        btn.setObjectName("ToastPrimary")
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.clicked.connect(self._close_from_button)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(lbl_t, 1)
        head.addWidget(badge_lbl)

        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.addStretch(1)
        row.addWidget(btn)

        content = QVBoxLayout()
        content.setContentsMargins(12, 14, 16, 14)
        content.setSpacing(8)
        content.addLayout(head)
        content.addWidget(lbl_b)
        content.addLayout(row)

        card_row = QHBoxLayout(card)
        card_row.setContentsMargins(14, 14, 0, 0)
        card_row.setSpacing(0)
        card_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        card_row.addLayout(content, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(card)

        if auto_close_ms > 0:
            QTimer.singleShot(auto_close_ms, self.close)

    def _close_from_button(self) -> None:
        """
        处理用户点击确认按钮。

        @author Kai
        @date 2026/08/05 16:58
        """
        self.close()

    def showEvent(self, event) -> None:  # noqa: N802
        """
        首次展示时靠近当前屏幕右下角。

        @param event 显示事件
        @author Kai
        @date 2026/08/05 16:58
        """
        super().showEvent(event)
        self._move_to_bottom_right()
        self.raise_()

    def _move_to_bottom_right(self) -> None:
        """
        将提醒卡片定位到可用工作区右下角。

        @author Kai
        @date 2026/08/05 16:58
        """
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.adjustSize()
        margin = 24
        x = geo.right() - self.width() - margin
        y = geo.bottom() - self.height() - margin
        self.move(max(geo.left(), x), max(geo.top(), y))


def show_reminder_toast(title: str, message: str) -> None:
    """
    弹出非模态提醒窗。

    @param title 标题
    @param message 正文
    @author Kai
    @date 2026/08/05 16:58
    """
    dlg = ReminderToast(title, message)
    # 避免被 GC：挂到实例属性由调用方持有列表
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.show()
    dlg.raise_()
