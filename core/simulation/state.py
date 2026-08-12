# -*- coding: utf-8 -*-
"""隐藏状态层（v3.0 Phase 4）：Energy / Stress / SleepDebt 三个「看不见但会累积」的状态。

背景：
    Runtime 结算的是「可见属性」（HP / MP / 可变属性 / EXP）——每个事件即时生效。
    但真实世界不是这样：熬夜不是「立刻-5 HP」就完了，而是慢慢累积「睡眠债」；
    加班久了累积「压力」；压力爆表才触发「慢性疲劳」。
    这一层就是「看不见的世界状态」：从事件推导状态变化，供规则系统判断。

设计：
    - SimState：三个隐藏状态的容器（全部 0~100，越高越「坏」的是 Stress/SleepDebt，
      Energy 越高越「好」）。全部用 clamp 保证不越界。
    - derive_state_changes()：用「关键词表」从事件名/标签/描述推导状态增量。
      纯本地、可测、不依赖 LLM——这样即使 AI 没打对标签，世界也会自己演化。
    - 关键词表集中放顶部（DEFAULT_DERIVERS），方便调平衡；未来可加「AI 推导」。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ----------------------------------------------------------------------------
# 状态范围（集中放顶部，方便调平衡）
# ----------------------------------------------------------------------------
STATE_LIMITS = {
    "energy": (0, 100),      # 精力：0 疲惫不堪 / 100 精力充沛
    "stress": (0, 100),      # 压力：0 轻松 / 100 濒临崩溃
    "sleep_debt": (0, 100),  # 睡眠债：0 无债 / 100 严重透支
}

DEFAULT_ENERGY = 70      # 初始精力（新的一天，假设休息得差不多）
DEFAULT_STRESS = 10      # 初始压力（轻微）
DEFAULT_SLEEP_DEBT = 10  # 初始睡眠债（一点，不健康作息累积来的）


# ----------------------------------------------------------------------------
# 状态推导关键词表
# ----------------------------------------------------------------------------
# 每一项：(状态名, 增量, 关键词列表)。命中任一关键词即累加该增量。
# 增量可为正（增加状态）或负（减少状态），最后统一 clamp 到 STATE_LIMITS。
# 注意：
#   - sleep_debt 和 stress 都是「越大越坏」；energy 是「越大越好」。
#   - 「休息类」关键词会减少 sleep_debt / stress、增加 energy。
DEFAULT_DERIVERS: list[tuple[str, int, tuple[str, ...]]] = [
    # —— 睡眠债累积 ——
    ("sleep_debt", +20, ("熬夜", "通宵", "凌晨", "失眠", "没睡好", "加班到")),
    ("sleep_debt", +10, ("加班", "赶工", "熬夜刷", "打游戏到很晚")),
    ("sleep_debt", -25, ("睡觉", "午休", "补觉", "早睡", "休息", "睡了个好觉")),
    # —— 压力累积 / 释放 ——
    ("stress", +15, ("压力", "焦虑", "被骂", "挨批", "事故", "deadline", "截止",
                     "开会", "考试", "赶进度")),
    ("stress", +8, ("加班", "通勤", "堵车", "排队", "吵架")),
    ("stress", -15, ("放松", "散步", "冥想", "按摩", "听歌", "撸猫", "散步")),
    ("stress", -10, ("运动", "跑步", "健身", "游泳", "打球")),
    # —— 精力消耗 / 恢复 ——
    ("energy", -15, ("熬夜", "通宵", "失眠")),
    ("energy", -10, ("加班", "高强度", "累", "疲惫")),
    ("energy", +15, ("睡觉", "午休", "补觉", "早睡")),
    ("energy", +10, ("运动", "跑步", "健身", "游泳", "散步")),
]


# ----------------------------------------------------------------------------
# 状态容器
# ----------------------------------------------------------------------------
@dataclass
class SimState:
    """隐藏世界状态（Energy / Stress / SleepDebt），全部 clamp 到 [0,100]。"""

    energy: int = DEFAULT_ENERGY
    stress: int = DEFAULT_STRESS
    sleep_debt: int = DEFAULT_SLEEP_DEBT

    def clamp(self) -> "SimState":
        """把全部状态夹到合法范围，返回自身（链式用）。"""
        lo_e, hi_e = STATE_LIMITS["energy"]
        lo_s, hi_s = STATE_LIMITS["stress"]
        lo_d, hi_d = STATE_LIMITS["sleep_debt"]
        self.energy = max(lo_e, min(hi_e, self.energy))
        self.stress = max(lo_s, min(hi_s, self.stress))
        self.sleep_debt = max(lo_d, min(hi_d, self.sleep_debt))
        return self

    def apply_delta(self, delta: dict[str, int]) -> "SimState":
        """叠加一组状态增量（dict），自动 clamp。"""
        self.energy += int(delta.get("energy", 0))
        self.stress += int(delta.get("stress", 0))
        self.sleep_debt += int(delta.get("sleep_debt", 0))
        return self.clamp()

    def to_dict(self) -> dict[str, int]:
        return {"energy": self.energy, "stress": self.stress,
                "sleep_debt": self.sleep_debt}

    @classmethod
    def from_dict(cls, data: dict | None) -> "SimState":
        """从 dict 恢复（跨天持久化用）；缺字段用默认值。"""
        data = data or {}
        return cls(
            energy=int(data.get("energy", DEFAULT_ENERGY)),
            stress=int(data.get("stress", DEFAULT_STRESS)),
            sleep_debt=int(data.get("sleep_debt", DEFAULT_SLEEP_DEBT)),
        ).clamp()

    @classmethod
    def fresh_day(cls) -> "SimState":
        """新的一天：轻微回满精力、清一部分睡眠债（睡了一觉）。"""
        return cls(
            energy=DEFAULT_ENERGY,
            stress=max(0, DEFAULT_STRESS - 5),
            sleep_debt=max(0, DEFAULT_SLEEP_DEBT - 20),
        ).clamp()


# ----------------------------------------------------------------------------
# 事件 → 状态增量 推导
# ----------------------------------------------------------------------------
def _match_any(text: str, keywords: tuple[str, ...]) -> bool:
    """文本是否命中关键词列表中的任意一个。"""
    return any(kw in text for kw in keywords)


def derive_state_changes(
    name: str,
    tags: list[str] | None = None,
    description: str = "",
    *,
    drivers: list[tuple[str, int, tuple[str, ...]]] | None = None,
) -> dict[str, int]:
    """从单个事件推导状态增量（纯本地，不调 LLM）。

    参数：
        name: 事件名（如「熬夜加班」）
        tags: 事件标签（如 ["加班", "疲惫"]）
        description: 事件描述（补充匹配，可为空）
        drivers: 推导关键词表（默认 DEFAULT_DERIVERS，测试可注入）
    返回：
        {"energy": -10, "stress": +8, "sleep_debt": +20} 这类增量 dict
    """
    drivers = drivers if drivers is not None else DEFAULT_DERIVERS
    haystack = " ".join(filter(None, [name, *(tags or []), description]))

    result: dict[str, int] = {}
    for state, delta, keywords in drivers:
        if _match_any(haystack, keywords):
            result[state] = result.get(state, 0) + delta
    return result
