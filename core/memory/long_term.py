# -*- coding: utf-8 -*-
"""长期记忆（v3.0 Phase 3）：SQLite 持久化的用户档案 / 历史事件 / 长期偏好。

这是「让 Agent 会使用数据」的底座：
    - 每次编译后，Agent 把事件快照写入 events 表；
    - 从标签中提炼「反复出现的偏好」累计权重（bump_pref）；
    - 用户可在设置页维护少量档案（昵称 / 习惯）。

与 short_term 的关系：
    long_term 是「永久的档案库」，short_term 是「刚聊完的临时上下文」；
    检索器把两者合起来喂给 Planner。
"""

from __future__ import annotations

from typing import Any

from ..database import Database, Repository


class LongTermMemory:
    """长期记忆：封装 Repository 的语义化读写（面向 Agent / Retriever）。"""

    def __init__(self, db: Database | None = None) -> None:
        self.repo = Repository(db)

    # ------------------------------------------------------------------
    # 用户档案
    # ------------------------------------------------------------------
    def set_profile(self, key: str, value: str) -> None:
        self.repo.set_profile(key, value)

    def get_profile(self, key: str) -> str | None:
        return self.repo.get_profile(key)

    def profiles(self) -> dict[str, str]:
        return self.repo.all_profiles()

    # ------------------------------------------------------------------
    # 历史事件
    # ------------------------------------------------------------------
    def save_event(
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
        """保存一次编译事件快照，返回 id。"""
        return self.repo.add_event(
            date=date, source=source, summary=summary, advice=advice,
            attributes=attributes, tags=tags, world_label=world_label,
        )

    def recent(self, limit: int = 10, *, date: str | None = None) -> list[dict]:
        """最近 N 条事件（可筛选日期）。"""
        return self.repo.recent_events(limit, date=date)

    def on_date(self, date: str) -> list[dict]:
        """某天的全部事件。"""
        return self.repo.events_on(date)

    def total_events(self, *, since: str | None = None) -> int:
        return self.repo.count_events(since=since)

    # ------------------------------------------------------------------
    # 长期偏好
    # ------------------------------------------------------------------
    def observe_tags(self, tags: list[str], *, delta: float = 1.0) -> None:
        """观察一组标签：每个标签累计权重（用于提炼长期偏好）。"""
        for tag in (tags or []):
            tag = str(tag).strip()
            if tag:
                self.repo.bump_pref("tag:" + tag, tag, delta)

    def get_pref(self, key: str) -> str | None:
        return self.repo.get_pref(key)

    def top_prefs(self, limit: int = 5) -> list[dict]:
        """按权重取前 N 条偏好（给检索器/展示用）。"""
        return self.repo.top_prefs(limit)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def close(self) -> None:
        self.repo.db.close()
