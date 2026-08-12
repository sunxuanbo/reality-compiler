# -*- coding: utf-8 -*-
"""全项目冒烟测试：import 所有核心模块，验证没有缺失/错误引用。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ok, fail = [], []
MODULES = [
    "core.agent", "core.agent.agent", "core.agent.planner",
    "core.agent.validator", "core.agent.reflector",
    "core.database", "core.database.db", "core.database.repository",
    "core.memory", "core.memory.short_term", "core.memory.long_term",
    "core.memory.retriever",
    "core.simulation", "core.simulation.state", "core.simulation.rules",
    "core.simulation.engine",
    "core.compiler", "core.runtime", "core.llm_client",
    "core.schema_validator", "core.storage", "core.logger",
    "core.world_config", "core.content_provider", "core.lexicon",
    "core.pdf_exporter",
    "ui", "ui.render",
    "ui.pages", "ui.pages.home", "ui.pages.settings", "ui.pages.report",
]
for m in MODULES:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        fail.append((m, repr(e)))

print("== 模块 import 结果 ==")
print(f"成功 {len(ok)} 个，失败 {len(fail)} 个")
for m, e in fail:
    print(f"  ✘ {m}: {e}")

# 验证测试引用的关键符号存在
from core.lexicon import Event, MatchedEvent
from core.agent import RealityAgent, Planner, Validator, Reflector, AgentPlan, ValidationResult, ReflectionResult
from core.memory import ShortTermMemory, LongTermMemory, MemoryRetriever
from core.database import Database, Repository
from core.simulation import SimState, RuleEngine, SimulationEngine, SimulationResult
print("核心符号全部可导入 ✔")
