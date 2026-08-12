# -*- coding: utf-8 -*-
"""SQLite 连接管理 + 建表（v3.0 Phase 3 记忆系统底座）。

设计说明：
    - 单例风格：模块级维护全局连接（Streamlit 脚本每次 rerun 都会重新 import，
      但 SQLite 连接在同一进程内可复用；为稳妥起见，每次获取时校验连接存活）。
    - 表结构：
        user_profile   用户档案（key-value，如昵称/偏好）
        events         历史事件（一次编译的完整快照）
        preferences    长期偏好（从历史中提炼的关键偏好）
    - WAL 模式：读写并发更稳（Streamlit 多会话下更安全）。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


def default_db_path() -> Path:
    """默认数据库位置：项目根目录 / data / reality.db。

    归到 data/ 子目录，避免根目录被 sqlite 文件弄乱。
    """
    root = Path(__file__).resolve().parent.parent.parent   # core/database -> 项目根
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "reality.db"


# ----------------------------------------------------------------------------
# 建表 SQL（集中放一处，方便一眼看到全部 schema）
# ----------------------------------------------------------------------------
SCHEMA_SQL = """
-- 用户档案：key-value 存储（昵称 / 习惯 / 偏好等）
CREATE TABLE IF NOT EXISTS user_profile (
    key        TEXT PRIMARY KEY,      -- 档案键名，如 'nickname'
    value      TEXT NOT NULL DEFAULT '',  -- 档案值
    updated_at TEXT NOT NULL          -- 更新时间（ISO 8601）
);

-- 历史事件：一次编译的完整快照
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,        -- 编译日期（ISO）
    source      TEXT NOT NULL,        -- 用户原文（清洗后）
    summary     TEXT NOT NULL DEFAULT '',  -- AI 复盘
    advice      TEXT NOT NULL DEFAULT '',   -- AI 建议
    attributes  TEXT NOT NULL DEFAULT '{}', -- 属性面板 JSON（hp/mp/gold/exp/level）
    tags        TEXT NOT NULL DEFAULT '[]', -- 标签 JSON 数组
    world_label TEXT NOT NULL DEFAULT '',   -- 世界观名称
    created_at  TEXT NOT NULL          -- 记录写入时间（ISO）
);

-- 长期偏好：从历史中提炼的关键偏好
CREATE TABLE IF NOT EXISTS preferences (
    key         TEXT PRIMARY KEY,     -- 偏好键名，如 'recurring_tag'
    value       TEXT NOT NULL DEFAULT '',  -- 偏好内容
    weight      REAL NOT NULL DEFAULT 1.0, -- 权重（出现频率等）
    updated_at  TEXT NOT NULL          -- 更新时间（ISO）
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
"""


class Database:
    """SQLite 连接管理：打开 / 建表 / 关闭 / 线程安全。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or default_db_path())
        # 用 RLock（可重入锁）：wipe() 等持锁方法内部还会调用 self.conn，
        # 普通 Lock 会死锁；RLock 允许同一线程重入。
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._open()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def _open(self) -> None:
        """打开连接并建表。连接用 check_same_thread=False + 全局锁保护。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row     # 按列名取字段，代码更可读
        # WAL：读写不互相阻塞（多会话场景更稳）；journal 模式避免中间态可见
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        """获取连接；若连接已关闭则重新打开（Streamlit 重跑后仍可用）。"""
        with self._lock:
            if self._conn is None:
                self._open()
            return self._conn

    def close(self) -> None:
        """显式关闭连接（测试用）。"""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    # ------------------------------------------------------------------
    # 便捷查询（仓储层用）
    # ------------------------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行写操作（INSERT / UPDATE / DELETE），自动提交。"""
        # 锁必须覆盖 execute + commit 的完整事务；只在 conn 属性取值时加锁
        # 无法阻止其他线程在提交前插入自己的 SQL，可能造成事务串扰。
        with self._lock:
            conn = self.conn
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """执行查询，返回 Row 列表。"""
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    # 测试辅助
    # ------------------------------------------------------------------
    def wipe(self) -> None:
        """清空全部业务表（测试用；保留 schema）。"""
        with self._lock:
            for table in ("user_profile", "events", "preferences"):
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.commit()
