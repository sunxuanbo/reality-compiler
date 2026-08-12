# -*- coding: utf-8 -*-
"""Agent 层自检（v3.0 Phase 2）：Planner / Validator / Reflector / RealityAgent。

运行方式：python tests/test_agent.py
覆盖重点：
    - Planner：输入清洗 / 空输入 / 超长截断 / 计划约束与 schema 一致
    - Validator：正常通过 / 语义警告（事件过多 / 空名 / 无标签）/ 格式异常
    - Reflector：本地规则兜底（越界数值 / 全零假事件）/ AI 反思注入 / AI 不可用降级
    - RealityAgent：全链路编排（fake LLM 注入）→ CompileResult 类型与旧入口一致
"""

from __future__ import annotations

import os
import sys
import json
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 统一从项目根目录 import，保证包路径一致
from core.agent import (
    Planner, AgentPlan,
    Validator, ValidationResult,
    Reflector, ReflectionResult,
    RealityAgent,
)
from core.world_config import FALLBACK_WORLD, world_from_ai


PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    """断言并计数。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✔ {name}")
    else:
        FAIL += 1
        print(f"  ✘ FAIL: {name}")


def _test_world(name: str = "赛博纪元", currency: str = "比特币") -> object:
    """构造一个最小世界观（复用 FALLBACK_WORLD 的转换函数）。"""
    data = {
        "world_name": name,
        "world_description": "AI 生成的测试世界观",
        "currency_name": currency,
        "stat_mapping": {"hp": "生命值", "mp": "精力值", "gold": currency},
    }
    return world_from_ai(data, "day-test")


def _plan(text: str = "今天加班到凌晨") -> AgentPlan:
    return Planner().create_plan(text, _test_world())


def main() -> None:
    print("=== Agent 层自检 ===")

    # 1. Planner
    print("\n[1] Planner")
    planner = Planner()

    # 1.1 正常计划
    plan = planner.create_plan("  今天加班到凌晨  ", _test_world())
    check("输入去空白", plan.source == "今天加班到凌晨")
    check("计划含世界观", plan.world.label == "赛博纪元")
    check("计划含目标", bool(plan.objectives))
    check("计划含数值约束", plan.constraints["exp"] == [0, 15])
    check("计划含输出规格", plan.output_spec["format"] == "json_object")
    check("计划日期为今天", plan.date == datetime.date.today().isoformat())

    # 1.2 空输入
    try:
        planner.create_plan("   ", _test_world())
        check("空输入抛异常", False)
    except ValueError:
        check("空输入抛异常", True)

    # 1.3 超长截断
    long_text = "啊" * 5000
    plan = planner.create_plan(long_text, _test_world(), date="2026-08-08")
    check("超长输入截断", len(plan.source) <= planner.max_input_len)
    check("截断标记已记录", plan.output_spec["truncated_input"] is True)
    check("指定日期生效", plan.date == "2026-08-08")

    # 1.4 无世界观回退
    plan = planner.create_plan("x", None)
    check("无世界观回退兜底世界", plan.world is FALLBACK_WORLD or plan.world.label == FALLBACK_WORLD.label)

    # 2. Validator
    print("\n[2] Validator")
    validator = Validator()

    # 2.1 正常 JSON 通过
    good = json.dumps({
        "events": [{"name": "加班", "hp": -10, "mp": -5, "gold_or_san": -3,
                    "exp": 2, "tags": ["加班"]}],
    })
    v = validator.check(good, _plan())
    check("正常 JSON 通过", v.ok is True and v.data is not None)

    # 2.2 带解释文字也能提取
    messy = "当然，我来分析：\n" + json.dumps({
        "events": [{"name": "早起", "hp": 5, "exp": 1, "tags": ["健康"]}],
    })
    v = validator.check(messy, _plan())
    check("解释文字 + JSON 可提取", v.ok is True and len(v.data["events"]) == 1)

    # 2.3 纯文字 → 不通过（需重生成）
    v = validator.check("完全不是 JSON", _plan())
    check("纯文字不通过", v.ok is False)

    # 2.4 事件过多 → 语义警告但通过
    many = {"events": [{"name": f"E{i}", "hp": 0, "exp": 1, "tags": ["t"]} for i in range(10)]}
    v = validator.check(json.dumps(many), _plan())
    check("事件过多给警告", any("超出建议上限" in w for w in v.warnings))

    # 2.5 无标签 → 警告
    notag = {"events": [{"name": "事件", "hp": 0, "exp": 1}]}
    v = validator.check(json.dumps(notag), _plan())
    check("无标签给警告", any("标签" in w for w in v.warnings))

    # 2.6 缺可选字段 → 补 0（repaired 标记）
    missing = {"events": [{"name": "事件", "tags": ["t"]}]}
    v = validator.check(json.dumps(missing), _plan())
    check("缺字段补 0", v.data["events"][0]["hp"] == 0)

    # 2.7 check_data 入口（已过 schema 的 dict）
    v2 = validator.check_data({"events": [{"name": "事件", "hp": 1, "exp": 1}]}, _plan())
    check("check_data 入口可用", v2.ok is True)

    # 3. Reflector
    print("\n[3] Reflector")
    reflector = Reflector()

    # 3.1 正常事件 → AI 反思注入（fake 返回合理）
    fake_ok = {
        "reasonable": True,
        "issues": [],
        "suggestion": "整体合理。",
    }
    r = Reflector(llm_reflect=lambda *a, **k: dict(fake_ok)).reflect(
        "今天加班", [{"name": "加班", "hp": -10, "exp": 2}], _test_world(), _plan(),
    )
    check("AI 反思通过", r.reasonable is True and r.source == "ai")

    # 3.2 AI 反思判不合理（本地规则可通过、但 AI 判定不合理的事件）
    fake_bad = {
        "reasonable": False,
        "issues": ["普通日常获得 20 金币偏多，且与原文无关"],
        "suggestion": "重新生成。",
    }
    r = Reflector(llm_reflect=lambda *a, **k: dict(fake_bad)).reflect(
        "今天加班", [{"name": "暴富", "gold_or_san": 20, "exp": 2}], _test_world(), _plan(),
    )
    check("AI 反思判不合理", r.reasonable is False and r.source == "ai")
    check("反思问题已记录", bool(r.issues))

    # 3.3 AI 不可用 → 本地规则降级
    r = Reflector(llm_reflect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))).reflect(
        "今天加班", [{"name": "加班", "hp": -10, "exp": 2}], _test_world(), _plan(),
    )
    check("AI 不可用降级本地规则", r.source == "rule" and r.reasonable is True)

    # 3.4 本地规则：数值越界 → 不通过
    r = reflector.reflect("x", [{"name": "恶意", "hp": -99999, "exp": 2}], _test_world(), _plan())
    check("越界数值被本地规则拦下", r.reasonable is False)

    # 3.5 本地规则：全零假事件 → 不通过
    r = reflector.reflect("x", [{"name": "空", "hp": 0, "exp": 0}], _test_world(), _plan())
    check("全零假事件被拦下", r.reasonable is False)

    # 4. RealityAgent 全链路
    print("\n[4] RealityAgent")

    # 注入 fake LLM：返回合法事件 dict（与 call_llm_for_events_full 相同结构）
    def _fake_llm(world, user_text, date_str, **kw):
        return {
            "world_display_name": world.label,
            "summary": "加班的一天，注意身体。",
            "advice": "早点休息。",
            "events": [
                {"name": "加班", "description": "肝到凌晨", "hp": -10, "mp": -5,
                 "gold_or_san": -3, "exp": 2, "tags": ["加班"]},
            ],
        }

    agent = RealityAgent(llm_generate=_fake_llm)
    result = agent.run("今天加班到凌晨", _test_world(), enable_reflection=False)
    check("Agent.run 返回 AgentRunResult", result is not None)
    check("compile 是 CompileResult 类型", result.compile.source == "今天加班到凌晨")
    check("compile 含命中事件", len(result.compile.matched) == 1)
    check("compile 含伪代码", "def" in result.compile.code or "player" in result.compile.code)
    check("compile 含摘要", result.compile.summary.startswith("加班"))
    check("plan 已生成", result.plan.world.label == "赛博纪元")
    check("validation 通过", result.validation.ok is True)
    check("reflection 关闭时为 None", result.reflection is None)

    # 4.0b 主页快速模式：只做本地复核，绝不触发第二次 AI 调用
    reflection_calls = []
    fast_agent = RealityAgent(
        llm_generate=_fake_llm,
        reflector=Reflector(llm_reflect=lambda *a, **k: reflection_calls.append(1)),
    )
    fast_result = fast_agent.run(
        "今天加班到凌晨", _test_world(),
        enable_reflection=False, enable_local_reflection=True,
    )
    check("快速模式保留本地质量复核", fast_result.reflection is not None and fast_result.reflection.source == "rule")
    check("快速模式不发起第二次 AI 反思", reflection_calls == [])

    # 4.1 开启反思（注入 fake Reflector 的 llm_reflect）
    agent2 = RealityAgent(
        llm_generate=_fake_llm,
        reflector=Reflector(llm_reflect=lambda *a, **k: {
            "reasonable": True, "issues": [], "suggestion": "",
        }),
    )
    result2 = agent2.run("今天加班到凌晨", _test_world(), enable_reflection=True)
    check("反思开启时 reflection 非 None", result2.reflection is not None)
    check("反思通过标记", result2.reflected_ok is True)

    # 4.2 便捷入口 compile() 与旧入口同类型
    r3 = agent.compile("今天加班到凌晨", _test_world(), enable_reflection=False)
    check("compile() 便捷入口可用", hasattr(r3, "matched") and hasattr(r3, "code"))

    # 4.2b 世界模拟接入（v3.0 Phase 4）：注入 SimulationEngine
    from core.simulation import SimulationEngine, SimState
    agent_sim = RealityAgent(
        llm_generate=_fake_llm,
        simulation_engine=SimulationEngine(),
    )
    res_sim = agent_sim.run("今天加班到凌晨", _test_world(),
                            enable_reflection=False, enable_simulation=True)
    check("世界模拟开启时 simulation 非 None", res_sim.simulation is not None)
    res_acc = agent_sim.run(
        "今天加班到凌晨", _test_world(),
        enable_reflection=False, enable_simulation=True,
        simulation_state=SimState(sleep_debt=70),
    )
    check("世界模拟可从上次隐藏状态继续累积",
          any(r.name == "慢性疲劳" for r in res_acc.simulation.triggered_rules))
    agent_nosim = RealityAgent(llm_generate=_fake_llm)
    res_nosim = agent_nosim.run("今天加班到凌晨", _test_world(),
                                enable_reflection=False, enable_simulation=True)
    check("未注入引擎时 simulation 为 None", res_nosim.simulation is None)
    check("simulation 关闭不报错", res_nosim.compile.source == "今天加班到凌晨")

    # 4.3 空输入 → ValueError
    try:
        agent.run("   ", _test_world())
        check("Agent 空输入抛异常", False)
    except ValueError:
        check("Agent 空输入抛异常", True)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    if FAIL:
        sys.exit(1)
    print("全部 Agent 层自检通过 ✔")


if __name__ == "__main__":
    main()
