# -*- coding: utf-8 -*-
"""内容供应模块：世界观由 AI 动态生成 + 提供「今日冒险」素材。

v2.2 起不再有硬编码的「剑与魔法 / 后室」世界观列表，世界观由 DeepSeek API
按日期实时生成（名称 / 背景 / 货币名 / 今日冒险故事每天都不同）。

对外接口：
    today_world_id() -> str                     # 按日期得到稳定世界观 id（每天一个）
    fetch_world(*, api_key, base_url, model) -> dict   # 获取今日世界观 dict（AI 优先，失败兜底）
    fetch_daily_event(world_data, ...) -> str   # 取今日冒险故事（优先 AI 生成的世界观自带）
"""

from __future__ import annotations

import datetime

from core.llm_client import call_llm_for_world
from core.world_config import FALLBACK_WORLD


# ----------------------------------------------------------------------------
# 兜底世界观数据：仅当 AI 不可用（缺 Key / 网络异常）时使用，保证页面不白屏。
# 它不是预设的「异世界」，只是占位；主数据源永远是 AI 生成。
# ----------------------------------------------------------------------------
_FALLBACK_WORLD_DATA: dict = {
    "world_name": FALLBACK_WORLD.label,
    "world_description": FALLBACK_WORLD.desc,
    "currency_name": FALLBACK_WORLD.variable_stat.name,
    "stat_mapping": {
        "hp": "生命值",
        "mp": "精力值",
        "gold": FALLBACK_WORLD.variable_stat.name,
    },
    "daily_story": (
        "今天风平浪静，没有什么特别的事发生。上午处理了几件琐事，"
        "中午好好吃了顿饭，下午忙里偷闲休息了一会儿，晚上按时回家。"
    ),
}


def today_world_id() -> str:
    """返回「今天」应生效的世界观 id。

    直接用当前日期生成稳定 id（如 "day-2026-08-03"）：
      - 同一天内多次刷新页面 -> id 不变（配合 session_state 缓存世界观）；
      - 跨天 -> id 变化，触发世界观重新生成。
    """
    return f"day-{datetime.date.today().isoformat()}"


def fetch_world(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict:
    """获取今日世界观数据（dict）。

    优先由 AI 按当前日期实时生成一个全新世界观；任何失败（缺 Key / 网络 / 限流）
    都自动回退到内置兜底世界观，保证页面永远有世界观可用。

    参数:
        api_key / base_url / model: 模型设置（可由页面「⚙ 模型设置」传入）
    返回:
        含 world_name / world_description / currency_name / stat_mapping / daily_story 的 dict。
    """
    try:
        result = call_llm_for_world(
            datetime.date.today().isoformat(),
            api_key=api_key, base_url=base_url, model=model,
        )
        # 私有元数据只用于 UI 判断“真实 AI 结果 / 本地兜底”，不会进入提示词或日志。
        result = dict(result)
        result["_source"] = "ai"
        return result
    except Exception as exc:
        # AI 不可用时的兜底：用内置世界观，保证「每日世界观」与「生成今日冒险」永远有内容
        fallback = dict(_FALLBACK_WORLD_DATA)
        fallback["_source"] = "fallback"
        fallback["_error"] = str(exc) or "模型连接失败，请检查配置。"
        return fallback


def fetch_daily_event(
    world_data: dict,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    """获取当前世界观的「今日冒险」故事文本。

    优先取 AI 世界观自带字段 daily_story（200-300 字）；若为空则临时调 AI 生成；
    再失败则回退到兜底文本，保证按钮永远有输出。

    参数:
        world_data: 当前世界观 dict（fetch_world 的返回值）
        api_key / base_url / model: 模型设置
    返回:
        一段可直接喂给编译器的现实日常文本
    """
    story = str((world_data or {}).get("daily_story") or "").strip()
    if story:
        return story

    try:
        from core.llm_client import call_llm_for_daily
        from core.world_config import world_from_ai

        world = world_from_ai(world_data or {}, "fallback")
        return call_llm_for_daily(
            world, datetime.date.today().isoformat(),
            api_key=api_key, base_url=base_url, model=model,
        )
    except Exception:
        # AI 不可用时的兜底：用内置素材，保证「生成今日冒险」永远有输出
        return str(_FALLBACK_WORLD_DATA.get("daily_story") or "今天风平浪静，没什么特别的事。")
