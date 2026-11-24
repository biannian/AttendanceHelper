# Copyright (c) iGroup China.
# All rights reserved.
"""
AI 聊天主窗口。

@author Kai
@date 2026/08/05 16:44
@description QWidget 消息列表 + 独立消息组件 + 增量流式更新
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...ai_agent import run_agent
from ...chat_store import (
    add_message,
    clear_session,
    ensure_default_session,
    recent_messages,
)
from ...config import S, persist_chat_window_state
from .style import CHAT_QSS, CONTENT_MAX_WIDTH
from .widgets import (
    AssistantMessageWidget,
    ChatComposer,
    EmptyStateWidget,
    ToolStatusWidget,
    UserMessageWidget,
)


class ChatMessageList(QScrollArea):
    """
    聊天消息滚动列表。

@author Kai
@date 2026/08/31 17:36
@description 负责 QWidget 消息追加、清空、贴底滚动
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatMessageArea")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._message_widgets: list[QWidget] = []
        self._empty: Optional[EmptyStateWidget] = None
        # 用户贴在底部时，内容变高继续跟到底，避免新消息被输入框挡住
        self._stick_to_bottom = True
        self._pinning_scroll = False

        self.outer = QWidget()
        self.outer.setObjectName("ChatMessageViewport")
        outer_layout = QHBoxLayout(self.outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addStretch(1)

        self.column = QWidget()
        self.column.setMaximumWidth(CONTENT_MAX_WIDTH)
        self.column_layout = QVBoxLayout(self.column)
        self.column_layout.setContentsMargins(0, 14, 0, 28)
        self.column_layout.setSpacing(0)
        self.column_layout.addStretch(1)

        outer_layout.addWidget(self.column)
        outer_layout.addStretch(1)
        self.setWidget(self.outer)
        self.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

    def add_message_widget(self, widget: QWidget) -> None:
        """
        追加一条消息 QWidget。

        @param widget 消息控件
        @author Kai
        @date 2026/08/05 16:44
        """
        self._remove_empty()
        self.column_layout.insertWidget(
            max(0, self.column_layout.count() - 1),
            widget,
        )
        self._message_widgets.append(widget)
        self._apply_content_width(widget)
        widget.adjustSize()
        self.column.updateGeometry()
        self.scroll_to_bottom()

    def clear_messages(self, *, show_empty: bool = True) -> None:
        """
        清空消息列表。

        @param show_empty 是否立即显示空状态
        @author Kai
        @date 2026/08/05 16:52
        """
        for widget in list(self._message_widgets):
            self.column_layout.removeWidget(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._message_widgets.clear()
        self._remove_empty()
        if show_empty:
            self.show_empty()

    def show_empty(self) -> None:
        """
        显示空会话欢迎态。

        @author Kai
        @date 2026/08/05 16:44
        """
        if self._empty is not None:
            return
        self._empty = EmptyStateWidget()
        self.column_layout.insertWidget(0, self._empty)

    def scroll_to_bottom(self) -> None:
        """
        滚动到最新消息；等布局和 Markdown 高度稳定后再贴底。

        @author Kai
        @date 2026/08/31 17:36
        """
        self._stick_to_bottom = True
        self._scroll_to_bottom_now()
        # 0ms 时气泡/Markdown 往往还没撑开，补两次避免最后一条被挡住
        QTimer.singleShot(0, self._scroll_to_bottom_now)
        QTimer.singleShot(80, self._scroll_to_bottom_now)

    def _pin_scroll_to_maximum(self) -> None:
        """
        程序内贴底，不把用户上翻状态清掉。

        @author Kai
        @date 2026/08/31 17:36
        """
        self._pinning_scroll = True
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._pinning_scroll = False

    def _scroll_to_bottom_now(self) -> None:
        """
        立即滚到滚动条底部，并保证最后一条完整可见。

        @author Kai
        @date 2026/08/31 17:36
        """
        if not self._stick_to_bottom:
            return
        self._pin_scroll_to_maximum()
        last = self._last_visible_message()
        if last is not None:
            self.ensureWidgetVisible(last, 0, 24)
            self._pin_scroll_to_maximum()
        self._stick_to_bottom = True

    def _last_visible_message(self) -> Optional[QWidget]:
        """
        取列表中最后一条可见消息。

        @return 消息控件或 None
        @author Kai
        @date 2026/08/31 17:36
        """
        for widget in reversed(self._message_widgets):
            if widget.isVisible():
                return widget
        return None

    def _on_scroll_range_changed(self, _minimum: int, maximum: int) -> None:
        """
        内容变高时若用户本就在底部，继续跟到底。

        @param _minimum 滚动条最小值
        @param maximum 滚动条最大值
        @author Kai
        @date 2026/08/31 17:36
        """
        if self._stick_to_bottom:
            self._pin_scroll_to_maximum()

    def _on_scroll_value_changed(self, value: int) -> None:
        """
        用户上翻则取消贴底，回到底部再恢复。

        @param value 当前滚动位置
        @author Kai
        @date 2026/08/31 17:36
        """
        if self._pinning_scroll:
            return
        bar = self.verticalScrollBar()
        self._stick_to_bottom = value >= max(0, bar.maximum() - 16)

    def _remove_empty(self) -> None:
        """
        移除空会话欢迎态。

        @author Kai
        @date 2026/08/05 16:44
        """
        if self._empty is None:
            return
        self.column_layout.removeWidget(self._empty)
        self._empty.hide()
        self._empty.setParent(None)
        self._empty.deleteLater()
        self._empty = None

    def _content_width(self) -> int:
        """
        计算当前消息列宽度。

        @return 像素宽度
        @author Kai
        @date 2026/08/05 16:44
        """
        viewport_width = max(0, self.viewport().width())
        if viewport_width <= 0:
            return CONTENT_MAX_WIDTH
        return max(360, min(CONTENT_MAX_WIDTH, viewport_width - 48))

    def _apply_content_width(self, widget: QWidget) -> None:
        """
        将当前消息列宽度同步给消息控件。

        @param widget 消息控件
        @author Kai
        @date 2026/08/05 16:44
        """
        width = self._content_width()
        self.column.setFixedWidth(width)
        if hasattr(widget, "set_content_width"):
            widget.set_content_width(width)  # type: ignore[attr-defined]

    def resizeEvent(self, event) -> None:  # noqa: N802
        """
        窗口尺寸变化时只重算各消息组件宽度。

        @param event 尺寸事件
        @author Kai
        @date 2026/08/05 16:44
        """
        super().resizeEvent(event)
        width = self._content_width()
        self.column.setFixedWidth(width)
        for widget in self._message_widgets:
            if hasattr(widget, "set_content_width"):
                widget.set_content_width(width)  # type: ignore[attr-defined]


class ChatDialog(QDialog):
    """
    AI 对话对话框。

    @author Kai
    @date 2026/09/01 10:30
    @description 只更新当前消息组件；可取消置顶并记住窗口大小
    """

    delta_signal = Signal(str)
    reply_ready = Signal(str)
    reply_failed = Signal(str)
    status_signal = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatDialog")
        self.setWindowTitle("AI 对话 · 考勤助手")
        self.setMinimumSize(960, 640)
        self.resize(1200, 800)
        # 是否置顶；默认不置顶，避免挡住其它窗口
        self._pinned = bool(getattr(S, "ai_chat_pin", False))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._pinned)
        self.setStyleSheet(CHAT_QSS)
        self._force_light_palette()

        self._session_id = ensure_default_session()
        self._busy = False
        self._stream_buf = ""
        self._current_ai_message: Optional[AssistantMessageWidget] = None
        self._tool_widgets: dict[str, ToolStatusWidget] = {}

        header = self._build_header()
        self.message_list = ChatMessageList()
        self.composer = ChatComposer()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.message_list, 1)
        layout.addWidget(self.composer)

        self.composer.send_requested.connect(self._send)
        self.delta_signal.connect(self.append_ai_delta)
        self.reply_ready.connect(self._on_reply)
        self.reply_failed.connect(self._on_fail)
        self.status_signal.connect(self._on_status)
        self._reload_messages()
        self._restore_geometry()
        QTimer.singleShot(0, self._sync_composer_width)

    def _sync_composer_width(self) -> None:
        """
        让底部输入框几乎铺满窗口宽度。

        @author Kai
        @date 2026/09/01 10:05
        """
        # 左右边距合计约 56px，输入卡片吃掉剩余宽度
        self.composer.set_content_width(max(720, self.width() - 56))

    def resizeEvent(self, event) -> None:  # noqa: N802
        """窗口拉宽时同步输入框宽度。"""
        super().resizeEvent(event)
        self._sync_composer_width()

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭时落盘置顶与几何。"""
        self._persist_window_state()
        super().closeEvent(event)

    def _restore_geometry(self) -> None:
        """
        恢复上次聊天窗口大小与位置。

        @author Kai
        @date 2026/09/01 10:30
        """
        raw = str(getattr(S, "ai_chat_geometry", "") or "").strip()
        if not raw:
            return
        try:
            blob = QByteArray.fromBase64(raw.encode("ascii"))
        except Exception:  # noqa: BLE001
            return
        if blob:
            self.restoreGeometry(blob)

    def _persist_window_state(self) -> None:
        """
        把置顶开关与窗口几何写入配置。

        @author Kai
        @date 2026/09/01 10:30
        """
        encoded = self.saveGeometry().toBase64()
        geo = bytes(encoded).decode("ascii")
        persist_chat_window_state(pin=self._pinned, geometry=geo)

    def _build_header(self) -> QWidget:
        """
        构建顶部标题栏。

        @return header widget
        @author Kai
        @date 2026/08/05 16:44
        """
        header = QWidget()
        header.setObjectName("ChatHeader")
        header.setFixedHeight(58)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 8, 0, 8)
        title_box.setSpacing(0)
        title = QLabel("AI 对话")
        title.setObjectName("ChatTitle")
        sub = QLabel("查考勤 · 记事项 · 搜网 · 读白名单文件")
        sub.setObjectName("ChatSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)

        btn_clear = QPushButton("清空")
        btn_clear.setObjectName("ChatGhost")
        self.btn_pin = QPushButton("置顶")
        self.btn_pin.setObjectName("ChatGhost")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(self._pinned)
        self.btn_pin.setToolTip("勾选后聊天窗口浮在其它窗口上面；关闭后记住")
        btn_close = QPushButton("关闭")
        btn_close.setObjectName("ChatGhost")
        btn_clear.clicked.connect(self._clear)
        self.btn_pin.toggled.connect(self._on_pin_toggled)
        btn_close.clicked.connect(self.accept)

        row = QHBoxLayout(header)
        row.setContentsMargins(20, 0, 12, 0)
        row.addLayout(title_box, 1)
        row.addWidget(btn_clear)
        row.addWidget(self.btn_pin)
        row.addWidget(btn_close)
        return header

    def _on_pin_toggled(self, pinned: bool) -> None:
        """
        切换聊天窗口是否置顶。

        @param pinned 是否置顶
        @author Kai
        @date 2026/09/01 10:30
        """
        self._pinned = bool(pinned)
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._pinned)
        if visible:
            self.show()
        self._persist_window_state()

    def _force_light_palette(self) -> None:
        """
        强制浅色调色板，避免 Windows 深色模式错配。

        @author Kai
        @date 2026/08/05 16:44
        """
        pal = QPalette(self.palette())
        bg = QColor("#F7F7F8")
        text = QColor("#111827")
        pal.setColor(QPalette.ColorRole.Window, bg)
        pal.setColor(QPalette.ColorRole.Base, bg)
        pal.setColor(QPalette.ColorRole.Text, text)
        pal.setColor(QPalette.ColorRole.WindowText, text)
        pal.setColor(QPalette.ColorRole.ButtonText, text)
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#2563EB"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(pal)

    def _reload_messages(self) -> None:
        """
        从数据库恢复近期消息。

        @author Kai
        @date 2026/08/05 16:44
        """
        self.message_list.clear_messages(show_empty=False)
        messages = recent_messages(
            self._session_id,
            limit=S.ai_chat_context_messages,
        )
        for msg in messages:
            if msg.role == "user":
                self.add_user_message(msg.content, persist=False)
            elif msg.role == "assistant":
                self.add_ai_message(msg.content, persist=False)
        if not messages:
            self.message_list.show_empty()

    def _history_for_agent(self) -> list[dict[str, str]]:
        """
        构造发给模型的历史（不含 system / 当前 user）。

        @return OpenAI 兼容消息列表
        @author Kai
        @date 2026/08/05 16:44
        """
        messages = recent_messages(
            self._session_id,
            limit=S.ai_chat_context_messages,
        )
        out: list[dict[str, str]] = []
        for msg in messages:
            if msg.role not in ("user", "assistant"):
                continue
            content = (msg.content or "").strip()
            if not content:
                continue
            out.append({"role": msg.role, "content": content})
        if out and out[-1]["role"] == "user":
            out.pop()
        return out

    def add_user_message(self, text: str, *, persist: bool = True) -> None:
        """
        添加用户消息。

        @param text 用户输入
        @param persist 是否写入数据库
        @author Kai
        @date 2026/08/05 16:44
        """
        if persist:
            add_message(self._session_id, "user", text)
        widget = UserMessageWidget(text)
        self.message_list.add_message_widget(widget)

    def add_ai_message(self, text: str, *, persist: bool = True) -> AssistantMessageWidget:
        """
        添加 AI 消息。

        @param text AI 回复
        @param persist 是否写入数据库
        @return AI 消息组件
        @author Kai
        @date 2026/08/05 16:44
        """
        if persist:
            add_message(self._session_id, "assistant", text)
        widget = AssistantMessageWidget(text)
        self.message_list.add_message_widget(widget)
        return widget

    def append_ai_delta(self, delta: str) -> None:
        """
        将流式增量追加到当前 AI 消息组件。

        @param delta 增量文本
        @author Kai
        @date 2026/08/05 16:44
        """
        if self._current_ai_message is None:
            self._current_ai_message = self.add_ai_message("", persist=False)
        if not self._current_ai_message.isVisible():
            self._current_ai_message.setVisible(True)
        self._stream_buf += delta or ""
        self._current_ai_message.append_content(delta or "")
        self.message_list.scroll_to_bottom()

    def start_tool(self, name: str) -> None:
        """
        添加或更新工具执行中状态。

        @param name 工具 id
        @author Kai
        @date 2026/08/05 16:44
        """
        if name in self._tool_widgets:
            self._tool_widgets[name].start_tool(name)
            return
        widget = ToolStatusWidget(name)
        self._tool_widgets[name] = widget
        self.message_list.add_message_widget(widget)

    def finish_tool(
        self,
        name: str,
        *,
        ok: bool = True,
        error: str = "",
    ) -> None:
        """
        标记工具完成或失败。

        @param name 工具 id
        @param ok 是否成功
        @param error 失败原因
        @author Kai
        @date 2026/09/01 10:20
        """
        if name not in self._tool_widgets:
            self.start_tool(name)
        self._tool_widgets[name].finish_tool(name, ok=ok, error=error)
        self.message_list.scroll_to_bottom()

    def _send(self, text: str) -> None:
        """
        发送用户消息并启动 Agent 线程。

        @param text 用户输入
        @author Kai
        @date 2026/08/05 16:44
        """
        if self._busy:
            return
        if not S.ai_enable or not S.ai_enable_chat:
            self.composer.set_status("AI 对话已关闭，请到设置开启")
            return
        content = (text or "").strip()
        if not content:
            return

        self.composer.clear()
        self.add_user_message(content)
        self._busy = True
        self._stream_buf = ""
        self._tool_widgets.clear()
        self._current_ai_message = self.add_ai_message("", persist=False)
        self._current_ai_message.setVisible(False)
        self.composer.set_busy(True)
        self.composer.set_status("思考中…")

        history = self._history_for_agent()

        def worker() -> None:
            def on_delta(piece: str) -> None:
                self.delta_signal.emit(piece)

            def on_status(status: str) -> None:
                self.status_signal.emit(status)

            self.status_signal.emit("思考中…")
            result = run_agent(
                content,
                history=history,
                on_delta=on_delta,
                on_status=on_status,
                stream=True,
            )
            if result.get("ok"):
                reply = str(result.get("reply") or self._stream_buf or "")
                self.reply_ready.emit(reply)
            else:
                self.reply_failed.emit(str(result.get("error") or "未知错误"))

        threading.Thread(target=worker, daemon=True, name="ai-chat").start()

    def _on_status(self, status: str) -> None:
        """
        处理 Agent 状态回调。

        @param status 状态文本
        @author Kai
        @date 2026/08/05 16:44
        """
        text = (status or "").strip()
        # 工具卡片走专用协议，不把 tool_fail: 原文写到输入栏
        if not (
            text.startswith("tool_start:")
            or text.startswith("tool_done:")
            or text.startswith("tool_fail:")
        ):
            self.composer.set_status(text)
        if text.startswith("tool_start:"):
            self.start_tool(text.split(":", 1)[1].strip())
            return
        if text.startswith("tool_fail:"):
            rest = text.split(":", 1)[1]
            name, _, err = rest.partition("|")
            self.finish_tool(name.strip(), ok=False, error=err.strip())
            return
        if text.startswith("tool_done:"):
            self.finish_tool(text.split(":", 1)[1].strip(), ok=True)
            return
        if text.startswith("调用工具："):
            for name in text.replace("调用工具：", "", 1).split(","):
                name = name.strip()
                if name:
                    self.start_tool(name)
            return
        if text in ("生成中…", "汇总中…", "写作中…"):
            for widget in self._tool_widgets.values():
                if not widget.is_done():
                    widget.finish_tool()

    def _on_reply(self, reply: str) -> None:
        """
        Agent 完成后落库并收尾。

        @param reply 最终回复
        @author Kai
        @date 2026/08/05 16:44
        """
        final = (reply or self._stream_buf or "（空回复）").strip()
        if self._current_ai_message is None:
            self._current_ai_message = self.add_ai_message("", persist=False)
        self._current_ai_message.setVisible(True)
        self._current_ai_message.set_content(final)
        add_message(self._session_id, "assistant", final)
        self._finish_round("")

    def _on_fail(self, err: str) -> None:
        """
        Agent 失败后显示错误消息。

        @param err 错误描述
        @author Kai
        @date 2026/08/05 16:44
        """
        partial = self._stream_buf.strip()
        final = f"{partial}\n\n[错误] {err}" if partial else f"[错误] {err}"
        if self._current_ai_message is None:
            self._current_ai_message = self.add_ai_message("", persist=False)
        self._current_ai_message.setVisible(True)
        self._current_ai_message.set_content(final)
        add_message(self._session_id, "assistant", final)
        self._finish_round(f"失败：{err}")

    def _finish_round(self, status: str) -> None:
        """
        结束当前对话轮次。

        @param status 底部状态文案
        @author Kai
        @date 2026/08/05 16:44
        """
        self._busy = False
        self._stream_buf = ""
        self._current_ai_message = None
        self.composer.set_busy(False)
        self.composer.set_status(status)
        self.message_list.scroll_to_bottom()

    def _clear(self) -> None:
        """
        清空当前会话。

        @author Kai
        @date 2026/08/05 16:44
        """
        if self._busy:
            return
        clear_session(self._session_id)
        self._stream_buf = ""
        self._current_ai_message = None
        self._tool_widgets.clear()
        self.message_list.clear_messages()
        self.composer.set_status("会话已清空")
