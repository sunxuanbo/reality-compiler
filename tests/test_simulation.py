# -*- coding: utf-8 -*-
"""世界模拟自检（v3.0 Phase 4）：state / rules / engine。

运行方式：python tests/test_simulation.py
覆盖重点：
    - SimState：clamp / apply_delta / to_dict / from_dict / fresh_day
    - derive_state_changes：关键词推导（熬夜→睡眠债+压力；睡觉→恢复）
    - Rule / RuleEngine：阈值判断 / 触发 / 重置
    - SimulationEngine：事件→状态→规则→衍生事件的完整编排
    - 与 Runtime 兼容：MatchedEvent 形态也能跑
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.simulation import (
    SimState, derive_state_changes,
    Rule, RuleEngine, DEFAULT_RULES,
    SimulationEngine, SimulationResult,
)
from core.lexicon import MatchedEvent, Event as LexEvent


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


def _lex_event(name: str, hp: int = 0, exp: int = 0, keywords=None) -> MatchedEvent:
    """构造一个 Lexicon MatchedEvent（验证与 Runtime 兼容）。"""
    ev = LexEvent(
        key=f"sim_{name}", name=name, icon="✨", keywords=tuple(keywords or []),
        hp=hp, mp=0, gold=0, exp=exp,
    )
    return MatchedEvent(event=ev, hit_words=keywords or [], scale=1.0)


def main() -> None:
    print("=== 世界模拟自检 ===")

    # 1. SimState
    print("\n[1] SimState")
    s = SimState(energy=50, stress=30, sleep_debt=20)
    check("默认状态构造", s.energy == 50 and s.stress == 30 and s.sleep_debt == 20)

    s2 = SimState(energy=999, stress=-5, sleep_debt=200)
    s2.clamp()
    check("clamp 越界", s2.energy == 100 and s2.stress == 0 and s2.sleep_debt == 100)

    s3 = SimState(energy=80).apply_delta({"energy": -90, "stress": +50})
    check("apply_delta 并夹紧", s3.energy == 0 and s3.stress == 60)

    d = s3.to_dict()
    check("to_dict", d == {"energy": 0, "stress": 60, "sleep_debt": 10})
    s4 = SimState.from_dict(d)
    check("from_dict 恢复", s4.energy == 0 and s4.sleep_debt == 10)
    s5 = SimState.from_dict(None)
    check("from_dict 缺省", s5.energy == 70)
    s6 = SimState.fresh_day()
    check("fresh_day 初始状态", 0 <= s6.energy <= 100 and s6.sleep_debt <= 30)

    # 2. derive_state_changes
    print("\n[2] 状态推导")
    delta = derive_state_changes("熬夜加班到凌晨", tags=["加班"])
    # 实际推导：sleep_debt=+30（熬夜+凌晨+加班到 与 加班 都命中），stress=+8（加班），energy=-15（熬夜）
    check("熬夜→睡眠债+压力+精力消耗", delta.get("sleep_debt", 0) >= 20
          and delta.get("stress", 0) >= 8 and delta.get("energy", 0) <= -10)

    delta2 = derive_state_changes("早睡早起", tags=["健康"])
    check("睡觉→恢复睡眠债/压力/精力", delta2.get("sleep_debt", 0) < 0
          and delta2.get("energy", 0) > 0)

    delta3 = derive_state_changes("普通散步", tags=["日常"])
    check("散步→减压", delta3.get("stress", 0) < 0)

    delta4 = derive_state_changes("完全无关的内容", tags=["x"])
    check("无关事件无状态影响", delta4 == {} or all(v == 0 for v in delta4.values()))

    # 3. Rule / RuleEngine
    print("\n[3] 规则系统")
    r1 = Rule(name="测试规则", state_field="sleep_debt", threshold=80,
              trigger_event={"name": "慢性疲劳"}, trigger_tag=("😴", "debuff"))
    check("规则条件判断（未达阈值）", r1.matches(SimState(sleep_debt=50)) is False)
    check("规则条件判断（已达阈值）", r1.matches(SimState(sleep_debt=90)) is True)
    check(">= 方向", Rule("x", "stress", 60, ">=").matches(SimState(stress=60)) is True)
    check("<= 方向", Rule("x", "energy", 20, "<=").matches(SimState(energy=10)) is True)

    engine = RuleEngine([r1])
    st = SimState(sleep_debt=90)
    triggered = engine.apply(st)
    check("触发规则", len(triggered) == 1 and triggered[0].name == "测试规则")
    check("触发后重置状态", st.sleep_debt == 0)

    check("内置规则 3 条", len(DEFAULT_RULES) == 3)

    # 4. SimulationEngine 完整编排
    print("\n[4] 模拟引擎")
    sim = SimulationEngine()
    events = [
        {"name": "加班到凌晨", "tags": ["加班", "熬夜"]},
        {"name": "又被骂了", "tags": ["压力"]},
    ]
    res = sim.simulate(events)
    check("返回 SimulationResult", isinstance(res, SimulationResult))
    check("轨迹记录每步演化", len(res.trajectory) == 2)
    check("状态被累积", res.final_state.sleep_debt > 0 and res.final_state.stress > 0)
    check("轨迹含事件名", res.trajectory[0][0] == "加班到凌晨")
    check("轨迹增量非空", bool(res.trajectory[0][1]))
    check("终端行生成", len(res.lines) >= 3)
    check("无规则触发时 evolved 为 False", res.evolved is False)

    # 5. 规则触发 → 衍生事件（模拟连续熬夜）
    print("\n[5] 世界演化（规则触发）")
    sim2 = SimulationEngine()
    night = {"name": "熬夜", "tags": ["熬夜"]}
    # 连续 6 次熬夜：每次 +20 睡眠债 → 超过 80 触发慢性疲劳
    res2 = sim2.simulate([night] * 6)
    check("触发慢性疲劳规则", any(r.name == "慢性疲劳" for r in res2.triggered_rules))
    check("生成衍生事件", len(res2.derived_events) >= 1
          and res2.derived_events[0]["name"] == "😴 慢性疲劳")
    check("生成衍生标签", len(res2.derived_tags) >= 1)
    check("evolved 为 True", res2.evolved is True)
    check("规则重置后睡眠债下降", res2.final_state.sleep_debt < 80)

    # 6. 与 Runtime 兼容（MatchedEvent 形态）
    print("\n[6] Runtime 兼容")
    sim3 = SimulationEngine()
    lex_events = [
        _lex_event("熬夜加班", hp=-5, keywords=["熬夜", "加班"]),
        _lex_event("被骂", hp=-3, keywords=["压力"]),
    ]
    res3 = sim3.simulate(lex_events)
    check("MatchedEvent 形态可跑", len(res3.trajectory) == 2)
    check("MatchedEvent 推导生效", res3.final_state.sleep_debt > 0)

    # 7. 自定义状态起点（跨天 fresh_day 传入）
    print("\n[7] 自定义起点")
    sim4 = SimulationEngine()
    res4 = sim4.simulate([], state=SimState.fresh_day())
    check("空事件也返回状态", res4.final_state is not None)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    if FAIL:
        sys.exit(1)
    print("全部世界模拟自检通过 ✔")


if __name__ == "__main__":
    main()
