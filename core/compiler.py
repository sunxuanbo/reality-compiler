# -*- coding: utf-8 -*-
"""编译器层：把「一段现实日常」编译成「Python 伪代码」+ 编译告警。

对外主要暴露：
    compile_reality(text, world_id)  -> CompileResult  （给 UI 用，信息最全）

数据来源：
    统一调用 DeepSeek API（core.llm_client.call_llm_for_events）由大模型实时生成
    结构化事件；不再使用本地词库匹配（已废弃）。若 API 不可用（缺 Key / 网络异常 /
    限流等），异常向上抛出，由 UI 层捕获并友好提示，同时保留旧属性面板不丢失。
伪代码渲染逻辑（_render_code）与属性结算（core.runtime）保持不变。
"""

from __future__ import annotations

import hashlib                      # 用输入文本算哈希，生成稳定的流水号
import random                       # 生成看起来随机、但可复现的编译细节（耗时等）
import datetime                      # 取当前日期，传给 AI 编译器
from dataclasses import dataclass, field

from .lexicon import (
    MatchedEvent,
    Event,
)
from .world_config import FALLBACK_WORLD, WorldProfile
from .llm_client import call_llm_for_events_full  # DeepSeek API 封装层（核心数据来源）
from .emotion import EmotionState, resolve_emotion


# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
RUNTIME_VERSION = "life 3.0"        # 假装的运行时版本号，标题栏里会打印（v3.0 全量迭代）
TARGET_PYTHON = "py3.12"            # 假装的目标解释器版本


# 编译告警编号 -> 给用户看的中文说明
WARNING_TEXT: dict[str, str] = {
    "W000": "未识别到明确事件，结算结果仅供参考。",
    "W001": "检测到高强度消耗事件，注意身体电量。",
    "W002": "检测到负面情绪事件，建议找个方式疏解。",
    "W003": "检测到健康异常，必要时请就医。",
    "W014": "检测到突发事故，专注力正被严重拉扯。",
    "W004": "咖啡因只是透支，别把 buff 当血瓶。",
}


# ----------------------------------------------------------------------------
# 编译结果的数据结构
# ----------------------------------------------------------------------------
@dataclass
class CompileResult:
    """一次编译的完整产物，UI 层拿着它就能渲染代码框 / 终端 / 属性面板。"""

    source: str                                     # 用户原始输入
    build_id: str                                   # 流水号，如 "a3f19c"，同一句话永远一样
    code: str                                       # 生成的 Python 伪代码字符串
    warnings: list[str] = field(default_factory=list)   # 编译告警（中文）
    matched: list[MatchedEvent] = field(default_factory=list)  # 命中的事件，给运行时用
    elapsed_ms: int = 0                             # 假装的编译耗时（毫秒）
    scale: float = 1.0                              # 本次的强度倍率
    summary: str = ""                               # AI 生成的每日复盘（2-3 句）
    advice: str = ""                                # AI 生成的改进建议（1-2 句）
    emotion: EmotionState = field(default_factory=EmotionState)  # 情绪氛围（AI + 本地兜底）


# ----------------------------------------------------------------------------
# 内部工具函数
# ----------------------------------------------------------------------------
def _build_id(text: str) -> str:
    """根据输入文本生成 6 位流水号。

    用 sha1 而不是 Python 内置 hash()，是因为内置 hash 每次进程重启结果都不同，
    而我们希望「同样的输入 -> 同样的流水号」，这样看起来才像真编译器。
    """
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()  # 计算十六进制摘要
    return digest[:6]                                                # 取前 6 位即可


def _seed_from(text: str) -> int:
    """把文本转成一个整数随机种子，保证同输入同输出（可复现）。"""
    return int(hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:8], 16)


def _render_code(matched: list[MatchedEvent], build_id: str, scale: float,
                 vname: str = "钱包") -> str:
    """把命中事件渲染成一段「看起来像真的」的 Python 伪代码。

    重点：它只是长得像代码，绝对不包含任何可执行的危险逻辑。
    """
    lines: list[str] = []
    lines.append(f"#!/usr/bin/env {TARGET_PYTHON}")
    lines.append(f"# Reality Compiler {RUNTIME_VERSION} · build {build_id}")
    lines.append("import life")
    lines.append("")
    lines.append("player = life.Player()  # 你本人")
    lines.append("")

    total_hp = total_mp = total_gold = total_exp = 0
    for m in matched:
        ev = m.event
        dhp = round(ev.hp * scale)
        dmp = round(ev.mp * scale)
        dgold = round(ev.gold * scale)
        dexp = round(ev.exp * scale)
        total_hp += dhp
        total_mp += dmp
        total_gold += dgold
        total_exp += dexp
        # 事件名直接拼进 Python 单引号字符串字面量，必须转义以下字符，否则会破坏语法：
        #   \ 反斜杠、' 单引号（必转），以及 \r \n \t 等控制字符。
        # 事件名本不该含控制字符，但加词库时极易踩坑，提前兜底，
        # 保证生成的伪代码永远是合法 Python（否则 st.code 会渲染出坏代码）。
        safe_name = (
            ev.name.replace("\\", "\\\\")
                   .replace("\r", "\\r")
                   .replace("\n", "\\n")
                   .replace("\t", "\\t")
                   .replace("'", "\\'")
        )
        lines.append(
            f"player.log_event('{safe_name}', hp={dhp:+d}, mp={dmp:+d}, "
            f"{vname}={dgold:+d}, exp={dexp:+d})  # {ev.key}"
        )

    lines.append("")
    lines.append("# 一次性结算")
    lines.append(
        f"player.apply()  # HP {total_hp:+d} · MP {total_mp:+d} · "
        f"{vname} {total_gold:+d} · EXP {total_exp:+d}"
    )
    lines.append("print(player.summary())")
    return "\n".join(lines)


def _make_warnings(matched: list[MatchedEvent]) -> list[str]:
    """根据命中事件的 warning 字段，去重后生成中文告警列表。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in matched:
        w = m.event.warning
        if w and w not in seen:
            seen.add(w)
            if w in WARNING_TEXT:
                out.append(f"[{w}] {WARNING_TEXT[w]}")
    return out


def _to_int(value, default: int = 0) -> int:
    """把各种形态的数值（int/float/数字字符串）安全转成 int，供 LLM 返回数据使用。"""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _as_str_tuple(value) -> tuple[str, ...]:
    """把 LLM 返回的 tags 归一化为字符串元组。

    兼容三种形态：字符串（整串作为一个标签，避免被按字符拆开）、
    列表 / 元组（逐项转字符串）、None / 其他（空元组）。
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(t) for t in value)
    return ()


def _convert_llm_events(raw_events: list[dict], world_id: str) -> list[MatchedEvent]:
    """把 DeepSeek 返回的事件字典列表，转换为引擎层使用的 MatchedEvent 列表。

    字段映射：gold_or_san -> gold（渲染层再根据世界观决定显示「钱包」或「San 值」）。
    AI 事件强度倍率固定为 1.0，因为模型已经直接给出了最终数值，避免二次缩放。
    """
    out: list[MatchedEvent] = []
    for i, ev in enumerate(raw_events):
        tags = _as_str_tuple(ev.get("tags"))
        event = Event(
            key=f"ai_{i}_{ev.get('name', 'event')}",
            name=str(ev.get("name", "未知事件")),
            icon="✨",  # AI 生成事件统一图标
            keywords=tags,
            hp=_to_int(ev.get("hp", 0)),
            mp=_to_int(ev.get("mp", 0)),
            gold=_to_int(ev.get("gold_or_san", 0)),  # gold_or_san -> gold 映射
            exp=_to_int(ev.get("exp", 0)),
            warning="",
            world_tags=(world_id,),
            description=str(ev.get("description") or "").strip(),  # 保留 AI 描述（供日志/PDF）
        )
        out.append(
            MatchedEvent(
                event=event,
                hit_words=list(tags),
                scale=1.0,
            )
        )
    return out


# ----------------------------------------------------------------------------
# 对外入口
# ----------------------------------------------------------------------------
def build_compile_result(
    source: str,
    world: WorldProfile,
    ai_data: dict,
) -> CompileResult:
    """把 AI 返回数据（events/summary/advice）组装成 CompileResult（v3.0 Agent 化）。

    供两个入口共用：
        - compile_reality（旧入口：先调 LLM 再组装）
        - core.agent.RealityAgent（新入口：Planner → LLM → Validator → 组装 → Reflection）
    这样 Agent 化不会破坏现有渲染/运行时逻辑，只是把「组装」抽成可复用函数。

    参数：
        source: 清洗后的用户输入
        world:  当前世界观对象
        ai_data: call_llm_for_events_full 的返回（已过 schema 安全门）
    返回：
        CompileResult
    """
    raw_events = ai_data["events"]
    matched = _convert_llm_events(raw_events, world.world_id)
    warnings = ["[AI] 本次由 AI 编译器生成，数值为模型估计值。"] + _make_warnings(matched)
    build_id = _build_id(source)                 # 生成流水号
    scale = matched[0].scale if matched else 1.0  # 强度倍率对整句统一，取第一个即可

    # 编译耗时：用与旧 compile_reality 相同的 RNG 逻辑（seed 由文本决定，可复现）
    rng = random.Random(_seed_from(source))

    return CompileResult(
        source=source,
        build_id=build_id,
        code=_render_code(matched, build_id, scale, world.variable_stat.name),
        warnings=warnings,
        matched=matched,
        # 编译耗时：按事件数量估算 + 一点随机抖动，看起来更真实
        elapsed_ms=rng.randint(120, 320) + len(matched) * 24,
        scale=scale,
        summary=str(ai_data.get("summary") or ""),   # AI 每日复盘
        advice=str(ai_data.get("advice") or ""),     # AI 改进建议
        emotion=resolve_emotion(ai_data, source, matched),
    )


def compile_reality(
    text: str,
    world: WorldProfile | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> CompileResult:
    """完整编译：返回伪代码 + 告警 + 命中事件（运行时消费这一份）。

    数据来源：DeepSeek API（call_llm_for_events_full）—— 由大模型实时生成结构化事件。
    世界观由 AI 动态生成（WorldProfile 对象），其名称 / 背景 / 货币名注入提示词。
    若 API 调用失败，异常会向上抛出，由 UI 层捕获并友好提示，同时保留旧属性面板不丢失。

    world 为当前世界观对象（AI 生成）；None 时退化为内置兜底世界。
    api_key / base_url / model 可由「页面设置面板」传入；为空时回退读环境变量。
    """
    cleaned = text.strip()                       # 去掉首尾空白
    if not cleaned:                              # 空输入直接抛错，由 UI 层捕获并提示
        raise ValueError("输入为空，无法编译")

    world = world or FALLBACK_WORLD
    today = datetime.date.today().isoformat()    # 当前日期，传给 AI 编译器

    # 调用 AI 编译器：任何失败都向上抛出（不再本地降级），由 UI 层兜底展示
    ai_data = call_llm_for_events_full(
        world, cleaned, today,
        api_key=api_key, base_url=base_url, model=model,
    )
    return build_compile_result(cleaned, world, ai_data)
