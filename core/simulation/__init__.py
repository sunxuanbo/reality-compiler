# -*- coding: utf-8 -*-
"""世界模拟引擎（v3.0 Phase 4）：让世界自己发展 —— 事件影响事件。

背景（对齐优化方案）：
    旧链路：事件(熬夜, HP-5) → Runtime 直接结算 → 结束。
    新链路：事件 → 状态变化(Energy -10 / Stress +15 / SleepDebt +20)
          → 规则系统(若 SleepDebt>100 → 触发「慢性疲劳」) → 生成衍生新事件。

结构（对齐方案 Runtime 拆分，但不重写现有 core/runtime.py）：
    state.py    隐藏状态（Energy / Stress / SleepDebt）+ 事件→状态推导
    rules.py    规则系统（状态阈值 → 触发衍生事件/标签，声明式可扩展）
    engine.py   模拟引擎（事件→状态→规则→衍生事件 的编排，产出 SimulationResult）

设计原则（Agent.md 铁律）：
    - core/ 层，纯 Python，禁止 import streamlit
    - 不重写现有 Runtime（最有价值资产）；本包是「世界演化」增强层，可选接入
    - Event Graph（事件图）复杂度高，v3.0 第一版不实现（方案明确建议）
"""

from .state import SimState, derive_state_changes, STATE_LIMITS   # noqa: F401
from .rules import Rule, RuleEngine, DEFAULT_RULES   # noqa: F401
from .engine import SimulationEngine, SimulationResult   # noqa: F401

__all__ = [
    "SimState",
    "derive_state_changes",
    "STATE_LIMITS",
    "Rule",
    "RuleEngine",
    "DEFAULT_RULES",
    "SimulationEngine",
    "SimulationResult",
]
