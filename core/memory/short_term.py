# -*- coding: utf-8 -*-
"""短期记忆（v3.0 Phase 3）：本次进程内最近的 N 条事件。

与长期记忆的区别：
    - 短期：内存，进程重启即丢，适合「刚聊完的上下文」（如刚编译过什么、最近几天的标签）。
    - 长期：SQLite，永久保存，适合「用户档案 / 历史规律 / 长期偏好」。

设计：
    - 简单队列：FIFO，超上限自动淘汰最旧。
    - 线程安全：Streamlit 多会话下同一进程共享，加锁保护。
    - 可注入上限（测试可设小值验证淘汰）。
"""

from __future__ import annotations

import threading
from typing import Any


class ShortTermMemory:
    """进程内短期记忆队列（FIFO，最近 N 条）。"""

    def __init__(self, capacity: int = 20) -> None:
        self.capacity = max(1, capacity)
        self._items: list[dict] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------
    def remember(self, item: dict) -> None:
        """记一条；超出容量淘汰最旧。"""
        with self._lock:
            self._items.append(dict(item))
            if len(self._items) > self.capacity:
                del self._items[0]

    def clear(self) -> None:
        """清空（跨天 / 用户主动清空时用）。"""
        with self._lock:
            self._items.clear()

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------
    def recent(self, limit: int | None = None) -> list[dict]:
        """最近 limit 条（默认全部），最新的在末尾。"""
        with self._lock:
            items = list(self._items)
        if limit is None:
            return items
        return items[-max(0, limit):]

    def latest(self) -> dict | None:
        """最近一条；空时返回 None。"""
        with self._lock:
            return self._items[-1] if self._items else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def is_empty(self) -> bool:
        return len(self) == 0
