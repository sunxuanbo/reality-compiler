# -*- coding: utf-8 -*-
"""世界观配置层：定义「多世界观生活编译器」的属性结构与 AI 世界观转换。

v2.2 起世界观由 AI 动态生成，不再有硬编码的「剑与魔法 / 后室」注册表：

    - 数据结构（VariableStat / WorldProfile）保持不变，UI / 引擎层照常消费。
    - 新增 `world_from_ai(data, world_id)`：把 DeepSeek 返回的世界观 JSON
      转成 WorldProfile（货币名 -> variable_stat.name，随世界观变化）。
    - 仅保留一个 `FALLBACK_WORLD`（AI 不可用时的兜底世界），不再是主数据源。
    - HP / MP / 等级为固定属性；「钱包」改为随世界观动态显示的可变属性
      （显示名 = AI 生成的 currency_name，如金币 / 杏仁水 / 比特币）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ----------------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class VariableStat:
    """可变属性的描述（每个世界一个）。

    gold 字段在结算时会映射到这里定义的属性上。
    """

    name: str                       # 显示名，如 "钱包" / "San值" / "金币"（随世界观变化）
    icon: str                       # 图标（emoji），如 "💰" / "🌀"
    initial: int                    # 初始值（AI 世界下通常为 0，真实值来自用户存款）
    min_val: int = 0                # 下限，低于此值会夹住（例如 San 归零）
    max_val: int | None = None      # 上限，None 表示不封顶（如钱包可负可无限）


@dataclass(frozen=True)
class WorldProfile:
    """一个世界观的完整设定（可由 AI 动态生成）。"""

    world_id: str                           # 唯一标识，如 "day-2026-08-03"
    label: str                              # 世界观名称（中文 2-6 字，AI 生成）
    desc: str                               # 一句话世界观简介（AI 生成）
    variable_stat: VariableStat             # 该世界的可变属性（名称 = AI 货币名）

    # --- 可变属性触发的特殊 debuff（AI 世界默认不启用，保留机制供未来扩展）---
    low_threshold: int | None = None        # 可变属性低于此值时，追加 low_debuff
    low_debuff: str | None = None           # 偏低时追加的 debuff 标签，如 "🧠 认知污染"
    zero_debuff: str | None = None          # 可变属性触底（== min_val）时的特殊 debuff 标签

    # --- 标签墙配色：事件名 -> 额外 CSS class（AI 世界默认无，保留机制）---
    chip_colors: dict[str, str] = field(default_factory=dict)


# ----------------------------------------------------------------------------
# 兜底世界：仅当 AI 世界观生成失败（缺 Key / 网络异常）时使用，保证页面不白屏。
# 它不是一个「预设世界」，只是无数据时的占位，主数据源永远是 AI 生成。
# ----------------------------------------------------------------------------
FALLBACK_WORLD = WorldProfile(
    world_id="fallback",
    label="现实世界",
    desc="AI 世界观暂不可用，回到最朴素的世界。",
    variable_stat=VariableStat(name="钱包", icon="💰", initial=0, min_val=0, max_val=None),
)


def world_from_ai(data: dict, world_id: str) -> WorldProfile:
    """把 DeepSeek 返回的世界观 JSON 转成 WorldProfile。

    参数:
        data: AI 返回的 dict，含 world_name / world_description / currency_name
              / stat_mapping / daily_story 等字段。
        world_id: 该世界观的稳定 id（建议用日期，如 "day-2026-08-03"）。
    返回:
        WorldProfile：label=世界观名，desc=背景简介，可变属性名=货币名（如金币/杏仁水）。
    说明:
        字段缺失时全部有兜底值；可变属性初始值固定为 0，真实余额由用户「初始存款」决定。
    """
    data = data if isinstance(data, dict) else {}
    name = str(data.get("world_name") or "").strip()[:40] or "未知世界"
    desc = str(data.get("world_description") or "").strip()[:300]
    currency = str(data.get("currency_name") or "").strip()[:40] or "钱包"

    return WorldProfile(
        world_id=world_id,
        label=name,
        desc=desc,
        variable_stat=VariableStat(
            name=currency,
            icon="💰",
            initial=0,            # AI 世界下初始余额由用户存款决定（见 runtime.initial_vstat）
            min_val=0,
            max_val=None,
        ),
    )
