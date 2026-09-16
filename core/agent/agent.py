# -*- coding: utf-8 -*-
"""RealityAgent：编排完整编译生命周期（v3.2 —— 双 Agent 协作）。

流程（v3.2）：
    用户输入
      ↓
    Planner     把输入 + 世界观 + 上下文 编译成结构化执行计划
      ↓
    LLM         调用 DeepSeek 生成结构化事件
      ↓
    Validator   语义合理性校验
      ↓
    Runtime     build_compile_result + 结算
      ↓
    Critic      独立质检 Agent（v3.2 新增），评分 0-100
      ↓ 评分 < 70 且未超重编次数
    ⟲  重编：把 Critic 的 improvement_tip 注入 Planner 重新走一遍
      ↓ 评分 >= 70 或超重编次数
    Reflection  AI 自我反思
      ↓
    返回 AgentRunResult（含 collaboration 记录）

双 Agent 协作核心区别于旧链路：
    - 编译 Agent 和质检 Agent 是两个独立 LLM 调用
    - Critic 不知道 Planner/Validator 内部过程，真正的"第三方"
    - Critic 评分驱动重编循环，最多 2 次（防止成本/延迟失控）
    - 重编时 Critic 的 improvement_tip 注入 Planner，确保真的改了什么
"""

from __future__ import annotations

import time                        # v3.1 Agent 流程可视化：每步计时
from dataclasses import dataclass, field

from ..world_config import FALLBACK_WORLD, WorldProfile
from ..compiler import build_compile_result, CompileResult
from .. import llm_client
from ..simulation import SimulationEngine, SimulationResult, SimState
from ..emotion import resolve_emotion
from .planner import Planner, AgentPlan
from .validator import Validator, ValidationResult
from .reflector import Reflector, ReflectionResult


def _collect_tags(events: list[dict]) -> list[str]:
    """收集全部事件的标签（去重、去空）。"""
    tags: list[str] = []
    for ev in events or []:
        for t in (ev.get("tags") or []):
            t = str(t).strip()
            if t and t not in tags:
                tags.append(t)
    return tags


def _collect_attributes(compile_result: CompileResult) -> dict:
    """从 CompileResult 提取属性面板摘要（归档用）。

    CompileResult 本身不含最终结算值（结算在 Runtime 层），这里存
    「事件数量 + 总变化量」作为长期记忆的轻量画像。
    """
    matched = compile_result.matched or []
    return {
        "events": len(matched),
        "hp_total": sum(round(m.event.hp * m.scale) for m in matched),
        "mp_total": sum(round(m.event.mp * m.scale) for m in matched),
        "gold_total": sum(round(m.event.gold * m.scale) for m in matched),
        "exp_total": sum(round(m.event.exp * m.scale) for m in matched),
    }


@dataclass
class CriticResult:
    """Critic Agent 独立质检的结论（v3.2 双 Agent 协作）。"""
    score: int = 60                          # 0-100 总分
    dimensions: dict = field(default_factory=dict)  # 各维度分数 {"贴合度": 18, ...}
    passed: bool = True                      # 是否通过质检（避免用 pass 关键字）
    critical_issues: list[str] = field(default_factory=list)  # 最严重问题
    improvement_tip: str = ""                # 供重编参考的改进建议
    source: str = "ai"                       # "ai" / "rule"（降级）


@dataclass
class CollaborationRecord:
    """双 Agent 协作过程记录（v3.2）。"""
    rounds: list[dict] = field(default_factory=list)   # 每轮的 critic 评分和事件数
    final_score: int = 0                                # 最终轮的 critic 分数
    total_retries: int = 0                              # 重编次数
    passed: bool = True                                 # 最终是否通过


@dataclass
class AgentRunResult:
    """一次 Agent 完整运行的产物。"""

    plan: AgentPlan                              # 执行计划
    validation: ValidationResult                 # 校验结论
    compile: CompileResult                       # 编译结果（与旧 compile_reality 同类型）
    reflection: ReflectionResult | None = None   # 反思结论（关闭反思时为 None）
    simulation: SimulationResult | None = None   # 世界演化结论（v3.0 Phase 4，关闭时为 None）
    notes: list[str] = field(default_factory=list)   # 过程记录（供日志/调试）
    timings: dict = field(default_factory=dict)   # v3.1 Agent 流程可视化：每步耗时（秒）
    # v3.2 双 Agent 协作
    collaboration: CollaborationRecord | None = None  # 双 Agent 协作记录
    critic: CriticResult | None = None                # Critic Agent 最终评估

    @property
    def reflected_ok(self) -> bool:
        """反思是否通过（未反思视为通过）。"""
        return self.reflection is None or self.reflection.reasonable

    @property
    def simulated(self) -> bool:
        """世界是否发生了演化（有衍生事件/标签/规则触发）。"""
        return self.simulation is not None and self.simulation.evolved


class RealityAgent:
    """Reality Compiler 的 Agent 控制器（v3.2 双 Agent 协作版）。

    流程：Planner → LLM → Validator → Runtime → Critic（质检）→ 不通过则重编（最多2次）→ Reflection

    参数（全部可注入，便于测试与替换）：
        planner:       Planner 实例（默认）
        validator:     Validator 实例（默认）
        reflector:     Reflector 实例（默认）
        llm_generate:  可注入的事件生成函数（默认 core.llm_client.call_llm_for_events_full）
        llm_critic:    可注入的质检评估函数（默认 core.llm_client.call_llm_for_critic）
        simulation_engine: 世界模拟引擎（None = 不启用）
    """

    CRITIC_THRESHOLD = 70   # 分数低于此值触发重编
    MAX_RETRIES = 2          # 最多重编几次

    def __init__(
        self,
        planner: Planner | None = None,
        validator: Validator | None = None,
        reflector: Reflector | None = None,
        llm_generate=None,
        llm_critic=None,
        retriever=None,
        simulation_engine: SimulationEngine | None = None,
    ) -> None:
        self.planner = planner or Planner()
        self.validator = validator or Validator()
        self.reflector = reflector or Reflector()
        self._llm_generate = llm_generate or llm_client.call_llm_for_events_full
        self._llm_critic = llm_critic or llm_client.call_llm_for_critic
        self._retriever = retriever
        self.simulation_engine = simulation_engine

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def run(
        self,
        user_input: str,
        world: WorldProfile | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        context: dict | None = None,
        enable_reflection: bool = True,
        enable_local_reflection: bool = False,
        memory: "LongTermMemory | None" = None,
        enable_simulation: bool = True,
        simulation_state: SimState | None = None,
        enable_critic: bool = True,
    ) -> AgentRunResult:
        """执行完整编译生命周期（v3.2 双 Agent 协作）。

        v3.2 新增 enable_critic 参数：开启后，编译完成后 Critic Agent 独立评分，
        评分低于 70 自动重编（最多 2 次），improvement_tip 注入 Planner。

        参数：
            user_input: 用户写的现实日常
            world:      当前世界观；None 时用 FALLBACK_WORLD
            api_key / base_url / model: 透传给 LLM 调用
            context:    调用方手动注入的上下文（优先级最高，覆盖记忆检索）
            enable_reflection: 是否启用 AI 反思（默认开启；关闭时跳过反思环节）
            enable_local_reflection: AI 反思关闭时，是否执行零网络请求的本地规则复核。
            memory:     长期记忆（v3.0 Phase 3）。
            enable_simulation: 是否启用世界模拟（v3.0 Phase 4）。
            simulation_state: 上一次模拟后的隐藏状态。
            enable_critic: 是否启用双 Agent 协作（默认开启，v3.2 新增）。
        返回：
            AgentRunResult
        """
        notes: list[str] = []
        timings: dict[str, float] = {}
        collaboration = CollaborationRecord()
        _t0 = time.perf_counter()

        # === 记忆检索（前置，只做一次） ===
        effective_context = context
        if memory is not None and self._retriever is not None and effective_context is None:
            try:
                retrieved = self._retriever.retrieve()
                if retrieved:
                    effective_context = retrieved
                    notes.append("已注入记忆上下文")
            except Exception as exc:
                notes.append(f"记忆检索失败：{exc}")

        # === 双 Agent 协作主循环 ===
        # 最多执行 MAX_RETRIES+1 轮（初始 1 轮 + 重编 MAX_RETRIES 轮）
        improvement_tip: str = ""
        ai_data: dict = {}
        plan: AgentPlan | None = None
        validation: ValidationResult | None = None
        compile_result: CompileResult | None = None
        raw_events: list[dict] = []

        for attempt in range(self.MAX_RETRIES + 1):
            if attempt > 0:
                # 重编：把 Critic 的 improvement_tip 注入 Planner
                notes.append(f"🔄 第 {attempt} 次重编：{improvement_tip[:40]}")
                timings[f"Retry_{attempt}"] = 0

            # 1. Planner
            _t_plan = time.perf_counter()
            extra_context: dict | None = None
            if improvement_tip:
                extra_context = {"critic_feedback": improvement_tip}
            merged_context = {**(effective_context or {}), **extra_context} if extra_context else effective_context
            plan = self.planner.create_plan(user_input, world, context=merged_context)
            timings[f"Planner"] = round(time.perf_counter() - _t_plan, 3)
            world = plan.world
            notes.append(plan.summary())

            # 2. LLM
            _t_llm = time.perf_counter()
            ai_data = self._llm_generate(
                world, plan.source, plan.date,
                api_key=api_key, base_url=base_url, model=model,
                context=merged_context,
            )
            timings[f"LLM"] = round(time.perf_counter() - _t_llm, 3)

            # 3. Validator
            _t_val = time.perf_counter()
            validation = self.validator.check_data(ai_data, plan)
            timings[f"Validator"] = round(time.perf_counter() - _t_val, 3)
            if validation.warnings:
                notes.append("；".join(validation.warnings[:3]))

            # 4. Runtime
            _t_rt = time.perf_counter()
            compile_result = build_compile_result(plan.source, world, ai_data)
            timings[f"Runtime"] = round(time.perf_counter() - _t_rt, 3)

            raw_events = ai_data.get("events") or []

            # 5. Critic（v3.2 双 Agent 协作核心）
            if enable_critic:
                _t_critic = time.perf_counter()
                critic_result = self._run_critic(
                    world, user_input, raw_events,
                    compile_result.summary,
                    api_key=api_key, base_url=base_url, model=model,
                )
                timings[f"Critic{'' if attempt == 0 else '_' + str(attempt)}"] = round(time.perf_counter() - _t_critic, 3)

                collaboration.rounds.append({
                    "round": attempt + 1,
                    "score": critic_result.score,
                    "pass": critic_result.passed,
                    "issues": critic_result.critical_issues,
                    "num_events": len(raw_events),
                })

                if critic_result.passed or attempt >= self.MAX_RETRIES:
                    # 通过 或 超重编次数，退出循环
                    collaboration.final_score = critic_result.score
                    collaboration.total_retries = attempt
                    collaboration.passed = critic_result.passed
                    timings["Critic"] = timings.get(f"Critic{'' if attempt == 0 else '_' + str(attempt)}", 0)
                    notes.append(f"Critic 评分 {critic_result.score}/100 · 重编 {attempt} 次 · {'✅ 通过' if critic_result.passed else '⚠️ 超重编次数'}")
                    break
                else:
                    # 未通过，把改进建议留给下一轮
                    improvement_tip = critic_result.improvement_tip or "请让事件更贴合用户输入"
                    notes.append(f"Critic 评分 {critic_result.score}/100，未通过：{'; '.join(critic_result.critical_issues[:2])}")
            else:
                # 关闭 Critic 时直接退出循环（只执行一轮）
                break

        else:
            # for-else：如果循环正常结束（没 break），用最后一次的结果
            collaboration.final_score = 0
            collaboration.total_retries = self.MAX_RETRIES
            collaboration.passed = False

        # === Reflection ===
        _t_refl = time.perf_counter()
        reflection: ReflectionResult | None = None
        if enable_reflection:
            reflection = self.reflector.reflect(
                plan.source, raw_events, world, plan,
                api_key=api_key, base_url=base_url, model=model,
            )
        elif enable_local_reflection:
            reflection = self.reflector.reflect_local(raw_events)
        timings["Reflection"] = round(time.perf_counter() - _t_refl, 3) if (enable_reflection or enable_local_reflection) else 0
        if reflection is not None and not reflection.reasonable:
            notes.append("反思未通过：" + "；".join(reflection.issues[:3]))

        # === 世界模拟 ===
        _t_sim = time.perf_counter()
        simulation: SimulationResult | None = None
        if enable_simulation and self.simulation_engine is not None:
            try:
                simulation = self.simulation_engine.simulate(
                    raw_events,
                    state=(SimState.from_dict(simulation_state.to_dict()) if simulation_state is not None else None),
                    world=world,
                )
                if simulation.evolved:
                    notes.append(
                        f"世界演化：触发 {len(simulation.triggered_rules)} 条规则，"
                        f"生成 {len(simulation.derived_events)} 个衍生事件"
                    )
                if compile_result.emotion.source == "local" and simulation.final_state is not None:
                    compile_result.emotion = resolve_emotion(
                        ai_data, plan.source, raw_events,
                        simulation.final_state.to_dict(),
                    )
            except Exception as exc:
                notes.append(f"世界模拟失败：{exc}")
        timings["Simulation"] = round(time.perf_counter() - _t_sim, 3) if (enable_simulation and self.simulation_engine is not None) else 0

        # === 记忆归档 ===
        _t_mem = time.perf_counter()
        if memory is not None:
            try:
                tags = _collect_tags(raw_events)
                memory.save_event(
                    date=plan.date, source=plan.source,
                    summary=compile_result.summary, advice=compile_result.advice,
                    attributes=_collect_attributes(compile_result),
                    tags=tags, world_label=world.label,
                )
                memory.observe_tags(tags)
                if self._retriever is not None:
                    self._retriever.short_term.remember({
                        "date": plan.date, "summary": compile_result.summary, "tags": tags,
                    })
                notes.append(f"已归档 {len(tags)} 个标签到长期记忆")
            except Exception as exc:
                notes.append(f"记忆归档失败：{exc}")
        timings["Memory"] = round(time.perf_counter() - _t_mem, 3) if memory is not None else 0

        timings["total"] = round(time.perf_counter() - _t0, 3)

        return AgentRunResult(
            plan=plan,
            validation=validation,
            compile=compile_result,
            reflection=reflection,
            simulation=simulation,
            notes=notes,
            timings=timings,
            collaboration=collaboration if enable_critic else None,
            critic=self._last_critic_result if enable_critic else None,
        )

    # ------------------------------------------------------------------
    # Critic 辅助方法
    # ------------------------------------------------------------------
    def _run_critic(
        self,
        world: WorldProfile,
        user_input: str,
        events: list[dict],
        summary: str,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
    ) -> CriticResult:
        """执行 Critic Agent 独立质检；AI 不可用时降级为本地规则评分。"""
        try:
            verdict = self._llm_critic(
                world, user_input, events, summary,
                api_key=api_key, base_url=base_url, model=model,
            )
            result = CriticResult(
                score=verdict["score"],
                dimensions=verdict.get("dimensions", {}),
                passed=verdict["pass"],
                critical_issues=verdict.get("critical_issues", []),
                improvement_tip=verdict.get("improvement_tip", ""),
                source="ai",
            )
        except Exception as exc:
            # AI 质检失败 → 降级为本地规则评分（保守给 70 分，不阻塞编译）
            result = self._rule_based_critic(events, summary)
            result.critical_issues.append(f"Critic AI 不可用（{exc}），已降级为规则评分")
        self._last_critic_result = result   # 缓存供 AgentRunResult 使用
        return result

    @staticmethod
    def _rule_based_critic(events: list[dict], summary: str) -> CriticResult:
        """本地规则质检（AI 不可用时的降级方案）。"""
        issues: list[str] = []
        score = 70   # 保守起始分

        n = len(events)
        if n == 0:
            score -= 30; issues.append("无事件")
        elif n > 8:
            score -= 10; issues.append("事件过多")
        elif 2 <= n <= 5:
            score += 5   # 事件数量合适

        # 数值变化是否有层次
        non_zero = sum(
            1 for ev in events
            if any(ev.get(k, 0) != 0 for k in ("hp", "mp", "gold_or_san", "gold", "exp"))
        )
        if events and non_zero == 0:
            score -= 20; issues.append("所有事件数值为0")
        elif non_zero >= 2:
            score += 5

        score = max(0, min(100, score))
        return CriticResult(
            score=score,
            dimensions={},
            passed=score >= RealityAgent.CRITIC_THRESHOLD,
            critical_issues=issues,
            improvement_tip="",
            source="rule",
        )

    # ------------------------------------------------------------------
    # 便捷方法（供 UI / 测试直接拿 CompileResult）
    # ------------------------------------------------------------------
    def compile(
        self,
        user_input: str,
        world: WorldProfile | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        enable_reflection: bool = True,
    ) -> CompileResult:
        """便捷入口：只返回 CompileResult（与旧 compile_reality 行为对齐）。

        反思失败不会让编译失败——reflection 异常由 Reflector 内部降级。
        """
        return self.run(
            user_input, world,
            api_key=api_key, base_url=base_url, model=model,
            enable_reflection=enable_reflection,
        ).compile
