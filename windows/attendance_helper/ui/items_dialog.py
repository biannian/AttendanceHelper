# Copyright (c) iGroup China.
# All rights reserved.
"""
今日事项列表对话框。

@author Kai
@date 2026/08/05 14:15
@description 勾选完成 / 删除
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .. import items_store


class ItemsDialog(QDialog):
    """
    事项列表。

    @author Kai
    @date 2026/08/05 14:15
    @description 展示 open 事项并支持完成/删除
    """

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setWindowTitle("今日事项")
        self.setMinimumSize(440, 360)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.list = QListWidget()
        self.btn_refresh = QPushButton("刷新")
        self.btn_done = QPushButton("标记完成")
        self.btn_del = QPushButton("删除")
        self.btn_close = QPushButton("关闭")

        row = QHBoxLayout()
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_done)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        row.addWidget(self.btn_close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(row)

        self.btn_refresh.clicked.connect(self.reload)
        self.btn_done.clicked.connect(self._complete_selected)
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_close.clicked.connect(self.accept)
        self.reload()

    def reload(self) -> None:
        """重新加载 open 事项。"""
        self.list.clear()
        for item in items_store.list_items(status="open"):
            label = f"[{item.id}] {item.title}"
            extra = item.remind_mode
            if item.remind_at:
                extra += f" @ {item.remind_at}"
            elif item.due_at:
                extra += f" 截止 {item.due_at}"
            elif item.workday_time:
                extra += f" 工作日 {item.workday_time}"
            else:
                extra += "（无提醒时间，不会响）"
            row = QListWidgetItem(f"{label}\n  {extra}")
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            self.list.addItem(row)

    def _selected_id(self) -> Optional[int]:
        """当前选中事项 id。"""
        cur = self.list.currentItem()
        if not cur:
            return None
        val = cur.data(Qt.ItemDataRole.UserRole)
        return int(val) if val is not None else None

    def _complete_selected(self) -> None:
        """完成选中。"""
        iid = self._selected_id()
        if iid is None:
            return
        items_store.complete_item(item_id=iid)
        self.reload()

    def _delete_selected(self) -> None:
        """删除选中。"""
        iid = self._selected_id()
        if iid is None:
            return
        items_store.delete_item(iid)
        self.reload()
