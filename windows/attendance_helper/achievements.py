# Copyright (c) iGroup China.
# All rights reserved.
"""
轻量成就进度（SQLite）。

@author Kai
@date 2026/08/05 14:15
@description 首次创建事项、准时收尾、事项清零等
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .db import db_conn, init_db

# 预置成就定义：(id, title, description, target)
ACHIEVEMENT_DEFS: list[tuple[str, str, str, int]] = [
    ("first_capture", "初出茅庐", "完成第一次事项创建", 1),
    ("wrapup_ontime_3", "准时收尾达人", "准时完成收尾 3 次", 3),
    ("items_clear_streak_3", "清空大师", "连续工作日事项清零 3 天", 3),
]


@dataclass
class Achievement:
    """
    成就记录。

    @author Kai
    @date 2026/08/05 14:15
    @description 进度与解锁时间
    """

    id: str
    title: str
    description: str
    progress: int
    target: int
    unlocked_at: Optional[str]

    @property
    def unlocked(self) -> bool:
        """是否已解锁。"""
        return bool(self.unlocked_at)


def _now_iso() -> str:
    """当前本地时间 ISO。"""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def ensure_achievements() -> None:
    """
    写入预置成就行（幂等）。

    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with db_conn() as conn:
        for aid, title, desc, target in ACHIEVEMENT_DEFS:
            exists = conn.execute(
                "SELECT 1 FROM achievements WHERE id = ?", (aid,)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO achievements(
                    id, title, description, progress, target, unlocked_at
                ) VALUES (?, ?, ?, 0, ?, NULL)
                """,
                (aid, title, desc, target),
            )


def list_achievements() -> list[Achievement]:
    """
    列出全部成就。

    @return 成就列表
    @author Kai
    @date 2026/08/05 14:15
    """
    ensure_achievements()
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM achievements ORDER BY id"
        ).fetchall()
    return [
        Achievement(
            id=str(r["id"]),
            title=str(r["title"]),
            description=str(r["description"] or ""),
            progress=int(r["progress"] or 0),
            target=int(r["target"] or 1),
            unlocked_at=r["unlocked_at"],
        )
        for r in rows
    ]


def bump_achievement(achievement_id: str, delta: int = 1) -> Optional[Achievement]:
    """
    增加成就进度；达到目标时写入解锁时间。

    @param achievement_id 成就 id
    @param delta 增量
    @return 更新后的成就；不存在返回 None
    @author Kai
    @date 2026/08/05 14:15
    """
    ensure_achievements()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM achievements WHERE id = ?", (achievement_id,)
        ).fetchone()
        if not row:
            return None
        progress = int(row["progress"] or 0) + max(0, int(delta))
        target = max(1, int(row["target"] or 1))
        unlocked = row["unlocked_at"]
        if progress >= target and not unlocked:
            unlocked = _now_iso()
            progress = target
        conn.execute(
            """
            UPDATE achievements
            SET progress = ?, unlocked_at = ?
            WHERE id = ?
            """,
            (progress, unlocked, achievement_id),
        )
        updated = conn.execute(
            "SELECT * FROM achievements WHERE id = ?", (achievement_id,)
        ).fetchone()
    return Achievement(
        id=str(updated["id"]),
        title=str(updated["title"]),
        description=str(updated["description"] or ""),
        progress=int(updated["progress"] or 0),
        target=int(updated["target"] or 1),
        unlocked_at=updated["unlocked_at"],
    )


def set_achievement_progress(
    achievement_id: str,
    progress: int,
) -> Optional[Achievement]:
    """
    直接设置成就进度（用于连续天数类）。

    @param achievement_id 成就 id
    @param progress 进度值
    @return 更新后成就
    @author Kai
    @date 2026/08/05 14:15
    """
    ensure_achievements()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM achievements WHERE id = ?", (achievement_id,)
        ).fetchone()
        if not row:
            return None
        target = max(1, int(row["target"] or 1))
        progress = max(0, min(int(progress), target))
        unlocked = row["unlocked_at"]
        if progress >= target and not unlocked:
            unlocked = _now_iso()
        conn.execute(
            """
            UPDATE achievements
            SET progress = ?, unlocked_at = ?
            WHERE id = ?
            """,
            (progress, unlocked, achievement_id),
        )
        updated = conn.execute(
            "SELECT * FROM achievements WHERE id = ?", (achievement_id,)
        ).fetchone()
    return Achievement(
        id=str(updated["id"]),
        title=str(updated["title"]),
        description=str(updated["description"] or ""),
        progress=int(updated["progress"] or 0),
        target=int(updated["target"] or 1),
        unlocked_at=updated["unlocked_at"],
    )
