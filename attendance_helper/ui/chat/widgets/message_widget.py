# Copyright (c) iGroup China.
# All rights reserved.
"""
聊天消息组件。

@author Kai
@date 2026/08/05 16:44
@description User / Assistant 消息均为独立 QWidget
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..renderer import build_markdown_document
from ..style import CONTENT_MAX_WIDTH


class MessageWidget(QWidget):
    """
    消息组件基类。

    @author Kai
    @date 2026/08/05 16:44
    @description 保存消息文本并提供增量更新接口
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._content = text or ""

    def set_content(self, text: str) -> None:
        """
        设置完整消息内容。

        @param text 消息文本
        @author Kai
        @date 2026/08/05 16:44
        """
        self._content = text or ""

    def append_content(self, delta: str) -> None:
        """
        追加流式文本。

        @param delta 增量文本
        @author Kai
        @date 2026/08/05 16:44
        """
        if not delta:
            return
        self.set_content(self._content + delta)

    def content(self) -> str:
        """
        返回当前消息内容。

        @return 消息文本
        @author Kai
        @date 2026/08/05 16:44
        """
        return self._content

    def set_content_width(self, width: int) -> None:
        """
        设置消息内容最大宽度。

        @param width 像素宽度
        @author Kai
        @date 2026/08/05 16:44
        """
        _ = width


class UserMessageWidget(MessageWidget):
    """
    用户消息气泡。

    @author Kai
    @date 2026/08/05 16:44
    @description 右对齐浅色气泡
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.bubble = QLabel()
        self.bubble.setObjectName("UserBubble")
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.bubble.setFont(QFont("Microsoft YaHei UI", 14))

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 8)
        row.addStretch(1)
        row.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignRight)
        self.set_content(text)

    def set_content(self, text: str) -> None:
        """
        设置用户气泡内容。

        @param text 用户输入
        @author Kai
        @date 2026/08/05 16:44
        """
        super().set_content(text)
        self.bubble.setText(self._content)

    def set_content_width(self, width: int) -> None:
        """
        限制用户气泡最大宽度。

        @param width 消息列宽度
        @author Kai
        @date 2026/08/05 16:44
        """
        self.bubble.setMaximumWidth(max(260, int(width * 0.76)))


class AssistantMessageWidget(MessageWidget):
    """
    AI 消息组件。

    @author Kai
    @date 2026/08/05 16:44
    @description 左侧头像 + 独立 QTextBrowser Markdown 内容
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.avatar = QLabel("AI")
        self.avatar.setObjectName("AssistantAvatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.browser = QTextBrowser()
        self.browser.setObjectName("AssistantContent")
        self.browser.setOpenExternalLinks(True)
        self.browser.setReadOnly(True)
        self.browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.browser, 1)
        self.set_content(text)

    def set_content(self, text: str) -> None:
        """
        设置 AI Markdown 内容。

        @param text AI 回复
        @author Kai
        @date 2026/08/05 16:44
        """
        super().set_content(text)
        doc = build_markdown_document(self._content)
        self.browser.setDocument(doc)
        self._fit_browser_height()

    def set_content_width(self, width: int) -> None:
        """
        更新 AI 文本区域宽度并重新计算高度。

        @param width 消息列宽度
        @author Kai
        @date 2026/08/05 16:44
        """
        content_width = max(280, min(CONTENT_MAX_WIDTH, width) - 56)
        self.browser.setMaximumWidth(content_width)
        self.browser.document().setTextWidth(content_width)
        self._fit_browser_height()

    def _fit_browser_height(self) -> None:
        """
        根据 Markdown 文档高度撑开控件，避免内层滚动条。

        @author Kai
        @date 2026/08/05 16:44
        """
        doc = self.browser.document()
        width = max(280, self.browser.maximumWidth() or CONTENT_MAX_WIDTH)
        doc.setTextWidth(width)
        height = int(doc.size().height()) + 12
        self.browser.setFixedHeight(max(32, height))

    def resizeEvent(self, event) -> None:  # noqa: N802
        """
        消息宽度变化时重新适配 Markdown 高度。

        @param event 尺寸事件
        @author Kai
        @date 2026/08/05 16:44
        """
        super().resizeEvent(event)
        self._fit_browser_height()


class EmptyStateWidget(QWidget):
    """
    空会话欢迎态。

    @author Kai
    @date 2026/08/05 16:44
    @description 无消息时显示引导文案
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        title = QLabel("今天想先办哪件事？")
        title.setStyleSheet("font-size:22px;font-weight:700;color:#111827;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc = QLabel("可以问「还差多久下班」，也可以问「今天摸鱼了多久」。")
        desc.setStyleSheet("font-size:14px;color:#6B7280;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 80, 24, 24)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addStretch(1)
