# -*- coding: utf-8 -*-
"""Validator：AI 输出的合理性校验（v3.0 Phase 2）。

职责（在 schema 安全门之上做「语义合理性」检查）：
    1. 复用 core.schema_validator 的硬校验（JSON 提取 / 缺字段补 0 / 类型强转 /
       数值硬截断 / 兜底默认事件）——这是第一道防线，保证格式合法。
    2. 新增「语义合理性」检查（Agent 层独有）：
       - 事件数量是否在合理范围（Planner 计划要求 1-6 条）
       - 是否为空事件 / 全是零数值的「假事件」
       - 事件名是否为空 / 超长
       - 标签是否为空（AI 忘记打标签时提示）
    3. 校验结论：通过 / 带警告通过 / 不通过（需重生成）。

与旧链路的区别：
    旧：compiler 里直接 json.loads + 本地降级。
    新：Agent 里先过 schema_validator（格式），再过 Validator（语义），
        两关都过才交给 Runtime。Validator 是 Agent「判断」能力的一部分。

分层约定：core 层，纯 Python，禁止 import streamlit。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import schema_validator as sv
from ..agent.planner import AgentPlan


# 语义合理性的阈值（独立于 schema 硬范围，作为「质量」判断而非「安全」判断）
EVENTS_MIN, EVENTS_MAX = 1, 6          # 与 Planner objectives 一致
NAME_MAX_LEN = 40                      # 事件名过长提示
DESC_MAX_LEN = 300                     # 描述过长提示


@dataclass
class ValidationResult:
    """一次校验的完整结论。"""

    ok: bool                                # True=可交给 Runtime；False=需重生成
    data: dict | None = None                # 校验通过后的响应 dict（已修复）
    notes: list[str] = field(default_factory=list)   # 人类可读的检查记录
    warnings: list[str] = field(default_factory=list) # 不致命但建议留意的提示
    repaired: bool = False                  # 是否发生过修复（补字段/截断等）


class Validator:
    """校验 LLM 输出：格式关（schema_validator）+ 语义关（本类）。

    设计：Validator 不做 LLM 调用，只做「判断」。若判断不通过，
    由外层 Agent 决定是重生成还是降级（见 agent.py）。
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def check(self, content: str, plan: AgentPlan | None = None) -> ValidationResult:
        """校验 DeepSeek 返回的原始文本（字符串入口）。

        参数：
            content: LLM 返回的原文（可能是纯 JSON，也可能夹带解释文字）
            plan:    Planner 的执行计划（提供数量约束）；None 时用默认阈值
        返回：
            ValidationResult
        """
        # 第一关：schema 安全门（格式 + 硬数值 + 兜底）
        data, notes = sv.validate_and_repair(content)
        if data is None:
            # schema 层判定不可修复（非 JSON / 缺必填字段）→ 直接不通过
            return ValidationResult(
                ok=False,
                notes=notes,
                warnings=["AI 输出格式异常，需要重新生成。"],
            )
        # 第二关：语义合理性（复用 check_data）
        return self.check_data(data, plan, notes=notes)

    def check_data(
        self,
        data: dict,
        plan: AgentPlan | None = None,
        *,
        notes: list[str] | None = None,
    ) -> ValidationResult:
        """校验已解析的数据 dict（Agent 主流程入口）。

        Agent 的 LLM 阶段复用 call_llm_for_events_full（内部已过 schema 安全门 +
        格式重试 + 兜底），返回的已是合法 dict。本方法专注「语义合理性」检查：
        事件数量、事件质量（空名/超长/无标签）、是否需要修复提示。

        参数：
            data: call_llm_for_events_full 的返回 dict（含 events）
            plan: Planner 的执行计划（提供数量约束）；None 时用默认阈值
            notes: 来自 schema 层的修复记录（可选，合并进结果）
        返回：
            ValidationResult
        """
        notes = list(notes or [])
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            return ValidationResult(
                ok=False,
                notes=notes,
                warnings=["AI 输出格式异常，需要重新生成。"],
            )

        # 语义合理性检查
        warnings: list[str] = []
        evs = data.get("events") or []

        # Schema 层已先执行硬截断，Validator 仍要把质量问题呈现给调用方。
        warnings.extend(n for n in notes if "events 共" in n and "超出建议上限" in n)

        # 事件数量
        lo, hi = EVENTS_MIN, EVENTS_MAX
        if plan is not None:
            lo = int(plan.constraints.get("events_min", EVENTS_MIN))
            hi = int(plan.constraints.get("events_max", EVENTS_MAX))
        if not evs:
            # schema 层已兜底为默认事件，这里提示但不算致命
            warnings.append("AI 未返回事件，已使用默认事件。")
        elif len(evs) > hi:
            warnings.append(f"AI 返回 {len(evs)} 条事件，超出建议上限 {hi} 条。")

        # 事件质量
        for ev in evs:
            name = str(ev.get("name", "") or "")
            if not name.strip():
                warnings.append("存在名称为空的事件。")
            elif len(name) > NAME_MAX_LEN:
                warnings.append(f"事件名「{name[:12]}…」过长（>{NAME_MAX_LEN} 字）。")
            desc = str(ev.get("description") or "")
            if len(desc) > DESC_MAX_LEN:
                warnings.append("存在描述过长的事件。")
            tags = ev.get("tags") or []
            if not tags:
                warnings.append("AI 未给事件打标签，标签墙可能为空。")

        # 是否发生过修复（补字段 / 截断等）——只要有 notes 记录就算
        repaired = any(
            n and not n.startswith(("AI 返回", "无法提取")) for n in notes
        ) or bool(warnings)

        return ValidationResult(
            ok=True,                       # 语义问题不阻断，交给 Reflection 深度判断
            data=data,
            notes=notes,
            warnings=warnings,
            repaired=repaired,
        )
