# Copyright (c) iGroup.
# All rights reserved.
"""
托盘里的随手海龟汤。

@author Kai
@date 2026/10/15 15:53
@description 单题、单按钮，揭晓后立即换题；不打开二级窗口
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import playground as game
from ..activity_tracker import get_activity_tracker
from ..config import S

# 沿用轻卡片尺寸，换题不改变左键页面的布局。
CARD_HEIGHT = 116


class CompanionCard(QWidget):
    """
    可持续换题的轻量海龟汤卡片。

    @author Kai
    @date 2026/10/15 15:53
    @description 未完成的题目保留，足迹只记录实际揭晓，不把看过答案算猜中
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """
        创建三行题面与一个原地操作按钮。

        @param parent 所属详情卡
        @author Kai
        @date 2026/10/15 15:53
        """
        super().__init__(parent)
        # 临时线索绑定题局序号，刷新和换题不会串入另一道题。
        self._state: dict[str, Any] = {}
        self._hint_shown = False
        self._round = 0
        self._last_refresh = time.monotonic()
        self.setFixedHeight(CARD_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "CompanionCard { background: #162435; border-radius: 9px; }"
            "QLabel { background: transparent; border: none; color: #DCE6F0; font-size: 12px; }"
            "QPushButton { color: #73DDB7; background: #1D3B3B; border: none;"
            "border-radius: 5px; padding: 3px 10px; font-size: 12px; }"
            "QPushButton:hover { background: #28504B; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(3)
        self.heading = QLabel()
        self.heading.setStyleSheet("color: #8DA7B7; font-size: 11px;")
        self.heading.setFixedHeight(16)
        layout.addWidget(self.heading)
        self.body = QLabel()
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setWordWrap(True)
        self.body.setFixedHeight(48)
        layout.addWidget(self.body)
        row = QHBoxLayout()
        self.action = QPushButton()
        self.action.setFixedHeight(24)
        self.action.clicked.connect(self._act)
        row.addWidget(self.action)
        row.addStretch()
        self.note = QLabel()
        self.note.setStyleSheet("color: #7891A4; font-size: 10px;")
        row.addWidget(self.note)
        layout.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """
        同步当前题局和自然成长，不调用网络服务。

        @author Kai
        @date 2026/10/15 15:53
        """
        if S.fun_enable and S.fun_usage_link and S.fun_card_mode != "off":
            get_activity_tracker().flush()
            try:
                game.claim_growth()
            except ValueError:
                pass
        self._state = game.snapshot()
        if self._round != self._state["puzzle_round"]:
            self._hint_shown = False
        self._round = self._state["puzzle_round"]
        self._last_refresh = time.monotonic()
        self._render()

    def _render(self) -> None:
        """
        在题面、线索和谜底间切换，完成后立即提供下一题。

        @author Kai
        @date 2026/10/15 15:53
        """
        puzzle = self._state["puzzle"]
        progress = self._state["progress"]
        ended = progress["revealed"] or progress["solved"]
        self.heading.setText(("原来如此 · " if ended else "海龟汤 · ") + puzzle["title"])
        text = puzzle["answer"] if ended else (puzzle["hint"] if self._hint_shown else puzzle["zh"])
        self.body.setText(text)
        # 看线索时悬停可重读题面，无需增加输入框或另一个按钮。
        self.body.setToolTip(puzzle["zh"] if self._hint_shown and not ended else "")
        self.action.setText("再来一题" if ended else ("揭晓谜底" if self._hint_shown else "给点线索"))
        self.note.setText(f"已揭晓 {self._state['puzzle_completed']} 题" if ended else "")

    def _act(self) -> None:
        """
        推进当前步骤并以题局序号防止旧界面跳过新题。

        @author Kai
        @date 2026/10/15 15:53
        """
        progress = self._state["progress"]
        try:
            if progress["revealed"] or progress["solved"]:
                game.next_puzzle(expected_round=self._round)
            elif self._hint_shown:
                game.reveal_puzzle(expected_round=self._round)
            else:
                self._hint_shown = True
        except ValueError:
            # 另一处已推进题局时，仅刷新，不连续跨过未读题目。
            pass
        self.refresh()

    def showEvent(self, event: Any) -> None:  # noqa: N802
        """
        打开时继续未完成题；已揭晓则给新题，不一直挂着旧答案。

        @param event Qt 显示事件
        @author Kai
        @date 2026/10/15 15:53
        """
        self.refresh()
        progress = self._state["progress"]
        if progress["revealed"] or progress["solved"]:
            try:
                game.next_puzzle(expected_round=self._round)
            except ValueError:
                pass
            self.refresh()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        """
        隐藏后停止查询本地进度。

        @param event Qt 隐藏事件
        @author Kai
        @date 2026/10/15 15:53
        """
        self._timer.stop()
        super().hideEvent(event)
