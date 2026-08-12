# -*- coding: utf-8 -*-
"""情绪模型、兼容修复与安全渲染自检。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.emotion import MOODS, resolve_emotion
from core.schema_validator import validate_and_repair
from ui.render import emotion_card_html, mood_ambience_html


def check(name: str, condition: bool) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        raise AssertionError(name)


def run() -> None:
    base_event = [{"name": "普通日常", "description": "平稳度过一天", "hp": 0, "mp": 0, "exp": 1, "tags": ["日常"]}]

    for mood in MOODS:
        state = resolve_emotion({
            "mood": mood,
            "mood_intensity": 72,
            "mood_confidence": 88,
            "mood_reason": f"识别为{mood}",
        }, "今天的记录", base_event)
        check(f"AI 六类情绪可识别：{mood}", state.mood == mood and state.source == "ai")

    repaired, notes = validate_and_repair(json.dumps({
        "mood": "joyful",
        "mood_intensity": 999,
        "mood_confidence": -30,
        "mood_reason": "很好" * 100,
        "events": base_event,
    }, ensure_ascii=False))
    check("情绪强度上限被截断", repaired["mood_intensity"] == 100)
    check("情绪置信度下限被截断", repaired["mood_confidence"] == 0)
    check("情绪原因限制长度", len(repaired["mood_reason"]) == 120)

    legacy, _ = validate_and_repair(json.dumps({"summary": "旧响应", "events": base_event}, ensure_ascii=False))
    state = resolve_emotion(legacy, "今天很开心，事情都很顺利", legacy["events"])
    check("旧响应缺情绪字段时本地兜底", state.source == "local" and state.mood == "joyful")

    invalid, _ = validate_and_repair(json.dumps({"mood": "excited", "events": base_event}, ensure_ascii=False))
    check("未知情绪值不穿透白名单", invalid["mood"] == "")

    low_conf = resolve_emotion({
        "mood": "joyful", "mood_intensity": 90, "mood_confidence": 20,
    }, "今天压力很大，非常焦虑和担心", base_event)
    check("低置信度 AI 判断被本地结果替代", low_conf.source == "local" and low_conf.mood == "anxious")

    mixed = resolve_emotion({}, "项目成功了很开心，但身体也非常疲惫和难过", [
        {"name": "完成项目", "hp": 12, "mp": -12, "exp": 10, "tags": ["成功", "疲惫"]}
    ])
    check("正负线索并存识别为复杂情绪", mixed.mood == "mixed")

    gentle = resolve_emotion({}, "我现在觉得活不下去", base_event)
    check("高风险负面文字启用克制模式", gentle.gentle and gentle.intensity <= 38)

    html = emotion_card_html(resolve_emotion({
        "mood": "sad", "mood_intensity": 60, "mood_confidence": 90,
        "mood_reason": "<script>alert(1)</script>",
    }, "难过", base_event))
    check("情绪原因经过 HTML 转义", "<script>" not in html and "&lt;script&gt;" in html)
    check("氛围类名只使用六类白名单", 'data-mood="sad"' in mood_ambience_html(resolve_emotion({
        "mood": "sad", "mood_intensity": 60, "mood_confidence": 90,
    }, "难过", base_event)))

    print("\n情绪系统自检通过 ✓")


if __name__ == "__main__":
    run()
