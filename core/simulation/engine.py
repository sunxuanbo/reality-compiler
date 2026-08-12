# -*- coding: utf-8 -*-
"""模拟引擎（v3.0 Phase 4）：事件 → 状态变化 → 规则触发 → 衍生事件 的完整编排。

对齐优化方案的核心思想「事件影响事件」：
    熬夜
      ↓ 状态变化
    Energy -10 / Stress +15 / SleepDebt +20
      ↓ 规则系统
    若 SleepDebt > 80 → 触发「慢性疲劳」
      ↓ 生成新事件
    慢性疲劳 也参与结算

与 core/runtime.py 的关系（重要）：
    - runtime.py 结算「可见属性」（HP/MP/可变属性/EXP）——本轮不改动它。
    - simulation/engine.py 是「世界演化」增强层：在 runtime 结算之后，或独立运行，
      用「隐藏状态」让世界自己发展。
    - UI 层把两部分的产物合起来展示（属性面板来自 runtime，世界演化面板来自 simulation）。

设计：
    - SimulationEngine.simulate(events, state=None, world=None) → SimulationResult
      events: 本次编译的命中事件（MatchedEvent 或轻量 dict，见 _plain_events）
      state:  初始隐藏状态（默认 SimState()；跨天可用 SimState.fresh_day()）
    - 产出：状态演化轨迹 + 触发的规则 + 生成的衍生事件 + 更新后的状态
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .state import SimState, derive_state_changes
from .rules import Rule, RuleEngine, DEFAULT_RULES


@dataclass
class SimulationResult:
    """一次世界演化的完整产物。"""

    # 状态演化轨迹：每一步的 (事件名, 状态增量 dict, 演化后状态 dict)
    trajectory: list[tuple[str, dict, dict]] = field(default_factory=list)
    triggered_rules: list[Rule] = field(default_factory=list)     # 触发的规则
    derived_events: list[dict] = field(default_factory=list)      # 衍生事件（可直接再结算）
    derived_tags: list[tuple[str, str]] = field(default_factory=list)  # 衍生标签
    final_state: SimState | None = None                           # 演化后的状态
    lines: list[str] = field(default_factory=list)                # 终端行（供 UI）

    @property
    def evolved(self) -> bool:
        """世界是否发生了演化（有衍生事件或标签）。"""
        return bool(self.triggered_rules or self.derived_events or self.derived_tags)


class SimulationEngine:
    """世界模拟引擎：把事件跑一遍「状态 → 规则 → 衍生」演化。"""

    def __init__(self, rules: list[Rule] | None = None, *, debug: bool = False) -> None:
        self.rule_engine = RuleEngine(rules if rules is not None else list(DEFAULT_RULES))
        self.debug = debug

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def simulate(
        self,
        events: list,
        state: SimState | None = None,
        *,
        world=None,  # noqa: ANN001 保留参数位，未来可挂世界观专属规则
    ) -> SimulationResult:
        """跑一次世界演化。

        参数：
            events: 本次编译的命中事件列表。支持两种形态：
                    - core.lexicon.MatchedEvent（有 .event.name/.event.keywords）
                    - 轻量 dict：{"name": ..., "tags": [...], "description": ...}
            state:  初始隐藏状态；None 时用 SimState()（今天刚开始）。
                    （跨天建议用 SimState.fresh_day()，见 state.py）
            world:  可选，世界观对象（未来放世界观专属规则，第一版忽略）
        返回：
            SimulationResult
        """
        result = SimulationResult(final_state=state or SimState())
        lines: list[str] = result.lines
        emit = lines.append

        state_obj = result.final_state
        state_obj.clamp()
        emit("[sim] 世界模拟开始 · 初始状态 "
             f"Energy={state_obj.energy} Stress={state_obj.stress} "
             f"SleepDebt={state_obj.sleep_debt}")

        # 1. 逐事件推导状态变化
        plain = self._to_plain(events)
        for ev in plain:
            delta = derive_state_changes(
                ev.get("name", ""),
                tags=ev.get("tags"),
                description=ev.get("description", ""),
            )
            before = state_obj.to_dict()
            state_obj.apply_delta(delta)
            after = state_obj.to_dict()
            result.trajectory.append((ev.get("name", "?"), delta, after))
            if delta:
                d_txt = " ".join(f"{k} {v:+d}" for k, v in sorted(delta.items()))
                emit(f"  · {ev.get('name', '?')}: {d_txt}")
                emit(f"      → Energy={after['energy']} Stress={after['stress']} "
                     f"SleepDebt={after['sleep_debt']}")
            elif self.debug:
                emit(f"  · {ev.get('name', '?')}: 无状态影响")

        # 2. 规则系统：状态阈值检查 → 触发衍生事件 / 标签
        triggered = self.rule_engine.apply(state_obj)
        result.triggered_rules = triggered
        for rule in triggered:
            ev = dict(rule.trigger_event or {})
            if ev:
                result.derived_events.append(ev)
            if rule.trigger_tag:
                result.derived_tags.append(rule.trigger_tag)
            emit(f"[rule] 触发「{rule.name}」（{rule.state_field} 阈值 "
                 f"{rule.direction}{rule.threshold}）")

        # 3. 收尾
        if not triggered and not any(t[1] for t in result.trajectory):
            emit("[sim] 无规则触发，世界平静如常")
        elif triggered:
            emit("[sim] 世界因规则发生了演化 ✔")
        emit("[sim] 世界模拟完成")

        return result

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _to_plain(events: list) -> list[dict]:
        """把事件列表归一化成轻量 dict（兼容 MatchedEvent 与 dict 两种形态）。"""
        out: list[dict] = []
        for e in events or []:
            if isinstance(e, dict):
                out.append({
                    "name": str(e.get("name", "") or ""),
                    "tags": e.get("tags") or [],
                    "description": str(e.get("description", "") or ""),
                })
            else:
                # MatchedEvent / LexEvent 形态
                event_obj = getattr(e, "event", e)
                out.append({
                    "name": str(getattr(event_obj, "name", "") or ""),
                    "tags": list(getattr(event_obj, "keywords", []) or []),
                    "description": str(getattr(event_obj, "description", "") or ""),
                })
        return out
