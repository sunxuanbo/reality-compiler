# -*- coding: utf-8 -*-
"""Planner：把「用户输入 + 世界观 + 上下文」编译成结构化执行计划（v3.0 Phase 2）。

职责：
    1. 对用户输入做基础清洗（去空白 / 空输入检测）。
    2. 结合当前世界观（WorldProfile）生成执行计划：
       - 目标：这段输入要编译成什么（结构化事件 + 数值结算）。
       - 约束：数值硬范围（与 core.schema_validator 保持一致，Agent 层不新增数值口径）。
       - 上下文：历史上下文（如记忆系统短期记忆，当前为占位空列表，Phase 3 接入）。
       - 输出规格：DeepSeek 需要返回的 JSON 结构说明。
    3. 计划可序列化 / 可测试（纯数据对象，不含 I/O）。

与旧链路的区别：
    旧：输入 → LLM → 解析 → Runtime（无中间计划层）。
    新：输入 → Planner（产生计划）→ LLM（按计划生成）→ Validator → Runtime。
    Planner 是 Agent「思考」的第一步：先想清楚要做什么，再让 LLM 干活。

分层约定：core 层，纯 Python，禁止 import streamlit。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..world_config import FALLBACK_WORLD, WorldProfile
from ..schema_validator import (
    HP_MIN, HP_MAX,
    MP_MIN, MP_MAX,
    GOLD_MIN, GOLD_MAX,
    EXP_MIN, EXP_MAX,
    TAGS_MAX,
)


# ----------------------------------------------------------------------------
# 计划的数据结构
# ----------------------------------------------------------------------------
@dataclass
class AgentPlan:
    """一次编译的执行计划（Planner 的产物，LLM 与 Validator 都按它工作）。"""

    source: str                                   # 清洗后的用户输入
    world: WorldProfile                           # 当前世界观对象
    date: str                                     # 今日日期（ISO）
    objectives: list[str] = field(default_factory=list)      # 执行目标
    constraints: dict = field(default_factory=dict)          # 数值约束
    context: dict = field(default_factory=dict)              # 上下文（历史/人格等，Phase 3）
    output_spec: dict = field(default_factory=dict)          # LLM 输出规格

    def summary(self) -> str:
        """给日志/调试用的一句话摘要。"""
        return (
            f"Plan(source={self.source[:24]!r}, world={self.world.label}, "
            f"events_constraints=hp[{HP_MIN},{HP_MAX}] exp[{EXP_MIN},{EXP_MAX}])"
        )


# ----------------------------------------------------------------------------
# Planner
# ----------------------------------------------------------------------------
class Planner:
    """把输入编译成计划。当前为「规则型」Planner：不调 LLM，纯本地构造。

    未来（Phase 4 世界模拟升级）可扩展为「AI Planner」：让 LLM 决定本段输入的
    编译策略（重点监控哪些属性、触发哪些隐藏规则）。当前版本保持简单可控。
    """

    def __init__(self, *, max_input_len: int = 2000) -> None:
        self.max_input_len = max_input_len

    def create_plan(
        self,
        user_input: str,
        world: WorldProfile | None = None,
        *,
        date: str | None = None,
        context: dict | None = None,
    ) -> AgentPlan:
        """构造执行计划。

        参数：
            user_input: 用户写的现实日常（可能带多余空白）
            world:      当前世界观；None 时用 FALLBACK_WORLD
            date:       今日日期；None 时取系统当天
            context:    历史上下文（Phase 3 记忆系统接入后传入；当前可选）
        返回：
            AgentPlan
        异常：
            ValueError：输入为空 / 超长（超长会截断并标记，而不是直接拒绝）
        """
        cleaned = (user_input or "").strip()
        if not cleaned:
            raise ValueError("输入为空，无法编译")

        # 超长保护：截断到 max_input_len，避免 prompt 过大 / 成本失控
        truncated = False
        if len(cleaned) > self.max_input_len:
            cleaned = cleaned[: self.max_input_len]
            truncated = True

        import datetime as _dt
        date_str = date or _dt.date.today().isoformat()
        world = world or FALLBACK_WORLD
        context = dict(context or {})

        # 执行目标：本段输入的核心任务（给 LLM 的「任务书」）
        objectives = [
            "把用户的现实日常文本，编译成 1-6 个结构化事件（AI 事件）",
            "每个事件给出：名称、描述、属性增量（hp/mp/gold/exp）、标签",
            "生成一句今日复盘 summary 与一句改进建议 advice",
        ]

        # 数值约束：与 core.schema_validator 严格一致（Agent 层不新增口径）
        constraints = {
            "hp": [HP_MIN, HP_MAX],
            "mp": [MP_MIN, MP_MAX],
            "gold": [GOLD_MIN, GOLD_MAX],
            "exp": [EXP_MIN, EXP_MAX],
            "tags_max": TAGS_MAX,
            "events_min": 1,
            "events_max": 6,
            "note": "任何数值都不允许超出上述范围；超限将被系统强制截断。",
        }

        # LLM 输出规格：告诉 DeepSeek 必须返回什么样的 JSON
        output_spec = {
            "format": "json_object",
            "required_keys": ["events"],
            "event_fields": ["name", "description", "hp", "mp", "gold_or_san",
                             "exp", "tags"],
            "optional_keys": ["world_display_name", "summary", "advice"],
            "truncated_input": truncated,
        }

        return AgentPlan(
            source=cleaned,
            world=world,
            date=date_str,
            objectives=objectives,
            constraints=constraints,
            context=context,
            output_spec=output_spec,
        )
