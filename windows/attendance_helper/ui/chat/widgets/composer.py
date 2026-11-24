# Copyright (c) iGroup China.
# All rights reserved.
"""
聊天输入组件。

@author Kai
@date 2026/09/01 09:35
@description 底部固定输入框，支持思考程度与 Enter 发送
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ....config import (
    AI_REASONING_EFFORTS,
    AI_REASONING_OPTIONS,
    DEFAULT_AI_REASONING_EFFORT,
    S,
    persist_ai_reasoning_effort,
)


class ChatComposer(QWidget):
    """
    聊天输入区。

    @author Kai
    @date 2026/08/31 17:35
    @description 输入框、思考程度与发送按钮
    """

    send_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ComposerWrap")

        self.status = QLabel("")
        self.status.setObjectName("ChatStatus")
        self.status.setWordWrap(True)

        self.card = QFrame()
        self.card.setObjectName("ComposerCard")
        self.card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.card.setMinimumWidth(720)

        self.input = QTextEdit()
        self.input.setObjectName("ChatInput")
        self.input.setPlaceholderText("发给助手…（Enter / Ctrl+Enter 发送，Shift+Enter 换行）")
        self.input.setFixedHeight(76)
        self.input.setFont(QFont("Microsoft YaHei UI", 14))
        self.input.installEventFilter(self)

        self.cb_reasoning = QComboBox()
        self.cb_reasoning.setObjectName("ChatReasoning")
        self.cb_reasoning.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb_reasoning.setToolTip("仅影响下一轮对话，不影响宠物短句润色；关闭最快")
        self.cb_reasoning.setMinimumWidth(132)
        self.cb_reasoning.setMinimumHeight(32)
        self.cb_reasoning.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        for value, label in AI_REASONING_OPTIONS:
            self.cb_reasoning.addItem(f"思考：{label}", value)
        self._sync_reasoning_from_settings()
        self.cb_reasoning.currentIndexChanged.connect(self._on_reasoning_picked)

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("ChatSend")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self._emit_send)

        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(6, 2, 0, 0)
        tool_row.setSpacing(8)
        tool_row.addWidget(self.cb_reasoning, 0, Qt.AlignmentFlag.AlignVCenter)
        tool_row.addStretch(1)
        tool_row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignVCenter)

        card_col = QVBoxLayout(self.card)
        card_col.setContentsMargins(16, 10, 10, 10)
        card_col.setSpacing(6)
        card_col.addWidget(self.input)
        card_col.addLayout(tool_row)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(self.status)
        col.addWidget(self.card)

        row = QHBoxLayout(self)
        row.setContentsMargins(28, 12, 28, 16)
        row.addLayout(col, 1)

    def text(self) -> str:
        """
        获取输入文本。

        @return 输入框文本
        @author Kai
        @date 2026/08/31 17:35
        """
        return self.input.toPlainText().strip()

    def clear(self) -> None:
        """
        清空输入框。

        @author Kai
        @date 2026/08/31 17:35
        """
        self.input.clear()

    def set_busy(self, busy: bool) -> None:
        """
        设置发送按钮忙碌状态。

        @param busy 是否忙碌
        @author Kai
        @date 2026/08/31 17:35
        """
        self.send_button.setEnabled(not busy)

    def set_status(self, status: str) -> None:
        """
        设置底部状态文案。

        @param status 状态文本
        @author Kai
        @date 2026/08/31 17:35
        """
        self.status.setText(status or "")

    def set_content_width(self, width: int) -> None:
        """
        设置输入卡片宽度。

        @param width 内容列宽度
        @author Kai
        @date 2026/08/31 17:35
        """
        # 输入卡片跟窗口走，不再卡在消息列的最大宽度上
        self.card.setFixedWidth(max(720, width))

    def eventFilter(self, obj, event):  # noqa: N802
        """
        输入框快捷键：Enter / Ctrl+Enter 发送，Shift+Enter 换行。

        @param obj 事件对象
        @param event Qt 事件
        @return 是否拦截
        @author Kai
        @date 2026/08/31 17:35
        """
        if obj is self.input and isinstance(event, QKeyEvent):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False
                self._emit_send()
                return True
        return super().eventFilter(obj, event)

    def _current_reasoning(self) -> str:
        """
        当前选中的思考程度。

        @return none / low / medium / high
        @author Kai
        @date 2026/09/01 09:35
        """
        value = str(self.cb_reasoning.currentData() or "").strip().lower()
        if value not in AI_REASONING_EFFORTS:
            return DEFAULT_AI_REASONING_EFFORT
        return value

    def _apply_reasoning_ui(self, effort: str) -> None:
        """
        按思考程度选中下拉项。

        @param effort none / low / medium / high
        @author Kai
        @date 2026/09/01 09:35
        """
        for index in range(self.cb_reasoning.count()):
            if str(self.cb_reasoning.itemData(index) or "") == effort:
                if self.cb_reasoning.currentIndex() != index:
                    self.cb_reasoning.setCurrentIndex(index)
                return
        self.cb_reasoning.setCurrentIndex(0)

    def _sync_reasoning_from_settings(self) -> None:
        """
        按当前配置勾选思考程度。

        @author Kai
        @date 2026/09/01 09:35
        """
        effort = str(getattr(S, "ai_reasoning_effort", "") or "").strip().lower()
        if effort not in AI_REASONING_EFFORTS:
            effort = DEFAULT_AI_REASONING_EFFORT
        self._apply_reasoning_ui(effort)

    def _on_reasoning_picked(self) -> None:
        """
        聊天框切换思考程度后立即写入配置。

        @author Kai
        @date 2026/09/01 09:35
        """
        persist_ai_reasoning_effort(self._current_reasoning())

    def _emit_send(self) -> None:
        """
        发出发送请求。

        @author Kai
        @date 2026/08/31 17:35
        """
        text = self.text()
        if text:
            self.send_requested.emit(text)
