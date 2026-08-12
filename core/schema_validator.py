# -*- coding: utf-8 -*-
"""Schema 安全门（v2.6，bug1 + bug2）：在 DeepSeek 返回数据和 Compiler 之间的「容错层」。

背景：
    用户输入 → DeepSeek API → 直接拿 JSON → 编译 → 显示。
    这个链路假设 LLM 永远返回正确 JSON——但实际 DeepSeek 可能返回：
        - 不完整的 JSON（缺 mp / gold / exp / tags 字段）
        - 带解释文字的 JSON（如「当然，我来帮你分析一下：{...}」）
        - 纯文字（完全不是 JSON）
        - 被 Prompt Injection 诱导出的超规数值（如 hp=100000、exp=999999）
    任何一次格式异常都可能导致页面崩溃，或被恶意利用刷爆数值。

职责（对应 bug1 的四步安全门）：
    1. JSON Extractor  从「解释文字 + JSON」混排中提取纯 JSON
    2. Pydantic Validator  严格数据模型 + 字段范围约束
    3. Repair Strategy  缺字段补 0、类型错误强转、超范围截断、tags 超量截断
    4. Fallback  不可修复（缺必填字段 / 非 JSON）时由调用方（llm_client）触发重试，
                 重试耗尽后降级到「本地默认事件」，页面永不崩溃。

另实现 bug2 的「数值统一硬上限」：
    hp   ∈ [-30, +20]      mp   ∈ [-30, +20]
    gold ∈ [-50, +30]      exp  ∈ [0, +15]      tags ≤ 5 个
    第一层防御（截断到范围）；runtime.py 是第二层防御（累加前再截断）。

兼容性说明：
    LLM 系统提示词要求返回字段 gold_or_san，而本模型按 bug1 定义 gold 字段；
    通过 field_validator 把 gold_or_san 合并进 gold，输出时同时带 gold 与 gold_or_san，
    保证 compiler（读 gold_or_san）与日志（读 gold）都兼容。
"""

from __future__ import annotations

import json
from typing import Any

# pydantic 缺失时降级：应用不崩，但跳过强校验（仍做基础提取与兜底）
try:  # pragma: no cover - 正常环境必有 pydantic
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
except ImportError:  # pragma: no cover
    BaseModel = object

    class Field:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):  # noqa: ANN001, ANN002
            pass

    ConfigDict = dict  # type: ignore[no-redef]
    ValidationError = Exception  # type: ignore[no-redef]

    def field_validator(*args, **kwargs):  # type: ignore[no-redef]  # noqa: ANN001, ANN002
        def deco(fn):
            return fn
        return deco


# ----------------------------------------------------------------------------
# 数值硬上限（bug2：统一防御边界，常量集中放顶部）
# ----------------------------------------------------------------------------
HP_MIN, HP_MAX = -30, 20       # hp 允许范围（扣血上限 -30 / 回血上限 +20）
MP_MIN, MP_MAX = -30, 20       # mp 允许范围
GOLD_MIN, GOLD_MAX = -50, 30   # gold/gold_or_san 允许范围
EXP_MIN, EXP_MAX = 0, 15       # exp 允许范围（单次事件最多 +15，防等级刷爆）
TAGS_MAX = 5                   # tags 最多 5 个，超出截断
EVENTS_MAX = 6                 # 单次最多 6 个事件，限制成本、日志体积与结算放大
NAME_MAX_LEN = 40
DESCRIPTION_MAX_LEN = 300
TAG_MAX_LEN = 40
SUMMARY_MAX_LEN = 1000
ADVICE_MAX_LEN = 500
MOOD_REASON_MAX_LEN = 120
VALID_MOODS = {"joyful", "calm", "sad", "anxious", "angry", "mixed"}


def _clamp(value: int, lo: int, hi: int) -> int:
    """把数值夹紧到 [lo, hi]。"""
    return max(lo, min(hi, value))


# ----------------------------------------------------------------------------
# 1. Pydantic 数据模型
# ----------------------------------------------------------------------------
class AIEvent(BaseModel):
    """单条事件：严格约束字段类型与取值范围。"""

    model_config = ConfigDict(extra="ignore")          # 忽略未知字段，不报错

    name: str = Field(..., description="事件名称")      # 必填：缺了走重试
    description: str = Field(default="", description="事件描述")  # 可选
    hp: int = Field(default=0, ge=HP_MIN, le=HP_MAX)     # 越界由 Repair 截断
    mp: int = Field(default=0, ge=MP_MIN, le=MP_MAX)
    gold: int = Field(default=0, ge=GOLD_MIN, le=GOLD_MAX)
    exp: int = Field(default=0, ge=EXP_MIN, le=EXP_MAX)
    tags: list[str] = Field(default_factory=list, max_length=TAGS_MAX)

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_to_list(cls, v: Any) -> Any:
        """把 tags 归一化成字符串列表。

        兼容三种形态（与 compiler._as_str_tuple 保持一致）：
            - 字符串「加班 疲惫」→ 整串作为一个标签，避免被按字符拆开
            - 列表 / 元组 → 逐项转字符串
            - None / 其他 → 空列表
        """
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, (list, tuple)):
            return [str(t) for t in v]
        return []


class AIResponse(BaseModel):
    """AI 的完整返回：世界观回显 + 复盘 + 事件列表。"""

    model_config = ConfigDict(extra="ignore")

    world_display_name: str = Field(default="", description="世界观显示名称")
    summary: str = Field(default="", description="今日总结")
    advice: str = Field(default="", description="改进建议")
    mood: str = Field(default="", description="六类情绪枚举")
    mood_intensity: int = Field(default=0, ge=0, le=100)
    mood_confidence: int = Field(default=0, ge=0, le=100)
    mood_reason: str = Field(default="", description="情绪判断依据")
    events: list[AIEvent] = Field(default_factory=list)


# ----------------------------------------------------------------------------
# 2. JSON 提取器
# ----------------------------------------------------------------------------
def extract_json(content: str) -> dict | None:
    """从 AI 返回文本中提取 JSON 对象；提取失败返回 None。

    依次尝试：
        1. 整体就是纯 JSON（json.loads 直接成功）
        2. 「解释文字 + JSON」混排：逐个尝试 JSON 对象起点
    """
    if not content or not content.strip():
        return None
    content = content.strip()

    # 尝试 1：整体直接是 JSON
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass

    # 尝试 2：从每个左大括号开始做增量解码。相比贪婪正则，这能正确处理
    # JSON 字符串里的大括号，也允许对象后面带少量解释文字。
    decoder = json.JSONDecoder()
    for index, char in enumerate(content):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(content[index:])
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# ----------------------------------------------------------------------------
# 3. 校验 + 修复 + 兜底
# ----------------------------------------------------------------------------
def _coerce_int(value: Any, default: int = 0) -> int:
    """尝试把任意形态（int / float / 数字字符串 / bool）强转成 int；失败用默认值。"""
    if isinstance(value, bool):            # bool 是 int 子类，先挡掉（True→1 会让修复无意义）
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _repair_event(raw: dict, notes: list[str]) -> dict | None:
    """修复单条事件；缺必填字段（name 为空）返回 None（触发重试）。

    修复规则（bug1）：
        - 缺可选字段（hp/mp/gold/exp/tags/description）→ 补默认值
        - 类型错误 → 强转 int；强转失败 → 0
        - 超范围 → 截断到允许范围
        - tags 超 5 个 → 只保留前 5 个
    所有修复动作记录到 notes（供调用方记日志，bug1 第 4 点）。
    """
    if not isinstance(raw, dict):
        notes.append("事件不是对象，已丢弃")
        return None

    name = raw.get("name")
    if name is None or not str(name).strip():
        notes.append("缺少必填字段 name，触发重试")
        return None

    hp = _coerce_int(raw.get("hp"))
    mp = _coerce_int(raw.get("mp"))
    gold_raw = raw.get("gold_or_san", raw.get("gold"))     # 兼容两种字段名
    gold = _coerce_int(gold_raw)
    exp = _coerce_int(raw.get("exp"))
    tags_raw = raw.get("tags", [])
    if isinstance(tags_raw, str):
        tags = [tags_raw]
    elif isinstance(tags_raw, (list, tuple)):
        tags = list(tags_raw)
    else:
        tags = []
    if isinstance(tags, str):  # 防御性分支；正常归一化后不会进入
        tags = [tags]
    tags = [str(t).strip()[:TAG_MAX_LEN] for t in tags]
    tags = [t for t in tags if t]

    # 类型修复记录
    for fname, val, default in (("hp", raw.get("hp"), 0),
                                ("mp", raw.get("mp"), 0),
                                ("gold", gold_raw, 0),
                                ("exp", raw.get("exp"), 0)):
        if val is None:
            notes.append(f"{fname} 缺失，补 0")
        elif not isinstance(val, (int, float)) and not (
                isinstance(val, str) and val.lstrip("-").isdigit()):
            notes.append(f"{fname} 类型异常（{type(val).__name__}），已强转")
    if not isinstance(tags_raw, list):
        notes.append("tags 非列表，已归一化")

    # 数值硬截断（bug2 第一层防御）：先记原始值，夹紧后逐字段记录越界
    for fname, raw_val, lo, hi in (
            ("hp", hp, HP_MIN, HP_MAX),
            ("mp", mp, MP_MIN, MP_MAX),
            ("gold", gold, GOLD_MIN, GOLD_MAX),
            ("exp", exp, EXP_MIN, EXP_MAX)):
        clamped = _clamp(raw_val, lo, hi)
        if clamped != raw_val:
            notes.append(f"{fname} {raw_val} 超出 [{lo},{hi}]，截断为 {clamped}")
    hp = _clamp(hp, HP_MIN, HP_MAX)
    mp = _clamp(mp, MP_MIN, MP_MAX)
    gold = _clamp(gold, GOLD_MIN, GOLD_MAX)
    exp = _clamp(exp, EXP_MIN, EXP_MAX)
    if len(tags) > TAGS_MAX:
        notes.append(f"tags 共 {len(tags)} 个，截断为前 {TAGS_MAX} 个")
        tags = tags[:TAGS_MAX]

    clean_name = str(name).strip()
    clean_desc = str(raw.get("description") or "").strip()
    if len(clean_name) > NAME_MAX_LEN:
        notes.append(f"事件名超过 {NAME_MAX_LEN} 字，已截断")
        clean_name = clean_name[:NAME_MAX_LEN]
    if len(clean_desc) > DESCRIPTION_MAX_LEN:
        notes.append(f"事件描述超过 {DESCRIPTION_MAX_LEN} 字，已截断")
        clean_desc = clean_desc[:DESCRIPTION_MAX_LEN]

    return {
        "name": clean_name or "未知事件",
        "description": clean_desc,
        "hp": hp,
        "mp": mp,
        "gold": gold,
        "gold_or_san": gold,       # 兼容 compiler._convert_llm_events（读 gold_or_san）
        "exp": exp,
        "tags": tags,
    }


def validate_and_repair(content: str) -> tuple[dict | None, list[str]]:
    """入口：提取 + 校验 + 修复。

    返回 (result, notes)：
        result 非 None -> 可直接交给 compiler 使用的完整响应 dict
        result 为 None -> 不可修复（非 JSON / 缺必填字段），调用方应重试，重试耗尽走兜底
    notes：本次所有修复动作的描述（供调用方写日志，bug1 第 4 点）。
    """
    notes: list[str] = []

    parsed = extract_json(content)
    if parsed is None:
        notes.append("无法提取 JSON（纯文字或 JSON 解析失败），触发重试")
        return None, notes

    # 字段归位：AI 可能返回 world_display_name / world_name 两种写法
    if "world_display_name" not in parsed and "world_name" in parsed:
        parsed["world_display_name"] = parsed["world_name"]

    events_raw = parsed.get("events", [])
    if not isinstance(events_raw, list):
        notes.append("events 不是列表，按空列表处理")
        events_raw = []
    if len(events_raw) > EVENTS_MAX:
        notes.append(
            f"events 共 {len(events_raw)} 条，超出建议上限 {EVENTS_MAX} 条，"
            f"已截断为前 {EVENTS_MAX} 条"
        )
        events_raw = events_raw[:EVENTS_MAX]

    events: list[dict] = []
    for i, ev in enumerate(events_raw):
        repaired = _repair_event(ev, notes)
        if repaired is None:
            # 有一条事件缺 name：整体视为不可修复，触发重试
            return None, notes
        events.append(repaired)

    # 若没有事件，填一条兜底「平凡的一天」（bug1 兜底，页面不空屏）
    if not events:
        notes.append("AI 未返回事件，使用默认事件")
        events = [default_event()]

    summary = str(parsed.get("summary", "") or "")
    advice = str(parsed.get("advice", "") or "")
    mood = str(parsed.get("mood", "") or "").strip().lower()
    mood_intensity = _clamp(_coerce_int(parsed.get("mood_intensity")), 0, 100)
    mood_confidence = _clamp(_coerce_int(parsed.get("mood_confidence")), 0, 100)
    mood_reason = str(parsed.get("mood_reason", "") or "").strip()
    if mood not in VALID_MOODS:
        if mood:
            notes.append(f"未知 mood {mood!r}，交给本地情绪判断")
        mood = ""
    if len(summary) > SUMMARY_MAX_LEN:
        notes.append(f"summary 超过 {SUMMARY_MAX_LEN} 字，已截断")
        summary = summary[:SUMMARY_MAX_LEN]
    if len(advice) > ADVICE_MAX_LEN:
        notes.append(f"advice 超过 {ADVICE_MAX_LEN} 字，已截断")
        advice = advice[:ADVICE_MAX_LEN]
    if len(mood_reason) > MOOD_REASON_MAX_LEN:
        notes.append(f"mood_reason 超过 {MOOD_REASON_MAX_LEN} 字，已截断")
        mood_reason = mood_reason[:MOOD_REASON_MAX_LEN]

    result = {
        "world_display_name": str(parsed.get("world_display_name", "") or ""),
        "summary": summary,
        "advice": advice,
        "mood": mood,
        "mood_intensity": mood_intensity,
        "mood_confidence": mood_confidence,
        "mood_reason": mood_reason,
        "events": events,
    }

    # 用 Pydantic 再做一次严格校验（缺 name / 数值越界已在 _repair_event 兜底，
    # 这里主要兜住 Pydantic 自身的额外约束，如 tags 超长）
    if BaseModel is not object:
        try:
            AIResponse(**result)
        except ValidationError as exc:  # pragma: no cover - 防御性兜底
            notes.append(f"Pydantic 校验未通过（{exc}），改用默认事件")
            result["events"] = [default_event()]
    return result, notes


def default_event() -> dict:
    """本地兜底事件：任何修复都失败时页面仍能显示内容（bug1 第 4 步 Fallback）。"""
    return {
        "name": "平凡的一天",
        "description": "今天风平浪静，没什么特别的事。",
        "hp": 0,
        "mp": 0,
        "gold": 0,
        "gold_or_san": 0,
        "exp": 1,
        "tags": ["日常"],
    }


def default_response() -> dict:
    """完全兜底的响应：重试耗尽后由 llm_client 返回，页面永不崩溃。"""
    return {
        "world_display_name": "",
        "summary": "AI 编译器今天状态不佳，暂时按平凡的一天结算。",
        "advice": "请稍后再试。",
        "mood": "calm",
        "mood_intensity": 20,
        "mood_confidence": 0,
        "mood_reason": "今天的情绪线索比较平稳。",
        "events": [default_event()],
    }
