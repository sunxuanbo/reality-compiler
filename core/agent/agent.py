# -*- coding: utf-8 -*-
"""RealityAgent：编排完整编译生命周期（v3.0 Phase 2 —— Agent 化核心）。

流程（与优化方案对齐）：
    用户输入
      ↓
    Planner     把输入 + 世界观 + 上下文 编译成结构化执行计划
      ↓
    LLM         调用 DeepSeek 生成结构化事件（复用 core.llm_client，
                内部已含 schema 安全门 + 格式重试 + 兜底）
      ↓
    Validator   语义合理性校验（事件数量 / 质量 / 修复提示）
      ↓
    Runtime     复用 core.compiler.build_compile_result + core.runtime
                （不重写，只是被 Agent 编排）
      ↓
    Reflection  AI 自我反思（合理性 / 符合人物 / 违规），异常则标记
      ↓
    返回 AgentRunResult（compile + validation + reflection）

与旧链路的兼容：
    RealityAgent.run() 返回的 AgentRunResult.compile 是 CompileResult，
    与旧 compile_reality() 返回类型完全一致——UI 层无需改动即可切换。

分层约定：core 层，纯 Python，禁止 import streamlit。
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
class AgentRunResult:
    """一次 Agent 完整运行的产物。"""

    plan: AgentPlan                              # 执行计划
    validation: ValidationResult                 # 校验结论
    compile: CompileResult                       # 编译结果（与旧 compile_reality 同类型）
    reflection: ReflectionResult | None = None   # 反思结论（关闭反思时为 None）
    simulation: SimulationResult | None = None   # 世界演化结论（v3.0 Phase 4，关闭时为 None）
    notes: list[str] = field(default_factory=list)   # 过程记录（供日志/调试）
    timings: dict = field(default_factory=dict)   # v3.1 Agent 流程可视化：每步耗时（秒）

    @property
    def reflected_ok(self) -> bool:
        """反思是否通过（未反思视为通过）。"""
        return self.reflection is None or self.reflection.reasonable

    @property
    def simulated(self) -> bool:
        """世界是否发生了演化（有衍生事件/标签/规则触发）。"""
        return self.simulation is not None and self.simulation.evolved


class RealityAgent:
    """Reality Compiler 的 Agent 控制器：编排 Planner → LLM → Validator → Runtime → Reflection。

    参数（全部可注入，便于测试与替换）：
        planner:   Planner 实例（默认）
        validator: Validator 实例（默认）
        reflector: Reflector 实例（默认）
        llm_generate: 可注入的事件生成函数（默认 core.llm_client.call_llm_for_events_full）
    """

    def __init__(
        self,
        planner: Planner | None = None,
        validator: Validator | None = None,
        reflector: Reflector | None = None,
        llm_generate=None,
        retriever=None,
        simulation_engine: SimulationEngine | None = None,
    ) -> None:
        self.planner = planner or Planner()
        self.validator = validator or Validator()
        self.reflector = reflector or Reflector()
        self._llm_generate = llm_generate or llm_client.call_llm_for_events_full
        # v3.0 Phase 3 记忆检索器（None = 不启用记忆）。可注入替换（测试用）。
        self._retriever = retriever
        # v3.0 Phase 4 世界模拟引擎（None = 不启用世界演化）。可注入替换（测试用）。
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
    ) -> AgentRunResult:
        """执行完整编译生命周期。

        参数：
            user_input: 用户写的现实日常
            world:      当前世界观；None 时用 FALLBACK_WORLD
            api_key / base_url / model: 透传给 LLM 调用
            context:    调用方手动注入的上下文（优先级最高，覆盖记忆检索）
            enable_reflection: 是否启用 AI 反思（默认开启；关闭时跳过反思环节）
            enable_local_reflection: AI 反思关闭时，是否执行零网络请求的本地规则复核。
            memory:     长期记忆（v3.0 Phase 3）。传 None 时不使用记忆；
                        传入 LongTermMemory 时：编译前自动检索注入上下文，
                        编译后自动归档事件与标签偏好。
            enable_simulation: 是否启用世界模拟（v3.0 Phase 4，默认开启）。
                        开启时用 SimulationEngine 跑「事件→状态→规则→衍生事件」演化；
                        构造 Agent 时传了 simulation_engine 才真正生效。
            simulation_state: 上一次模拟后的隐藏状态；传入后在其基础上继续累积。
        返回：
            AgentRunResult
        异常：
            ValueError：输入为空（Planner 抛出）
            RuntimeError：LLM 调用失败（沿用现有中文错误语义，由 UI 层捕获）
        """
        notes: list[str] = []
        timings: dict[str, float] = {}
        _t0 = time.perf_counter()

        # 1. Planner：先把输入编译成执行计划
        #    记忆接入：若传入了 LongTermMemory，先用 retriever 检索记忆上下文
        #    （用户档案 / 近期事件 / 长期偏好），再注入 Planner 与 LLM 提示词。
        effective_context = context
        if memory is not None and self._retriever is not None and effective_context is None:
            try:
                # 不按今天过滤：长期记忆的价值正在于跨天延续最近经历。
                retrieved = self._retriever.retrieve()
                if retrieved:
                    effective_context = retrieved
                    notes.append("已注入记忆上下文")
            except Exception as exc:     # 记忆检索失败绝不影响编译
                notes.append(f"记忆检索失败：{exc}")
        _t_plan = time.perf_counter()
        plan = self.planner.create_plan(user_input, world, context=effective_context)
        timings["Planner"] = round(time.perf_counter() - _t_plan, 3)
        world = plan.world
        notes.append(plan.summary())

        # 2. LLM：按计划生成结构化事件（已含 schema 安全门 + 格式重试 + 兜底）
        _t_llm = time.perf_counter()
        ai_data = self._llm_generate(
            world, plan.source, plan.date,
            api_key=api_key, base_url=base_url, model=model,
            context=effective_context,
        )
        timings["LLM"] = round(time.perf_counter() - _t_llm, 3)

        # 3. Validator：语义合理性校验
        _t_val = time.perf_counter()
        validation = self.validator.check_data(ai_data, plan)
        timings["Validator"] = round(time.perf_counter() - _t_val, 3)
        if validation.warnings:
            notes.append("；".join(validation.warnings[:3]))

        # 4. Runtime：复用编译器组装 CompileResult（不重写）
        _t_rt = time.perf_counter()
        compile_result = build_compile_result(plan.source, world, ai_data)
        timings["Runtime"] = round(time.perf_counter() - _t_rt, 3)

        # 5. Reflection：AI 深度反思与本地快速复核均可选，保持旧接口语义。
        _t_refl = time.perf_counter()
        reflection: ReflectionResult | None = None
        raw_events = ai_data.get("events") or []
        if enable_reflection:
            reflection = self.reflector.reflect(
                plan.source,
                raw_events,
                world,
                plan,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        elif enable_local_reflection:
            reflection = self.reflector.reflect_local(raw_events)
        timings["Reflection"] = round(time.perf_counter() - _t_refl, 3) if (enable_reflection or enable_local_reflection) else 0
        if reflection is not None and not reflection.reasonable:
            notes.append("反思未通过：" + "；".join(reflection.issues[:3]))

        # 5.5 世界模拟（v3.0 Phase 4）：事件 → 状态变化 → 规则触发 → 衍生事件。
        #     让世界自己发展；模拟失败/关闭绝不影响编译主流程。
        _t_sim = time.perf_counter()
        simulation: SimulationResult | None = None
        if enable_simulation and self.simulation_engine is not None:
            try:
                raw_events = ai_data.get("events") or []
                # 模拟引擎会原地修改 SimState；复制一份再运行，保证后续步骤若失败，
                # 调用方保存的上一状态不会被半途污染。
                state_for_run = (
                    SimState.from_dict(simulation_state.to_dict())
                    if simulation_state is not None else None
                )
                simulation = self.simulation_engine.simulate(
                    raw_events,
                    state=state_for_run,
                    world=world,
                )
                if simulation.evolved:
                    notes.append(
                        f"世界演化：触发 {len(simulation.triggered_rules)} 条规则，"
                        f"生成 {len(simulation.derived_events)} 个衍生事件"
                    )
                # 低置信度/旧格式响应由本地兜底时，把模拟后的压力、精力和睡眠债也纳入判断。
                if compile_result.emotion.source == "local" and simulation.final_state is not None:
                    compile_result.emotion = resolve_emotion(
                        ai_data,
                        plan.source,
                        raw_events,
                        simulation.final_state.to_dict(),
                    )
            except Exception as exc:     # 模拟失败绝不影响编译
                notes.append(f"世界模拟失败：{exc}")
        timings["Simulation"] = round(time.perf_counter() - _t_sim, 3) if (enable_simulation and self.simulation_engine is not None) else 0

        # 6. 记忆归档（v3.0 Phase 3）：编译成功后把事件快照 + 标签偏好写入长期记忆。
        #    失败静默，绝不影响编译结果。
        _t_mem = time.perf_counter()
        if memory is not None:
            try:
                tags = _collect_tags(ai_data.get("events") or [])
                memory.save_event(
                    date=plan.date,
                    source=plan.source,
                    summary=compile_result.summary,
                    advice=compile_result.advice,
                    attributes=_collect_attributes(compile_result),
                    tags=tags,
                    world_label=world.label,
                )
                memory.observe_tags(tags)
                if self._retriever is not None:
                    self._retriever.short_term.remember({
                        "date": plan.date,
                        "summary": compile_result.summary,
                        "tags": tags,
                    })
                notes.append(f"已归档 {len(tags)} 个标签到长期记忆")
            except Exception as exc:   # pragma: no cover
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
