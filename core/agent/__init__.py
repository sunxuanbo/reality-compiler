# -*- coding: utf-8 -*-
"""Agent 层（v3.0 Phase 2）：把「LLM → Compiler → Runtime」升级为真正的 Agent 生命周期。

流程：
    用户输入
      ↓
    Planner     把输入 + 世界观 + 上下文 编译成结构化执行计划
      ↓
    LLM         调用 DeepSeek 生成结构化事件（复用 core.llm_client 安全门）
      ↓
    Validator   校验输出合理性（schema 安全门 + 语义合理性规则）
      ↓
    Runtime     复用 core.runtime 结算属性
      ↓
    Reflection  AI 自我反思（合理性 / 是否符合人物 / 是否违反规则）

对外主要暴露：
    RealityAgent（core.agent.agent）—— 编排完整生命周期，返回 CompileResult。

分层约定（Agent.md 铁律）：
    本包属于 core/ 引擎层，纯 Python，【禁止 import streamlit】。
    不重写现有 Runtime / Compiler / LLM，而是把它们「包」进 Agent 生命周期。
"""

from .agent import RealityAgent   # noqa: F401  编排入口
from .planner import Planner, AgentPlan   # noqa: F401
from .validator import Validator, ValidationResult   # noqa: F401
from .reflector import Reflector, ReflectionResult   # noqa: F401

__all__ = [
    "RealityAgent",
    "Planner",
    "AgentPlan",
    "Validator",
    "ValidationResult",
    "Reflector",
    "ReflectionResult",
]
