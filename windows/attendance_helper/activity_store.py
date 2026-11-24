# Copyright (c) iGroup China.
# All rights reserved.
"""
使用时长的 SQLite 读写。

@author Kai
@date 2026/09/29 15:12
@description 按天累计软件秒数，另存用户手动归类；不保存窗口标题
"""

from __future__ import annotations

from datetime import date, datetime

from .activity_classify import CAT_REST, CAT_SLACK, CAT_UNKNOWN, CAT_WORK, REST_APP_KEY
from .db import db_conn

# 允许写入规则表的归类
_RULE_CATEGORIES = {CAT_WORK, CAT_SLACK, CAT_UNKNOWN}
# meta 表里「暂停统计」记到哪一天
_PAUSED_DAY_KEY = "activity_paused_day"


def _now_iso() -> str:
    """
    当前本地时间，写 updated_at。

    @return YYYY-MM-DD HH:MM:SS
    @author Kai
    @date 2026/09/29 15:12
    """
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _meta_get(key: str) -> str:
    """
    读取 meta 值。

    @param key 键
    @return 值；不存在时为空串
    @author Kai
    @date 2026/09/29 15:12
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return ""
    return str(row["value"] or "")


def _meta_set(key: str, value: str) -> None:
    """
    写入 meta 值。

    @param key 键
    @param value 值
    @author Kai
    @date 2026/09/29 15:12
    """
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def add_usage_batch(rows: list[tuple[str, str, str, int]]) -> None:
    """
    把若干秒数累加到当日软件上。

    @param rows (day, app_key, display_name, seconds)
    @author Kai
    @date 2026/09/29 15:12
    """
    pending = [row for row in rows if int(row[3]) > 0]
    if not pending:
        return
    now = _now_iso()
    payload = [
        (day, app_key, display_name, int(seconds), now)
        for day, app_key, display_name, seconds in pending
    ]
    with db_conn() as conn:
        conn.executemany(
            """
            INSERT INTO activity_usage(
                day, app_key, display_name, seconds, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day, app_key) DO UPDATE SET
                seconds = activity_usage.seconds + excluded.seconds,
                display_name = excluded.display_name,
                updated_at = excluded.updated_at
            """,
            payload,
        )


def list_usage(day: str) -> list[tuple[str, str, int]]:
    """
    列出某一天已落库的使用记录。

    @param day YYYY-MM-DD
    @return (app_key, display_name, seconds)，按时长从长到短
    @author Kai
    @date 2026/09/29 15:12
    """
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT app_key, display_name, seconds
            FROM activity_usage
            WHERE day = ?
            ORDER BY seconds DESC
            """,
            (day,),
        ).fetchall()
    return [
        (str(row["app_key"]), str(row["display_name"]), int(row["seconds"]))
        for row in rows
    ]


def delete_day(day: str) -> None:
    """
    删除某一天的全部使用记录。

    @param day YYYY-MM-DD
    @author Kai
    @date 2026/09/29 15:12
    """
    with db_conn() as conn:
        conn.execute("DELETE FROM activity_usage WHERE day = ?", (day,))


def load_rules() -> dict[str, str]:
    """
    读取用户手动归类。

    @return app_key → work/slack/unknown
    @author Kai
    @date 2026/09/29 15:12
    """
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT app_key, category FROM activity_rules"
        ).fetchall()
    return {str(row["app_key"]): str(row["category"]) for row in rows}


def set_rule(app_key: str, category: str) -> None:
    """
    记住用户对某个软件的归类。休息行不能改。

    @param app_key 使用记录键
    @param category work / slack / unknown
    @author Kai
    @date 2026/09/29 15:12
    """
    if app_key == REST_APP_KEY or category not in _RULE_CATEGORIES:
        return
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO activity_rules(app_key, category, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(app_key) DO UPDATE SET
                category = excluded.category,
                updated_at = excluded.updated_at
            """,
            (app_key, category, _now_iso()),
        )


def clear_rule(app_key: str) -> None:
    """
    取消手动归类，恢复内置默认。

    @param app_key 使用记录键
    @author Kai
    @date 2026/09/29 15:12
    """
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM activity_rules WHERE app_key = ?", (app_key,)
        )


def is_paused_today(day: str | None = None) -> bool:
    """
    今天是否暂停了使用统计。跨日自动恢复。

    @param day 对比用的日期，默认今天
    @return 暂停中为 True
    @author Kai
    @date 2026/09/29 15:12
    """
    today = day or date.today().isoformat()
    return _meta_get(_PAUSED_DAY_KEY) == today


def set_paused_today(paused: bool, day: str | None = None) -> None:
    """
    暂停或恢复今天的使用统计。

    @param paused 是否暂停
    @param day 写入的日期，默认今天
    @author Kai
    @date 2026/09/29 15:12
    """
    today = day or date.today().isoformat()
    _meta_set(_PAUSED_DAY_KEY, today if paused else "")
