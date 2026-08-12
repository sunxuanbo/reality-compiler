# -*- coding: utf-8 -*-
"""仓储层：用户档案 / 历史事件 / 长期偏好的增删查改（v3.0 Phase 3）。

所有 SQL 收敛在本文件，上层（memory / agent）只面向「语义化方法」编程：
    profile:  get_profile / set_profile / all_profiles
    events:   add_event / recent_events / events_on / count_events
    prefs:    get_pref / set_pref / bump_pref / top_prefs
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from .db import Database


def _now_iso() -> str:
    """当前时间 ISO 8601（带本地时区）。"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class Repository:
    """SQLite 仓储：三张业务表的语义化读写。"""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    # ------------------------------------------------------------------
    # 用户档案（key-value）
    # ------------------------------------------------------------------
    def set_profile(self, key: str, value: str) -> None:
        """写入 / 更新一条档案（upsert）。"""
        self.db.execute(
            "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, str(value), _now_iso()),
        )

    def get_profile(self, key: str) -> str | None:
        """读取一条档案；不存在返回 None。"""
        rows = self.db.query(
            "SELECT value FROM user_profile WHERE key=?", (key,),
        )
        return rows[0]["value"] if rows else None

    def all_profiles(self) -> dict[str, str]:
        """读取全部档案（dict）。"""
        return {r["key"]: r["value"] for r in self.db.query(
            "SELECT key, value FROM user_profile ORDER BY updated_at DESC")}

    # ------------------------------------------------------------------
    # 历史事件
    # ------------------------------------------------------------------
    def add_event(
        self,
        *,
        date: str,
        source: str,
        summary: str = "",
        advice: str = "",
        attributes: dict | None = None,
        tags: list[str] | None = None,
        world_label: str = "",
    ) -> int:
        """写入一条编译事件快照，返回自增 id。"""
        cur = self.db.execute(
            "INSERT INTO events (date, source, summary, advice, attributes, tags, "
            "world_label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date, source, summary, advice,
                json.dumps(attributes or {}, ensure_ascii=False),
                json.dumps(tags or [], ensure_ascii=False),
                world_label, _now_iso(),
            ),
        )
        return cur.lastrowid or 0

    def _row_to_event(self, row) -> dict:
        """sqlite3.Row → dict（JSON 字段解析成对象）。"""
        ev = dict(row)
        for f in ("attributes", "tags"):
            try:
                ev[f] = json.loads(ev.get(f) or ("{}" if f == "attributes" else "[]"))
            except (ValueError, TypeError):
                ev[f] = {} if f == "attributes" else []
        return ev

    def recent_events(self, limit: int = 10, *, date: str | None = None) -> list[dict]:
        """最近 N 条事件（可选按日期过滤），按写入时间倒序。"""
        limit = max(0, min(int(limit), 1000))
        sql = "SELECT * FROM events"
        params: tuple = ()
        if date:
            sql += " WHERE date=?"
            params = (date,)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        return [self._row_to_event(r) for r in self.db.query(sql, params + (limit,))]

    def events_on(self, date: str) -> list[dict]:
        """某一天的全部事件（正序：先发生在前）。"""
        rows = self.db.query(
            "SELECT * FROM events WHERE date=? ORDER BY created_at ASC, id ASC",
            (date,),
        )
        return [self._row_to_event(r) for r in rows]

    def count_events(self, *, since: str | None = None) -> int:
        """事件总数（可选 since 日期过滤）。"""
        if since:
            rows = self.db.query(
                "SELECT COUNT(*) AS n FROM events WHERE date>=?", (since,),
            )
        else:
            rows = self.db.query("SELECT COUNT(*) AS n FROM events")
        return int(rows[0]["n"]) if rows else 0

    # ------------------------------------------------------------------
    # 长期偏好
    # ------------------------------------------------------------------
    def set_pref(self, key: str, value: str, weight: float = 1.0) -> None:
        """写入 / 更新一条长期偏好。"""
        self.db.execute(
            "INSERT INTO preferences (key, value, weight, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "weight=excluded.weight, updated_at=excluded.updated_at",
            (key, str(value), float(weight), _now_iso()),
        )

    def get_pref(self, key: str) -> str | None:
        """读取一条偏好；不存在返回 None。"""
        rows = self.db.query(
            "SELECT value FROM preferences WHERE key=?", (key,),
        )
        return rows[0]["value"] if rows else None

    def bump_pref(self, key: str, value: str, delta: float = 1.0) -> None:
        """累加偏好权重（用于「同一标签反复出现」的统计）。"""
        # 单条 UPSERT 原子累加，避免并发的「先读再写」丢失更新。
        self.db.execute(
            "INSERT INTO preferences (key, value, weight, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "weight=preferences.weight + excluded.weight, "
            "updated_at=excluded.updated_at",
            (key, str(value), float(delta), _now_iso()),
        )

    def top_prefs(self, limit: int = 5) -> list[dict]:
        """按权重倒序取前 N 条偏好。"""
        limit = max(0, min(int(limit), 1000))
        return [dict(r) for r in self.db.query(
            "SELECT key, value, weight FROM preferences "
            "ORDER BY weight DESC, updated_at DESC, key ASC LIMIT ?", (limit,),
        )]
