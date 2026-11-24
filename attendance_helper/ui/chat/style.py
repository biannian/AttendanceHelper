# Copyright (c) iGroup.
# All rights reserved.
"""
AI 聊天窗口样式常量。

@author Kai
@date 2026/08/05 16:44
@description ChatGPT Windows 风格配色与控件 QSS
"""

from __future__ import annotations

# 主消息列最大宽度；窗口变宽时消息与输入框一起变宽
CONTENT_MAX_WIDTH = 1080

# 工具名 → 中文展示名
TOOL_LABELS: dict[str, str] = {
    "create_item": "创建事项",
    "list_items": "查看事项",
    "complete_item": "完成事项",
    "get_attendance": "查询今日考勤",
    "get_day_attendance": "查询某日考勤",
    "get_month_attendance": "查询本月考勤",
    "get_app_usage": "查询使用时长",
    "web_search": "搜索网页",
    "read_file": "读取文件",
    "list_dir": "列出目录",
    "ls": "列出目录",
    "dir": "列出目录",
}

CHAT_QSS = """
QDialog#ChatDialog {
    background: #F7F7F8;
}
QWidget#ChatHeader {
    background: #FFFFFF;
    border-bottom: 1px solid #ECECF1;
}
QLabel#ChatTitle {
    color: #111827;
    font-size: 16px;
    font-weight: 700;
}
QLabel#ChatSub {
    color: #6B7280;
    font-size: 12px;
}
QScrollArea#ChatMessageArea {
    background: #F7F7F8;
    border: none;
}
QWidget#ChatMessageViewport {
    background: #F7F7F8;
}
QLabel#UserBubble {
    background: #E8F0FE;
    color: #111827;
    border: 1px solid #D7E6FF;
    border-radius: 16px;
    padding: 10px 14px;
    font-size: 14px;
    line-height: 1.5;
}
QLabel#AssistantAvatar {
    background: #10A37F;
    color: #FFFFFF;
    border-radius: 14px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    font-size: 12px;
    font-weight: 700;
}
QTextBrowser#AssistantContent {
    background: transparent;
    color: #111827;
    border: none;
    padding: 0;
    font-size: 14px;
}
QFrame#ToolCard {
    background: #EFF6FF;
    border: 1px solid #BFDBFE;
    border-radius: 12px;
}
QFrame#ToolCard[done="true"] {
    background: #F0FDF4;
    border: 1px solid #BBF7D0;
}
QFrame#ToolCard[done="error"] {
    background: #FEF2F2;
    border: 1px solid #FECACA;
}
QLabel#ToolIcon {
    color: #2563EB;
    font-size: 14px;
    font-weight: 700;
}
QLabel#ToolText {
    color: #1D4ED8;
    font-size: 13px;
    font-weight: 600;
}
QWidget#ComposerWrap, QFrame#ComposerWrap {
    background: #FFFFFF;
    border-top: 1px solid #ECECF1;
}
QFrame#ComposerCard {
    background: #FFFFFF;
    border: 1px solid #DADDE3;
    border-radius: 20px;
}
QTextEdit#ChatInput {
    background: transparent;
    color: #111827;
    border: none;
    padding: 8px 6px;
    font-size: 14px;
}
QPushButton#ChatSend {
    background: #111827;
    color: #FFFFFF;
    border: none;
    border-radius: 16px;
    min-width: 72px;
    min-height: 32px;
    font-weight: 700;
}
QPushButton#ChatSend:hover {
    background: #374151;
}
QPushButton#ChatSend:disabled {
    background: #D1D5DB;
    color: #FFFFFF;
}
QPushButton#ChatGhost {
    background: transparent;
    color: #6B7280;
    border: none;
    border-radius: 10px;
    padding: 6px 10px;
}
QPushButton#ChatGhost:hover {
    background: #F3F4F6;
    color: #111827;
}
QPushButton#ChatGhost:checked {
    background: #E8F0FE;
    color: #1D4ED8;
}
QLabel#ChatStatus {
    color: #6B7280;
    font-size: 12px;
}
QLabel#ChatReasoningLabel {
    color: #6B7280;
    font-size: 12px;
}
QComboBox#ChatReasoning {
    background: #F3F4F6;
    color: #111827;
    border: 1px solid #D1D5DB;
    border-radius: 10px;
    padding: 4px 10px;
    min-width: 132px;
    min-height: 32px;
    font-size: 13px;
    font-weight: 600;
}
QComboBox#ChatReasoning:hover {
    background: #E5E7EB;
}
QComboBox#ChatReasoning::drop-down {
    border: none;
    width: 22px;
}
QComboBox#ChatReasoning QAbstractItemView {
    background: #FFFFFF;
    color: #111827;
    border: 1px solid #E5E7EB;
    selection-background-color: #E8F0FE;
    selection-color: #111827;
    padding: 4px;
}
"""

MARKDOWN_QSS = """
body, p, li, span, div {
    color: #111827;
    background: transparent;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 14px;
}
p {
    margin: 0 0 10px 0;
}
ul, ol {
    margin: 4px 0 10px 20px;
}
code {
    background: #ECECF1;
    color: #111827;
    padding: 1px 5px;
    border-radius: 5px;
}
pre {
    background: #ECECF1;
    color: #111827;
    padding: 10px 12px;
    border-radius: 10px;
    white-space: pre-wrap;
}
a {
    color: #2563EB;
}
"""
