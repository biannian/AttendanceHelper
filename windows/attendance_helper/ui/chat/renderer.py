# Copyright (c) iGroup China.
# All rights reserved.
"""
AI 消息 Markdown 渲染辅助。

@author Kai
@date 2026/08/05 16:44
@description 单条 Assistant 消息独立 QTextDocument 渲染
"""

from __future__ import annotations

from PySide6.QtGui import QTextDocument

from .style import MARKDOWN_QSS


def build_markdown_document(text: str) -> QTextDocument:
    """
    构建独立 Markdown 文档。

    @param text Markdown / 普通文本
    @return QTextDocument
    @author Kai
    @date 2026/08/05 16:44
    """
    doc = QTextDocument()
    doc.setDefaultStyleSheet(MARKDOWN_QSS)
    doc.setMarkdown(text or "")
    return doc
