# -*- coding: utf-8 -*-
"""检索器（v3.0 Phase 3）：把记忆检索成 Planner 可用的上下文。

职责：
    Agent 编译前调用 retrieve()，得到一份「上下文 dict」，注入 Planner 的 context。
    上下文包含三块（各自可裁剪，控制 token 成本）：
        profile  用户档案（昵称 / 习惯）
        recent   最近事件摘要（短期 + 长期各取一部分）
        prefs    高频偏好标签（权重 Top N）

设计：
    - 纯 Python，不做向量检索（Phase 3 先用关键词/权重检索，足够）。
    - 所有检索结果限制条数，防止 prompt 爆炸。
    - 记忆为空时返回空 dict（Planner 正常编译，不依赖记忆）。
"""

from __future__ import annotations

from typing import Any

from .short_term import ShortTermMemory
from .long_term import LongTermMemory


class MemoryRetriever:
    """把短期 + 长期记忆组装成 Planner 的 context dict。"""

    def __init__(
        self,
        short_term: ShortTermMemory | None = None,
        long_term: LongTermMemory | None = None,
        *,
        max_recent: int = 5,
        max_prefs: int = 5,
    ) -> None:
        # ShortTermMemory 实现了 __len__，空实例在布尔判断中为 False；不能用
        # ``x or default``，否则调用方传入的空记忆会被悄悄替换。
        self.short_term = short_term if short_term is not None else ShortTermMemory()
        self.long_term = long_term if long_term is not None else LongTermMemory()
        self.max_recent = max(1, max_recent)
        self.max_prefs = max(1, max_prefs)

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def retrieve(self, *, date: str | None = None) -> dict[str, Any]:
        """组装上下文 dict（供 Planner.create_plan 的 context 参数使用）。

        参数：
            date: 可选日期过滤（今日上下文）
        返回：
            {"profile": {...}, "recent": [...], "prefs": [...], "memory_enabled": True}
            记忆全空时返回 {"memory_enabled": True, ...}（空块照常存在）。
        """
        context: dict[str, Any] = {"memory_enabled": True}

        # 1. 用户档案
        profile = self.long_term.profiles()
        if profile:
            context["profile"] = profile

        # 2. 最近事件（短期在前，长期在后；各自裁剪）
        # 两种来源都按「最新优先」合并，避免容量裁剪时保留了较旧的短期记录。
        short_items = list(reversed(self.short_term.recent(self.max_recent)))
        long_items = self.long_term.recent(self.max_recent, date=date)
        recent = self._compact_events(short_items + long_items, self.max_recent)
        if recent:
            context["recent"] = recent

        # 3. 高频偏好
        prefs = self.long_term.top_prefs(self.max_prefs)
        if prefs:
            context["prefs"] = [
                {"tag": p["value"], "weight": p["weight"]} for p in prefs
                if p.get("value")
            ]

        return context

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _compact_events(items: list[dict], limit: int) -> list[str]:
        """把事件压缩成「一句话摘要」列表，并裁剪到 limit 条。

        摘要格式：[日期] 标签/事件名 摘要
        """
        out: list[str] = []
        for ev in items:
            if not isinstance(ev, dict):
                continue
            date = str(ev.get("date", "") or "")[:10]
            tags = ev.get("tags") or []
            tag_str = ",".join(str(t) for t in tags[:2]) if tags else ""
            summary = str(ev.get("summary", "") or "").strip() or "（无摘要）"
            line = f"{date} [{tag_str}] {summary}".strip()
            if line not in out:      # 去重（短期与长期可能同源）
                out.append(line)
            if len(out) >= limit:
                break
        return out
