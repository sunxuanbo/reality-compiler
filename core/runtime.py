# -*- coding: utf-8 -*-
"""运行时层：拿着编译结果「跑一遍」，输出终端日志 + 属性结算 + buff / debuff 标签。

真实编译器跑完会打印执行日志，这里我们把这一步模拟成：
    命中事件列表 matched  ->  simulate_runtime()  ->  RuntimeLog
UI 层把 RuntimeLog 里的终端行、属性面板、标签墙渲染出来即可。

多世界观升级后：
    - 固定属性（hp / mp / level）数值逻辑与上限保持不变；
    - 原本写死的「钱包」改为「可变属性」，由当前世界（WorldProfile.variable_stat）决定：
      事件的 gold 字段会映射到该可变属性（剑与魔法 -> 钱包；后室 -> San 值）；
    - 后室等世界可在可变属性触底 / 偏低时追加特殊 debuff（如认知崩溃 / 认知污染）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lexicon import MatchedEvent
from .world_config import FALLBACK_WORLD, WorldProfile


# ----------------------------------------------------------------------------
# 角色初始属性（魔法数字集中放顶部，方便调平衡）
# ----------------------------------------------------------------------------
HP_MAX = 100                    # 生命值上限
MP_MAX = 100                    # 精力上限
EXP_START = 0                   # 初始经验

# v2.6 等级系统（bug2 + bug3 双保险，防等级被刷爆）：
#   - MAX_EXP_PER_EVENT：单次事件 EXP 硬截断上限（第二层防御，schema_validator 是第一层）
#   - MAX_LEVEL：等级硬上限，到达后不再升级
MAX_EXP_PER_EVENT = 15          # 单个事件最多 +15 经验（即使 AI 被注入返回超大值也被压住）
MAX_LEVEL = 99                  # 等级硬上限（指数曲线之上再加一层保险）


# ----------------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------------
@dataclass
class RuntimeState:
    """一次模拟结束后的角色面板。"""

    hp: int
    mp: int
    vstat: int                   # 可变属性当前值（钱包 / San值 等，由世界决定）
    exp: int
    level: int


@dataclass
class CalcStep:
    """单条命中事件对属性的「逐步计算过程」，供 UI 透明展示。

    记录事件生效前后的每个属性值与增量、以及是否触发了上限/下限夹紧，
    让用户能看清 HP / MP / 可变属性 / EXP 究竟是怎么算出来的。
    """

    order: int
    icon: str
    name: str
    scale: float
    dhp: int
    dmp: int
    dv: int
    dexp: int
    hp_before: int
    hp_after: int
    mp_before: int
    mp_after: int
    v_before: int
    v_after: int
    exp_before: int
    exp_after: int
    clamp: str                                          # 夹紧说明，空串表示无夹紧


@dataclass
class RuntimeLog:
    """一次模拟的完整产物。"""

    lines: list[str] = field(default_factory=list)           # 终端逐行日志
    state: RuntimeState | None = None                       # 结算后的属性面板
    chips: list[tuple[str, str]] = field(default_factory=list)  # (标签名, "buff"/"debuff")
    steps: list[CalcStep] = field(default_factory=list)     # 逐步计算过程（透明化结算）


def _level_from(exp: int) -> int:
    """经验到等级的映射：指数曲线 + 硬上限（v2.6，bug3）。

    升级所需经验随等级平方增长：升到下一级所需经验 = (当前等级²) × 50
        Lv.1→Lv.2 需要 1²×50 = 50
        Lv.2→Lv.3 需要 2²×50 = 200
        Lv.3→Lv.4 需要 3²×50 = 450
        ...
    效果：前期升级速度和旧线性公式一致（50/级起步），后期越来越难，
    即使 EXP 被刷到 99 万，等级也只会到 Lv.32 左右，而不是旧公式的 Lv.20000。
    再加上 MAX_LEVEL = 99 硬上限，彻底杜绝等级无限增长。
    """
    level = 1
    remaining = max(0, exp)          # 负数经验按 0 处理（不降级）
    while level < MAX_LEVEL:
        needed = (level ** 2) * 50   # 升到下一级所需经验
        if remaining < needed:
            break
        remaining -= needed
        level += 1
    return min(level, MAX_LEVEL)


def simulate_runtime(
    matched: list[MatchedEvent],
    world: WorldProfile | None = None,
    *,
    initial_vstat: int | None = None,
    warn_threshold: int | None = None,
) -> RuntimeLog:
    """拿着命中事件跑一遍模拟，产出终端日志 + 属性结算 + 标签墙。

    参数:
        matched: compiler.compile_reality() 返回的 matched 列表
        world:   当前世界观（WorldProfile）。None 退化为旧版行为（可变属性视为钱包，初始 0）。
        initial_vstat: 可选，可变属性初始值（如用户填写的「初始存款」）；
                       None 时用世界默认值（钱包 100 / San 100）。
        warn_threshold: 可选，可变属性结算后低于该值追加「⚠️ 存款不足」警告标签。
    返回:
        RuntimeLog
    """
    world = world or FALLBACK_WORLD
    vs = world.variable_stat

    hp = HP_MAX
    mp = MP_MAX
    # 可变属性初始值：优先用调用方传入的（如真实存款），否则用世界设定默认
    vstat = int(initial_vstat) if initial_vstat is not None else vs.initial
    exp = EXP_START

    lines: list[str] = []
    emit = lines.append          # 一个小别名，让下面的日志代码读起来像真的在写终端

    emit("[boot] Reality Compiler runtime starting ...")
    emit(f"[scan] matched {len(matched)} event(s) · scale x{matched[0].scale:.2f}" if matched
         else "[scan] no event matched")
    emit(f"[world] {world.label} · 可变属性 {vs.icon} {vs.name}")

    chips: list[tuple[str, str]] = []
    steps: list[CalcStep] = []
    order = 0
    for m in matched:
        ev = m.event
        dhp = round(ev.hp * m.scale)
        dmp = round(ev.mp * m.scale)
        dv = round(ev.gold * m.scale)       # gold 映射为「可变属性」的增量
        dexp = round(ev.exp * m.scale)
        # v2.6 EXP 硬截断（bug2 第二层防御）：单次事件经验夹在 [0, MAX_EXP_PER_EVENT]。
        # schema_validator 是第一层（AI 返回 999999 → 15），这里再兜一层，
        # 即使绕过校验层直接构造事件，EXP 也不可能被刷爆。
        dexp = max(0, min(dexp, MAX_EXP_PER_EVENT))

        # 记录生效前的属性（用于展示「计算过程」）
        hp_b, mp_b, v_b, exp_b = hp, mp, vstat, exp

        # 结算，HP / MP 夹在 [0, 上限] 之间，掉到 0 就不会再负
        hp = max(0, min(HP_MAX, hp + dhp))
        mp = max(0, min(MP_MAX, mp + dmp))
        # 可变属性：下限一定夹住；上限为 None 表示不封顶（如钱包可负可无限）
        vstat += dv
        vstat = max(vs.min_val, vstat)
        if vs.max_val is not None:
            vstat = min(vs.max_val, vstat)
        exp += dexp

        # 逐步计算过程的透明化：找出哪些属性被上限/下限夹紧了
        clamp_parts: list[str] = []
        if hp_b + dhp != hp:
            clamp_parts.append("HP")
        if mp_b + dmp != mp:
            clamp_parts.append("MP")
        if v_b + dv != vstat:
            clamp_parts.append(vs.name)
        clamp_note = (" · 夹紧：" + "/".join(clamp_parts)) if clamp_parts else ""

        order += 1
        steps.append(CalcStep(
            order=order,
            icon=ev.icon,
            name=ev.name,
            scale=m.scale,
            dhp=dhp, dmp=dmp, dv=dv, dexp=dexp,
            hp_before=hp_b, hp_after=hp,
            mp_before=mp_b, mp_after=mp,
            v_before=v_b, v_after=vstat,
            exp_before=exp_b, exp_after=exp,
            clamp=clamp_note,
        ))

        emit(
            f"  {ev.icon} {ev.name:<10} hp={dhp:+d} mp={dmp:+d} "
            f"{vs.name}={dv:+d} exp={dexp:+d}"
        )
        # 负向标签（debuff）：只要生命/精力被消耗，或消耗了可变属性，就归为消耗。
        # 注意不能用 (hp+mp+dv)<0 判定——像「加班」会发工资(+gold)，
        # 若用加总，金钱收益会掩盖掉血掉蓝，把明显的消耗事件错标成 buff。
        # 事件名带 🚨（AI 识别的不健康行为）时，标签升级为红色警报样式
        base_kind = "debuff" if (dhp < 0 or dmp < 0 or dv < 0) else "buff"
        kind = "debuff red" if "🚨" in ev.name else base_kind
        chips.append((ev.name, kind))

    level = _level_from(exp)
    emit("[ok] simulation complete")
    emit(
        f"[stat] HP {hp}/{HP_MAX} · MP {mp}/{MP_MAX} · "
        f"{vs.name} {vstat} · EXP {exp} (Lv.{level})"
    )

    # --- 可变属性触发的特殊 debuff（如后室 San 值偏低 / 归零）---
    if world.low_debuff and world.low_threshold is not None and vstat < world.low_threshold:
        chips.append((world.low_debuff, "debuff"))
    if world.zero_debuff and vstat <= vs.min_val:
        chips.append((world.zero_debuff, "debuff"))
    # --- 存款不足预警：调用方设置了预警线且结算后存款低于预警线 ---
    if warn_threshold is not None and vstat < warn_threshold:
        chips.append(("⚠️ 存款不足", "debuff red"))

    # 标签去重，保持首次出现顺序（更接近人脑对「今天发生了啥」的归类）
    seen: set[str] = set()
    uniq_chips: list[tuple[str, str]] = []
    for name, kind in chips:
        if name not in seen:
            seen.add(name)
            uniq_chips.append((name, kind))

    return RuntimeLog(
        lines=lines,
        state=RuntimeState(hp=hp, mp=mp, vstat=vstat, exp=exp, level=level),
        chips=uniq_chips,
        steps=steps,
    )


def events_to_plain(matched: list[MatchedEvent]) -> list[dict]:
    """把命中事件转成可序列化的日志 dict（数值为结算口径，已乘强度倍率）。

    供 core/logger.py 写入 JSONL 日志与统计使用；只读、无副作用。
    每个事件包含：name / description / hp / mp / gold / exp / tags。
    """
    out: list[dict] = []
    for m in matched:
        scale = m.scale if m.scale is not None else 1.0
        ev = m.event
        out.append({
            "name": ev.name,
            "description": ev.description,
            "hp": round(ev.hp * scale),
            "mp": round(ev.mp * scale),
            "gold": round(ev.gold * scale),
            "exp": round(ev.exp * scale),
            "tags": list(ev.keywords),
        })
    return out
