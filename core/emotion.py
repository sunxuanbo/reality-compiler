# -*- coding: utf-8 -*-
"""情绪状态与本地兜底判断。

情绪只用于界面氛围与复盘提示，不构成心理或医学诊断。AI 返回可信时优先使用；
字段缺失、取值异常或置信度不足时，使用事件数值与原始日常文本做确定性兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MOODS = ("joyful", "calm", "sad", "anxious", "angry", "mixed")
MOOD_LABELS = {
    "joyful": "开心",
    "calm": "平静",
    "sad": "难过",
    "anxious": "焦虑",
    "angry": "生气",
    "mixed": "复杂",
}
MOOD_ICONS = {
    "joyful": "✦",
    "calm": "◌",
    "sad": "☂",
    "anxious": "⌁",
    "angry": "◆",
    "mixed": "◐",
}

_ALIASES = {
    "happy": "joyful", "joy": "joyful", "joyful": "joyful", "开心": "joyful", "快乐": "joyful",
    "calm": "calm", "neutral": "calm", "平静": "calm", "平稳": "calm",
    "sad": "sad", "down": "sad", "难过": "sad", "悲伤": "sad", "低落": "sad",
    "anxious": "anxious", "anxiety": "anxious", "焦虑": "anxious", "紧张": "anxious",
    "angry": "angry", "anger": "angry", "生气": "angry", "愤怒": "angry",
    "mixed": "mixed", "complex": "mixed", "复杂": "mixed", "混合": "mixed",
}

_KEYWORDS = {
    "joyful": ("开心", "快乐", "高兴", "惊喜", "幸福", "顺利", "完成", "成功", "喜欢", "庆祝", "放松"),
    "calm": ("平静", "安静", "安心", "悠闲", "散步", "冥想", "休息", "舒服", "惬意"),
    "sad": ("难过", "悲伤", "伤心", "低落", "失望", "孤独", "想哭", "哭了", "遗憾", "疲惫"),
    "anxious": ("焦虑", "紧张", "担心", "害怕", "不安", "压力", "慌", "deadline", "截止", "失眠"),
    "angry": ("生气", "愤怒", "恼火", "火大", "被骂", "吵架", "烦死", "不公平", "委屈"),
}
_GENTLE_WORDS = ("不想活", "想死", "自杀", "自残", "结束生命", "活不下去")


def clamp_percent(value, default: int = 0) -> int:
    """把任意数值安全限制到 0~100。"""
    if isinstance(value, bool):
        return default
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        number = default
    return max(0, min(100, number))


def normalize_mood(value: object) -> str:
    """把 AI 可能使用的中英文情绪名归一化为六类枚举。"""
    return _ALIASES.get(str(value or "").strip().lower(), "")


@dataclass(frozen=True)
class EmotionState:
    mood: str = "calm"
    intensity: int = 20
    confidence: int = 0
    reason: str = "今天的情绪线索比较平稳。"
    source: str = "local"
    gentle: bool = False

    @property
    def label(self) -> str:
        return MOOD_LABELS.get(self.mood, MOOD_LABELS["calm"])

    @property
    def icon(self) -> str:
        return MOOD_ICONS.get(self.mood, MOOD_ICONS["calm"])


def _event_parts(events: Iterable[object]) -> tuple[str, int, int, int]:
    """归一化事件文本，并汇总 HP/MP/EXP。支持 dict 与 MatchedEvent。"""
    chunks: list[str] = []
    hp = mp = exp = 0
    for item in events or []:
        if isinstance(item, dict):
            name = item.get("name", "")
            desc = item.get("description", "")
            tags = item.get("tags") or []
            hp_raw, mp_raw, exp_raw = item.get("hp", 0), item.get("mp", 0), item.get("exp", 0)
        else:
            event = getattr(item, "event", item)
            name = getattr(event, "name", "")
            desc = getattr(event, "description", "")
            tags = getattr(event, "keywords", ()) or ()
            hp_raw, mp_raw, exp_raw = (
                getattr(event, "hp", 0), getattr(event, "mp", 0), getattr(event, "exp", 0)
            )
        chunks.extend((str(name), str(desc), " ".join(str(tag) for tag in tags)))
        for raw, target in ((hp_raw, "hp"), (mp_raw, "mp"), (exp_raw, "exp")):
            try:
                value = int(round(float(raw)))
            except (TypeError, ValueError, OverflowError):
                value = 0
            if target == "hp":
                hp += value
            elif target == "mp":
                mp += value
            else:
                exp += value
    return " ".join(chunks).lower(), hp, mp, exp


def _fallback_emotion(
    source_text: str,
    events: Iterable[object],
    simulation_state: dict | None = None,
) -> EmotionState:
    event_text, hp, mp, exp = _event_parts(events)
    text = f"{source_text} {event_text}".lower()
    scores = {mood: 0 for mood in MOODS if mood != "mixed"}
    for mood, words in _KEYWORDS.items():
        scores[mood] += sum(3 for word in words if word in text)

    positive = max(0, hp) + max(0, mp)
    negative = max(0, -hp) + max(0, -mp)
    scores["joyful"] += min(8, positive // 6) + min(3, exp // 5)
    scores["sad"] += min(8, negative // 7)
    if negative >= 30:
        scores["anxious"] += 2

    sim = simulation_state or {}
    try:
        stress = int(sim.get("stress", 0) or 0)
        energy = int(sim.get("energy", 70) or 70)
        sleep_debt = int(sim.get("sleep_debt", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        stress, energy, sleep_debt = 0, 70, 0
    if stress >= 65:
        scores["anxious"] += 5
    if energy <= 30 or sleep_debt >= 70:
        scores["sad"] += 3

    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], MOODS.index(pair[0])))
    top_mood, top_score = ranked[0]
    second_mood, second_score = ranked[1]
    opposed = {top_mood, second_mood} & {"joyful", "calm"} and {top_mood, second_mood} & {"sad", "anxious", "angry"}
    if top_score >= 4 and second_score >= 4 and (top_score - second_score <= 2 or opposed):
        mood = "mixed"
        score = top_score + second_score
    elif top_score > 0:
        mood = top_mood
        score = top_score
    else:
        mood = "calm"
        score = 2

    intensity = clamp_percent(16 + score * 7, 20)
    reason_map = {
        "joyful": "记录里有明显的积极体验与能量恢复。",
        "calm": "记录里的情绪与生活节奏整体比较平稳。",
        "sad": "记录里出现了失落、疲惫或能量下降的线索。",
        "anxious": "记录里出现了压力、担心或紧绷感的线索。",
        "angry": "记录里出现了冲突、委屈或恼火的线索。",
        "mixed": "记录里同时出现了积极与消耗性的情绪线索。",
    }
    gentle = any(word in text for word in _GENTLE_WORDS)
    return EmotionState(
        mood=mood,
        intensity=min(intensity, 38) if gentle else intensity,
        confidence=min(88, 45 + score * 4),
        reason="现在更重要的是先照顾好自己，界面会保持安静克制。" if gentle else reason_map[mood],
        source="local",
        gentle=gentle,
    )


def resolve_emotion(
    ai_data: dict | None,
    source_text: str,
    events: Iterable[object],
    simulation_state: dict | None = None,
    *,
    confidence_threshold: int = 55,
) -> EmotionState:
    """解析 AI 情绪；不可信时回退到纯本地判断。"""
    data = ai_data if isinstance(ai_data, dict) else {}
    mood = normalize_mood(data.get("mood"))
    confidence = clamp_percent(data.get("mood_confidence"), 0)
    gentle = any(word in str(source_text).lower() for word in _GENTLE_WORDS)
    if mood and confidence >= confidence_threshold:
        reason = str(data.get("mood_reason") or "").strip()[:120]
        if not reason:
            reason = f"AI 从这段记录中识别到较明显的{MOOD_LABELS[mood]}情绪。"
        return EmotionState(
            mood=mood,
            intensity=min(clamp_percent(data.get("mood_intensity"), 20), 38) if gentle else clamp_percent(data.get("mood_intensity"), 20),
            confidence=confidence,
            reason="现在更重要的是先照顾好自己，界面会保持安静克制。" if gentle else reason,
            source="ai",
            gentle=gentle,
        )
    return _fallback_emotion(source_text, events, simulation_state)
