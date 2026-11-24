# Copyright (c) iGroup China.
# All rights reserved.
"""
工具调用状态组件。

@author Kai
@date 2026/09/01 10:20
@description ChatGPT 风格工具执行中 / 完成 / 失败卡片
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ..style import TOOL_LABELS


def tool_label(name: str) -> str:
    """
    将工具 id 转为中文显示名。

    @param name 工具 id
    @return 中文名称
    @author Kai
    @date 2026/08/05 16:44
    """
    key = (name or "").strip()
    return TOOL_LABELS.get(key, key or "工具")


class ToolStatusWidget(QWidget):
    """
    单个工具调用状态。

    @author Kai
    @date 2026/09/01 10:20
    @description start_tool / finish_tool 更新执行状态
    """

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        # 工具 id
        self._name = name or "tool"
        # 是否已结束（成功或失败）
        self._done = False
        # 结束时是否成功
        self._ok = True

        self.card = QFrame()
        self.card.setObjectName("ToolCard")
        self.card.setProperty("done", "false")

        self.icon = QLabel("●")
        self.icon.setObjectName("ToolIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text = QLabel()
        self.text.setObjectName("ToolText")
        self.text.setWordWrap(True)

        row = QHBoxLayout(self.card)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(8)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.text, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(64, 4, 16, 4)
        layout.addWidget(self.card, 1)
        self.start_tool(self._name)

    def start_tool(self, name: str | None = None) -> None:
        """
        标记工具执行中。

        @param name 可选工具 id
        @author Kai
        @date 2026/09/01 10:20
        """
        if name:
            self._name = name
        self._done = False
        self._ok = True
        self.icon.setText("●")
        self.text.setText(f"正在使用 {tool_label(self._name)}…")
        self._refresh_state()

    def finish_tool(
        self,
        name: str | None = None,
        *,
        ok: bool = True,
        error: str = "",
    ) -> None:
        """
        标记工具完成或失败。

        @param name 可选工具 id
        @param ok 工具是否成功
        @param error 失败原因（展示用）
        @author Kai
        @date 2026/09/01 10:20
        """
        if name:
            self._name = name
        self._done = True
        self._ok = bool(ok)
        label = tool_label(self._name)
        if self._ok:
            self.icon.setText("✓")
            self.text.setText(f"已使用 {label}")
        else:
            self.icon.setText("!")
            tip = (error or "失败").strip()
            self.text.setText(f"{label}失败：{tip}" if tip else f"{label}失败")
        self._refresh_state()

    def is_done(self) -> bool:
        """
        是否已结束（成功或失败）。

        @return 已结束则为 True
        @author Kai
        @date 2026/09/01 10:20
        """
        return self._done

    def tool_name(self) -> str:
        """
        返回工具 id。

        @return 工具 id
        @author Kai
        @date 2026/08/05 16:44
        """
        return self._name

    def _refresh_state(self) -> None:
        """
        刷新 QSS 动态属性。

        @author Kai
        @date 2026/09/01 10:20
        """
        if not self._done:
            state = "false"
        elif self._ok:
            state = "true"
        else:
            state = "error"
        self.card.setProperty("done", state)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        if not self._done:
            self.icon.setStyleSheet("color:#2563EB;")
            self.text.setStyleSheet("color:#1D4ED8;")
        elif self._ok:
            self.icon.setStyleSheet("color:#166534;")
            self.text.setStyleSheet("color:#166534;")
        else:
            self.icon.setStyleSheet("color:#B91C1C;")
            self.text.setStyleSheet("color:#B91C1C;")
