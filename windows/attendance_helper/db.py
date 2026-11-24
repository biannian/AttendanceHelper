# Copyright (c) iGroup China.
# All rights reserved.
"""
SQLite 连接与 schema 迁移。

@author Kai
@date 2026/09/29 15:10
@description helper.db：事项、对话、成就、使用时长
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from .paths import DB_PATH, LOG

# 当前 schema 版本（2：使用时长与归类规则）
SCHEMA_VERSION = 2

_LOCK = threading.RLock()
_INITIALIZED = False


def _connect() -> sqlite3.Connection:
    """
    打开数据库连接（行级工厂为 Row）。

    @return sqlite3 连接
    @author Kai
    @date 2026/08/05 14:15
    """
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """
    执行建表与版本迁移。

    @param conn 数据库连接
    @author Kai
    @date 2026/08/05 14:15
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'todo',
            due_at TEXT,
            remind_at TEXT,
            remind_mode TEXT NOT NULL DEFAULT 'fixed',
            before_minutes INTEGER NOT NULL DEFAULT 30,
            workday_time TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS item_remind_log (
            item_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            fired_at TEXT NOT NULL,
            PRIMARY KEY (item_id, day),
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '默认会话',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS achievements (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            progress INTEGER NOT NULL DEFAULT 0,
            target INTEGER NOT NULL DEFAULT 1,
            unlocked_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, id);

        CREATE TABLE IF NOT EXISTS activity_usage (
            day TEXT NOT NULL,
            app_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            seconds INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (day, app_key)
        );

        CREATE TABLE IF NOT EXISTS activity_rules (
            app_key TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    else:
        # 预留后续 ALTER；当前仅写回最新版本号
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(SCHEMA_VERSION),),
        )
    conn.commit()


def init_db() -> None:
    """
    初始化数据库（幂等）。

    @author Kai
    @date 2026/08/05 14:15
    """
    global _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            _migrate(conn)
            LOG.info("SQLite 已就绪 path=%s", DB_PATH)
        finally:
            conn.close()
        _INITIALIZED = True


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """
    获取带锁的数据库连接上下文。

    @return 连接上下文管理器
    @author Kai
    @date 2026/08/05 14:15
    """
    init_db()
    with _LOCK:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
