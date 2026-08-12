# -*- coding: utf-8 -*-
"""Reflector：AI 自我反思（v3.0 Phase 2 —— Agent 与普通 ChatGPT 的核心区别）。

职责：
    编译生成事件后，再以「第三方审查者」身份检查一次：
        - 数值是否离谱（普通日常获得巨额财富 → 必须标记）
        - 是否符合当前人物 / 世界观
        - 是否违反规则（注入指令 / 超范围数值）
        - 事件是否贴合用户输入（不编造）
    结论：合理（通过）/ 不合理（标记需重生成）。

设计（务实且稳健）：
    1. 首选「AI 反思」：调用 core.llm_client.call_llm_for_reflection，
       让大模型真正做一次自我审查（这是 Agent 化的关键能力）。
    2. 降级「本地规则反思」：AI 不可用（缺 Key / 网络异常 / 返回异常）时，
       用纯 Python 规则兜底（数值是否超 schema 范围 / 是否全是零数值假事件 /
       事件数是否异常），保证反思环节永不崩溃、永远有结论。
    3. 反思失败绝不影响编译主流程：即使 AI 反思抛异常，也只记一条 note。

分层约定：core 层，纯 Python，禁止 import streamlit。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import schema_validator as sv
from .. import llm_client
from ..agent.planner import AgentPlan


@dataclass
class ReflectionResult:
    """一次反思的结论。"""

    reasonable: bool                          # True=通过；False=需重生成
    source: str = "rule"                      # "ai"（AI 反思）/ "rule"（本地规则）
    issues: list[str] = field(default_factory=list)       # 发现的问题
    suggestion: str = ""                      # 改进建议
    notes: list[str] = field(default_factory=list)        # 过程记录（含降级原因）


class Reflector:
    """AI 自我反思器。

    参数：
        llm_reflect: 可注入的 AI 反思函数（默认走 core.llm_client.call_llm_for_reflection）。
                     测试可替换为 fake，验证 AI 分支与降级分支。
        max_reflection_events: 传给 AI 审查的最大事件数（超出截断，防止 prompt 过大）。
    """

    def __init__(self, llm_reflect=None, *, max_reflection_events: int = 12) -> None:
        self._llm_reflect = llm_reflect or llm_client.call_llm_for_reflection
        self.max_reflection_events = max_reflection_events

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def reflect(
        self,
        user_input: str,
        events: list[dict],
        world,
        plan: AgentPlan | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> ReflectionResult:
        """反思已生成的事件。

        参数：
            user_input: 用户原始输入（清洗后）
            events:     已生成的原始事件 dict 列表（未转换 MatchedEvent 前）
            world:      当前世界观对象
            plan:       Planner 执行计划（可选，提供上下文/约束参考）
            api_key / base_url / model: 透传给 AI 反思调用
        返回：
            ReflectionResult
        """
        if not events:
            return ReflectionResult(
                reasonable=False,
                source="rule",
                issues=["无事件可反思，需要重新生成。"],
            )

        # 第一步：本地规则反思（永远执行，作为兜底结论）
        rule_result = self._rule_check(events)
        # 本地规则已经发现严重问题（数值离谱），直接判不通过，不再浪费一次 AI 调用
        if not rule_result.reasonable:
            return rule_result

        # 第二步：AI 深度反思（可选能力，失败自动降级为本地结论）
        return self._ai_reflect(
            user_input, events, world, plan,
            api_key=api_key, base_url=base_url, model=model,
            fallback=rule_result,
        )

    def reflect_local(self, events: list[dict]) -> ReflectionResult:
        """只运行本地规则复核，不发起网络请求。

        用于主页默认快速模式：保留数值越界与空事件检查，同时避免为一次编译
        再等待第二次模型响应。需要深度审查时仍可调用 ``reflect()``。
        """
        if not events:
            return ReflectionResult(
                reasonable=False,
                source="rule",
                issues=["无事件可反思，需要重新生成。"],
            )
        result = self._rule_check(events)
        result.notes.append("已完成本地规则快速复核，未额外调用模型。")
        return result

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _rule_check(self, events: list[dict]) -> ReflectionResult:
        """本地规则反思：纯 Python，永远可用，作为 AI 反思的兜底。"""
        issues: list[str] = []

        # 数值范围检查（与 schema 硬上限一致——反射发现越界=严重问题）
        for ev in events:
            name = str(ev.get("name", "") or "")
            hp = ev.get("hp", 0)
            mp = ev.get("mp", 0)
            gold = ev.get("gold_or_san", ev.get("gold", 0))
            exp = ev.get("exp", 0)
            if hp < sv.HP_MIN or hp > sv.HP_MAX:
                issues.append(f"「{name}」hp={hp} 越界")
            if mp < sv.MP_MIN or mp > sv.MP_MAX:
                issues.append(f"「{name}」mp={mp} 越界")
            if gold < sv.GOLD_MIN or gold > sv.GOLD_MAX:
                issues.append(f"「{name}」gold={gold} 越界")
            if exp < sv.EXP_MIN or exp > sv.EXP_MAX:
                issues.append(f"「{name}」exp={exp} 越界")

        # 全是零数值的「假事件」：没有信息量，判定不合理
        non_empty = [
            ev for ev in events
            if (ev.get("hp") or 0) != 0 or (ev.get("mp") or 0) != 0
            or (ev.get("gold_or_san", ev.get("gold", 0)) or 0) != 0
            or (ev.get("exp") or 0) != 0
        ]
        if events and not non_empty:
            issues.append("所有事件数值全为 0，疑似空编译。")

        if issues:
            return ReflectionResult(
                reasonable=False,
                source="rule",
                issues=issues,
                suggestion="请根据问题重新生成。",
                notes=["本地规则反思发现严重问题。"],
            )
        return ReflectionResult(reasonable=True, source="rule")

    def _ai_reflect(
        self,
        user_input: str,
        events: list[dict],
        world,
        plan: AgentPlan | None,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        fallback: ReflectionResult,
    ) -> ReflectionResult:
        """AI 深度反思：调用 LLM 审查；任何失败都降级为本地结论。"""
        try:
            # 事件太多时截断，避免 prompt 过长 / 成本失控
            evs = events[: self.max_reflection_events]
            verdict = self._llm_reflect(
                world, user_input, evs,
                api_key=api_key, base_url=base_url, model=model,
            )
            reasonable = bool(verdict.get("reasonable", True))
            issues = list(verdict.get("issues", []) or [])
            suggestion = str(verdict.get("suggestion", "") or "")
            notes = [f"AI 反思结论：{'合理' if reasonable else '不合理'}"
                     + (f"（{len(issues)} 个问题）" if issues else "")]
            return ReflectionResult(
                reasonable=reasonable,
                source="ai",
                issues=issues,
                suggestion=suggestion,
                notes=notes,
            )
        except Exception as exc:
            # 反思失败绝不影响编译主流程：降级为本地规则结论
            return ReflectionResult(
                reasonable=fallback.reasonable,
                source="rule",
                issues=fallback.issues,
                suggestion=fallback.suggestion,
                notes=[f"AI 反思不可用（{exc}），已使用本地规则反思。", *fallback.notes],
            )
