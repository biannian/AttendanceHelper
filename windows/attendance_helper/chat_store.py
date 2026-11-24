# Copyright (c) iGroup China.
# All rights reserved.
"""
AI 对话会话与消息 SQLite 存取。

@author Kai
@date 2026/08/05 14:15
@description chat_sessions / chat_messages
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .db import db_conn, init_db


@dataclass
class ChatMessage:
    """
    单条对话消息。

    @author Kai
    @date 2026/08/05 14:15
    @description 对应 chat_messages 一行
    """

    id: int
    session_id: int
    role: str
    content: str
    tool_calls: Optional[str]
    created_at: str


def _now_iso() -> str:
    """当前本地时间 ISO。"""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def ensure_default_session() -> int:
    """
    确保存在默认会话并返回 session_id。

    @return 会话 id
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM chat_sessions ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row:
            return int(row["id"])
        now = _now_iso()
        cur = conn.execute(
            """
            INSERT INTO chat_sessions(title, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            ("默认会话", now, now),
        )
        return int(cur.lastrowid)


def add_message(
    session_id: int,
    role: str,
    content: str,
    *,
    tool_calls: Any = None,
) -> ChatMessage:
    """
    追加一条消息。

    @param session_id 会话 id
    @param role user / assistant / system / tool
    @param content 文本内容
    @param tool_calls 可选 tool_calls 结构
    @return 新建消息
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    now = _now_iso()
    tool_json = None
    if tool_calls is not None:
        tool_json = (
            tool_calls
            if isinstance(tool_calls, str)
            else json.dumps(tool_calls, ensure_ascii=False)
        )
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO chat_messages(
                session_id, role, content, tool_calls, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content or "", tool_json, now),
        )
        msg_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        row = conn.execute(
            "SELECT * FROM chat_messages WHERE id = ?", (msg_id,)
        ).fetchone()
    return ChatMessage(
        id=int(row["id"]),
        session_id=int(row["session_id"]),
        role=str(row["role"]),
        content=str(row["content"] or ""),
        tool_calls=row["tool_calls"],
        created_at=str(row["created_at"]),
    )


def recent_messages(session_id: int, limit: int = 20) -> list[ChatMessage]:
    """
    取最近 N 条消息（按时间正序返回）。

    @param session_id 会话 id
    @param limit 条数上限
    @return 消息列表
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    lim = max(1, int(limit))
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (session_id, lim),
        ).fetchall()
    return [
        ChatMessage(
            id=int(r["id"]),
            session_id=int(r["session_id"]),
            role=str(r["role"]),
            content=str(r["content"] or ""),
            tool_calls=r["tool_calls"],
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


def clear_session(session_id: int) -> None:
    """
    清空会话消息。

    @param session_id 会话 id
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
