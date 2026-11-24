# Copyright (c) iGroup China.
# All rights reserved.
"""
事项 / 提醒 SQLite 存取。

@author Kai
@date 2026/08/05 14:15
@description 支持固定时间、截止前、工作日三种提醒模式
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .db import db_conn, init_db


# 提醒模式常量
REMIND_FIXED = "fixed"
REMIND_BEFORE_DUE = "before_due"
REMIND_WORKDAY = "workday"
STATUS_OPEN = "open"
STATUS_DONE = "done"


@dataclass
class ItemRecord:
    """
    事项记录。

    @author Kai
    @date 2026/08/05 14:15
    @description 对应 items 表一行
    """

    id: int
    title: str
    kind: str
    due_at: Optional[str]
    remind_at: Optional[str]
    remind_mode: str
    before_minutes: int
    workday_time: Optional[str]
    status: str
    notes: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化字典（供 AI 工具返回）。"""
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "due_at": self.due_at,
            "remind_at": self.remind_at,
            "remind_mode": self.remind_mode,
            "before_minutes": self.before_minutes,
            "workday_time": self.workday_time,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_item(row: Any) -> ItemRecord:
    """
    Row → ItemRecord。

    @param row sqlite Row
    @return ItemRecord
    @author Kai
    @date 2026/08/05 14:15
    """
    return ItemRecord(
        id=int(row["id"]),
        title=str(row["title"]),
        kind=str(row["kind"]),
        due_at=row["due_at"],
        remind_at=row["remind_at"],
        remind_mode=str(row["remind_mode"]),
        before_minutes=int(row["before_minutes"] or 30),
        workday_time=row["workday_time"],
        status=str(row["status"]),
        notes=str(row["notes"] or ""),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _now_iso() -> str:
    """当前本地时间 ISO 字符串。"""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def create_item(
    title: str,
    *,
    kind: str = "todo",
    due_at: Optional[str] = None,
    remind_at: Optional[str] = None,
    remind_mode: str = REMIND_FIXED,
    before_minutes: int = 30,
    workday_time: Optional[str] = None,
    notes: str = "",
) -> ItemRecord:
    """
    创建事项。

    @param title 标题
    @param kind todo / reminder
    @param due_at 截止时间 ISO
    @param remind_at 提醒时间 ISO
    @param remind_mode 提醒模式
    @param before_minutes 截止前提醒分钟
    @param workday_time 工作日提醒 HH:MM
    @param notes 备注
    @return 新建记录
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    now = _now_iso()
    mode = remind_mode if remind_mode in (
        REMIND_FIXED,
        REMIND_BEFORE_DUE,
        REMIND_WORKDAY,
    ) else REMIND_FIXED
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO items(
                title, kind, due_at, remind_at, remind_mode,
                before_minutes, workday_time, status, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (title or "").strip() or "未命名事项",
                kind if kind in ("todo", "reminder") else "todo",
                due_at,
                remind_at,
                mode,
                max(0, int(before_minutes)),
                workday_time,
                STATUS_OPEN,
                notes or "",
                now,
                now,
            ),
        )
        item_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
    return _row_to_item(row)


def list_items(
    *,
    status: str = STATUS_OPEN,
    today_only: bool = False,
) -> list[ItemRecord]:
    """
    列出事项。

    @param status open / done / all
    @param today_only 仅今日相关（截止或提醒落在今天，或工作日模式）
    @return 事项列表
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    today = datetime.now().date().isoformat()
    with db_conn() as conn:
        if status == "all":
            rows = conn.execute(
                "SELECT * FROM items ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM items WHERE status = ? ORDER BY id DESC",
                (status,),
            ).fetchall()
    items = [_row_to_item(r) for r in rows]
    if not today_only:
        return items
    filtered: list[ItemRecord] = []
    for it in items:
        if it.remind_mode == REMIND_WORKDAY:
            filtered.append(it)
            continue
        for ts in (it.due_at, it.remind_at, it.created_at):
            if ts and str(ts).startswith(today):
                filtered.append(it)
                break
    return filtered


def get_item(item_id: int) -> Optional[ItemRecord]:
    """
    按 id 取事项。

    @param item_id 主键
    @return 记录或 None
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        ).fetchone()
    return _row_to_item(row) if row else None


def complete_item(
    *,
    item_id: Optional[int] = None,
    title_query: Optional[str] = None,
) -> Optional[ItemRecord]:
    """
    完成事项（按 id 或标题模糊匹配最新一条 open）。

    @param item_id 主键
    @param title_query 标题关键字
    @return 完成后的记录；未找到返回 None
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    now = _now_iso()
    with db_conn() as conn:
        row = None
        if item_id is not None:
            row = conn.execute(
                "SELECT * FROM items WHERE id = ? AND status = ?",
                (item_id, STATUS_OPEN),
            ).fetchone()
        elif title_query:
            q = f"%{title_query.strip()}%"
            row = conn.execute(
                """
                SELECT * FROM items
                WHERE status = ? AND title LIKE ?
                ORDER BY id DESC LIMIT 1
                """,
                (STATUS_OPEN, q),
            ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE items SET status = ?, updated_at = ? WHERE id = ?",
            (STATUS_DONE, now, int(row["id"])),
        )
        updated = conn.execute(
            "SELECT * FROM items WHERE id = ?", (int(row["id"]),)
        ).fetchone()
    return _row_to_item(updated)


def complete_all_open() -> int:
    """
    将全部未完成事项标为完成。

    @return 更新条数
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    now = _now_iso()
    with db_conn() as conn:
        cur = conn.execute(
            "UPDATE items SET status = ?, updated_at = ? WHERE status = ?",
            (STATUS_DONE, now, STATUS_OPEN),
        )
        return int(cur.rowcount or 0)


def defer_open_items_to_tomorrow() -> int:
    """
    收工时将未完成事项的提醒顺延到明天（同钟点）。

    @return 更新条数
    @author Kai
    @date 2026/08/05 15:03
    """
    from datetime import datetime, timedelta

    init_db()
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    updated = 0
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE status = ?", (STATUS_OPEN,)
        ).fetchall()
        for row in rows:
            mode = str(row["remind_mode"] or REMIND_FIXED)
            # 工作日模式本身会跨天，无需改时间
            if mode == REMIND_WORKDAY:
                continue
            remind_at = row["remind_at"]
            due_at = row["due_at"]
            new_remind = remind_at
            new_due = due_at
            if remind_at:
                try:
                    raw = str(remind_at).replace("T", " ")[:19]
                    dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
                    dt2 = datetime.combine(tomorrow, dt.time())
                    new_remind = dt2.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            if due_at:
                try:
                    raw = str(due_at).replace("T", " ")[:19]
                    dt = datetime.strptime(raw[:16], "%Y-%m-%d %H:%M")
                    dt2 = datetime.combine(tomorrow, dt.time())
                    new_due = dt2.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            conn.execute(
                """
                UPDATE items
                SET remind_at = ?, due_at = ?, updated_at = ?,
                    notes = CASE
                        WHEN notes LIKE '%[已顺延]%' THEN notes
                        ELSE trim(notes || ' [已顺延]')
                    END
                WHERE id = ?
                """,
                (new_remind, new_due, _now_iso(), int(row["id"])),
            )
            updated += 1
    return updated


def delete_item(item_id: int) -> bool:
    """
    删除事项。

    @param item_id 主键
    @return 是否删除成功
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return int(cur.rowcount or 0) > 0


def count_open() -> int:
    """
    未完成事项数量。

    @return 数量
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM items WHERE status = ?",
            (STATUS_OPEN,),
        ).fetchone()
    return int(row["c"] if row else 0)


def mark_remind_fired(item_id: int, day: str) -> bool:
    """
    标记某事项某日已提醒（首次返回 True）。

    @param item_id 事项 id
    @param day YYYY-MM-DD
    @return 是否本次新标记
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    now = _now_iso()
    with db_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM item_remind_log WHERE item_id = ? AND day = ?",
            (item_id, day),
        ).fetchone()
        if exists:
            return False
        conn.execute(
            """
            INSERT INTO item_remind_log(item_id, day, fired_at)
            VALUES (?, ?, ?)
            """,
            (item_id, day, now),
        )
        return True


def open_items_for_remind() -> list[ItemRecord]:
    """
    取出所有待提醒的 open 事项。

    @return 事项列表
    @author Kai
    @date 2026/08/05 14:15
    """
    return list_items(status=STATUS_OPEN, today_only=False)
