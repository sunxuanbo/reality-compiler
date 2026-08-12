# -*- coding: utf-8 -*-
"""记忆系统（v3.0 Phase 3）：让 Agent「记住」用户——不是简单存档，而是会使用数据。

结构（对齐优化方案）：
    short_term.py   短期记忆：本次进程内最近的 N 条事件（不落盘，随进程消失）
    long_term.py    长期记忆：SQLite 持久化的用户档案 / 历史事件 / 长期偏好
    retriever.py    检索器：把记忆检索成 Planner 可用的上下文 dict

设计要点：
    - 记忆的「写入」由 Agent 在编译后触发（见 core.agent.agent.RealityAgent.save_to_memory）
    - 记忆的「读取」由 Planner 的 context 参数消费（见 core.agent.planner.AgentPlan.context）
    - 记忆系统【默认不启用】：UI 需用户在「设置」页开启「启用记忆」，与日志开关同样尊重隐私。
    - 短期记忆在进程内保留（Streamlit 会话重启即清空）；长期记忆落盘 SQLite。

分层约定（Agent.md 铁律）：
    本包属于 core/ 引擎层，纯 Python，【禁止 import streamlit】。
"""

from .short_term import ShortTermMemory   # noqa: F401
from .long_term import LongTermMemory     # noqa: F401
from .retriever import MemoryRetriever     # noqa: F401

__all__ = ["ShortTermMemory", "LongTermMemory", "MemoryRetriever"]
