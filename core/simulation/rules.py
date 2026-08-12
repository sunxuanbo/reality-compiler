# -*- coding: utf-8 -*-
"""规则系统（v3.0 Phase 4）：状态阈值 → 触发衍生事件 / 标签。

对齐优化方案的核心示例：
    SleepDebt > 100 → 触发「慢性疲劳」→ 生成新事件

设计：
    - Rule：声明式规则数据类。条件 = 状态字段 + 阈值 + 方向（>= 或 <=）；
      动作 = 生成一个「衍生事件」（可再进 Runtime 结算）或加一个标签（debuff）。
    - RuleEngine：拿到一组状态后，批量检查规则，返回被触发的 Rule + 衍生事件。
    - DEFAULT_RULES：内置 3 条通用规则（睡眠债爆表→慢性疲劳、压力爆表→精神紧绷、
      精力告急→疲惫debuff）。任何一条都是「世界自己发展」的体现。
    - 可扩展：未来可给每个世界观配专属规则（WorldProfile 挂 rules），第一版先做通用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .state import SimState


# ----------------------------------------------------------------------------
# 规则数据结构
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    """一条「状态 → 动作」规则。

    字段：
        name:          规则名（用于日志 / 展示），如 "慢性疲劳"
        state_field:   要检查的状态字段（"energy" / "stress" / "sleep_debt"）
        threshold:     触发阈值
        direction:     ">="（状态 ≥ 阈值触发）或 "<="（状态 ≤ 阈值触发）
        trigger_event: 触发后生成的「衍生事件」dict（可再进 Runtime 结算）。
                       结构同 schema 事件：{name, description, hp, mp, gold_or_san, exp, tags}
        trigger_tag:   可选，追加到标签墙的 (标签名, 类型)。
        reset_field:   可选，触发后把该状态重置为 0（避免连续触发刷屏）。
    """

    name: str
    state_field: str
    threshold: int
    direction: str = ">="
    trigger_event: dict = field(default_factory=dict)
    trigger_tag: tuple[str, str] | None = None
    reset_field: bool = True

    def matches(self, state: SimState) -> bool:
        """判断当前状态是否满足触发条件。"""
        value = getattr(state, self.state_field)
        if self.direction == ">=":
            return value >= self.threshold
        if self.direction == "<=":
            return value <= self.threshold
        return False


# ----------------------------------------------------------------------------
# 内置规则（v3.0 通用规则，未来可挂到世界观上）
# ----------------------------------------------------------------------------
DEFAULT_RULES: list[Rule] = [
    Rule(
        name="慢性疲劳",
        state_field="sleep_debt",
        threshold=80,
        direction=">=",
        trigger_event={
            "name": "😴 慢性疲劳",
            "description": "长期睡眠不足，身体开始抗议了。",
            "hp": -8,
            "mp": -10,
            "gold_or_san": 0,
            "exp": 0,
            "tags": ["慢性疲劳"],
        },
        trigger_tag=("😴 慢性疲劳", "debuff red"),
    ),
    Rule(
        name="精神紧绷",
        state_field="stress",
        threshold=80,
        direction=">=",
        trigger_event={
            "name": "😖 精神紧绷",
            "description": "压力累积到临界点，注意力开始涣散。",
            "hp": -5,
            "mp": -12,
            "gold_or_san": 0,
            "exp": 0,
            "tags": ["精神紧绷"],
        },
        trigger_tag=("😖 精神紧绷", "debuff red"),
    ),
    Rule(
        name="精力告急",
        state_field="energy",
        threshold=20,
        direction="<=",
        trigger_event={
            "name": "🥱 精力告急",
            "description": "精力见底，再做下去效率只会更差。",
            "hp": -3,
            "mp": -8,
            "gold_or_san": 0,
            "exp": 0,
            "tags": ["精力告急"],
        },
        trigger_tag=("🥱 精力告急", "debuff"),
    ),
]


# ----------------------------------------------------------------------------
# 规则引擎
# ----------------------------------------------------------------------------
class RuleEngine:
    """批量检查一组规则，返回触发的规则列表。"""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = list(rules) if rules is not None else list(DEFAULT_RULES)

    def evaluate(self, state: SimState) -> list[Rule]:
        """按声明顺序检查全部规则，返回所有满足条件的 Rule。"""
        return [r for r in self.rules if r.matches(state)]

    def apply(self, state: SimState) -> list[Rule]:
        """检查并应用：触发规则时按需重置状态，返回触发的 Rule 列表。"""
        triggered = self.evaluate(state)
        for rule in triggered:
            if rule.reset_field:
                setattr(state, rule.state_field, 0)
        state.clamp()
        return triggered
