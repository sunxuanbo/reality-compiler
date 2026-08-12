# -*- coding: utf-8 -*-
"""本地日志系统：编译结果 JSONL 落盘 + 日 / 周 / 月统计。

UI 日志文件：<项目根>/logs/<会话ID>/reality_YYYY-MM-DD.log
（按会话隔离、按天分割，JSONL：每行一条 JSON）。未提供 namespace 的底层调用
仍写入 <项目根>/logs/，以兼容命令行与旧版调用。

【天的时间分区】每天早 6:00 到次日早 6:00 视为同一天（logical_day）：
    2026-08-06 23:30  -> 归属 2026-08-06（reality_2026-08-06.log）
    2026-08-07 02:00  -> 归属 2026-08-06（凌晨 0:00-5:59 归入前一天的文件）

统计维度：
    - 日统计   ：今日事件数 / HP / MP / 金钱净变化 / 获得经验 / 标签 TOP3
    - 周统计   ：本周（周一~周日）总事件数 / 日均 HP、金钱变化 / 周累计经验 / 标签 TOP5
    - 月统计   ：本月（1 号~月底）总事件数 / 月均 HP、MP、金钱 / 月累计经验 / 等级轨迹 / 标签 TOP5
均基于上面的「逻辑日」归属（早 6 点分区）。

说明：净变化由每条日志的 events 增量聚合得出；stats 字段保存的是当次编译的
当前值（hp / mp / gold / level / exp），用于「属性趋势」与「等级轨迹」展示。
"""

from __future__ import annotations

import datetime
import json
import re
import threading
from collections import Counter
from pathlib import Path

from .runtime import events_to_plain


# ----------------------------------------------------------------------------
# 路径与基础读写
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"                       # 日志根目录（项目根/logs）
_FILE_LOCK = threading.RLock()


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return default


def _namespace_dir(namespace: str | None = None) -> Path:
    """返回日志目录；namespace 用于隔离不同 UI 会话。"""
    if not namespace:
        return LOGS_DIR
    safe = "".join(re.findall(r"[A-Za-z0-9_-]+", str(namespace)))[:64]
    return LOGS_DIR / (safe or "session")


def _ensure_logs_dir(namespace: str | None = None) -> Path:
    path = _namespace_dir(namespace)
    path.mkdir(parents=True, exist_ok=True)
    return path


def logical_day(dt: datetime.datetime) -> datetime.date:
    """把一个时间点归属到「逻辑日」：早 6 点分区（6:00 ~ 次日 5:59 同一天）。"""
    return (dt - datetime.timedelta(hours=6)).date()


def day_file(day: datetime.date, *, namespace: str | None = None) -> Path:
    """某个逻辑日对应的日志文件路径。"""
    return _namespace_dir(namespace) / f"reality_{day.isoformat()}.log"


def append_log(entry: dict, *, namespace: str | None = None) -> Path:
    """把一条日志记录追加写入当天（按早 6 点分区）的 JSONL 文件。

    返回写入的文件路径。
    """
    _ensure_logs_dir(namespace)
    ts = entry.get("timestamp")
    try:
        dt = datetime.datetime.fromisoformat(ts) if ts else None
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        path = day_file(logical_day(datetime.datetime.now().astimezone()), namespace=namespace)
    else:
        path = day_file(logical_day(dt), namespace=namespace)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _FILE_LOCK, path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
    return path


def read_logs(day: datetime.date, *, namespace: str | None = None) -> list[dict]:
    """读取某个逻辑日的全部日志（文件不存在返回空列表）。"""
    path = day_file(day, namespace=namespace)
    if not path.exists():
        return []
    out: list[dict] = []
    with _FILE_LOCK, path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    out.append(item)
            except ValueError:
                continue          # 跳过损坏行，不影响整体
    return out


def read_range(
    d1: datetime.date,
    d2: datetime.date,
    *,
    namespace: str | None = None,
) -> list[dict]:
    """读取 [d1, d2]（含两端）区间内所有逻辑日的日志。"""
    out: list[dict] = []
    cur = d1
    while cur <= d2:
        out.extend(read_logs(cur, namespace=namespace))
        cur += datetime.timedelta(days=1)
    return out


# ----------------------------------------------------------------------------
# 日志记录构造
# ----------------------------------------------------------------------------
def build_entry(result, log, world, user_input: str) -> dict:
    """由一次编译结果构造一条日志记录（写入前可再补字段）。

    result: CompileResult（含 matched 命中事件）
    log:    RuntimeLog（含 state / chips）
    world:  WorldProfile（世界观名 / 货币名）
    user_input: 用户输入的原始日常文本
    """
    return {
        "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "world_name": world.label,
        "currency_name": world.variable_stat.name,
        "user_input": user_input,
        "events": events_to_plain(result.matched),
        "stats": {
            "hp": log.state.hp,
            "mp": log.state.mp,
            "gold": log.state.vstat,
            "level": log.state.level,
            "exp": log.state.exp,
        },
        "tags": [name for name, _kind in log.chips],
        "mood": getattr(getattr(result, "emotion", None), "mood", ""),
        "mood_intensity": _safe_int(
            getattr(getattr(result, "emotion", None), "intensity", 0)
        ),
    }


# ----------------------------------------------------------------------------
# 聚合与统计
# ----------------------------------------------------------------------------
def _aggregate(logs: list[dict]) -> dict:
    """聚合一段日志：事件数 / HP、MP、金钱、经验净变化 / 标签计数 / 等级轨迹。"""
    total_events = 0
    hp = mp = gold = exp = 0
    tag_counter: Counter[str] = Counter()
    mood_counter: Counter[str] = Counter()
    by_day_level: dict[datetime.date, int] = {}

    for entry in logs:
        if not isinstance(entry, dict):
            continue
        events = entry.get("events", [])
        if not isinstance(events, list):
            events = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            total_events += 1
            hp += _safe_int(ev.get("hp"))
            mp += _safe_int(ev.get("mp"))
            gold += _safe_int(ev.get("gold"))
            exp += _safe_int(ev.get("exp"))
        tags = entry.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, (list, tuple)):
            tags = []
        for tag in tags:
            if tag:
                tag_counter[str(tag)] += 1
        mood = str(entry.get("mood") or "")
        if mood in {"joyful", "calm", "sad", "anxious", "angry", "mixed"}:
            mood_counter[mood] += 1
        stats = entry.get("stats") or {}
        if stats.get("level") is not None:
            try:
                d = logical_day(datetime.datetime.fromisoformat(entry["timestamp"]))
            except (KeyError, ValueError, TypeError):
                d = datetime.date.today()
            by_day_level[d] = _safe_int(stats["level"])

    days_with_logs = len({_logical_day_of(e) for e in logs})
    return {
        "total_events": total_events,
        "hp": hp,
        "mp": mp,
        "gold": gold,
        "exp": exp,
        "top_tags": [tag for tag, _ in tag_counter.most_common()],
        "days_with_logs": days_with_logs,
        "level_track": [lv for _d, lv in sorted(by_day_level.items())],
        "max_level": max(by_day_level.values()) if by_day_level else 0,
        "mood_distribution": dict(mood_counter),
        "dominant_mood": mood_counter.most_common(1)[0][0] if mood_counter else "",
    }


def _logical_day_of(entry: dict) -> datetime.date:
    try:
        return logical_day(datetime.datetime.fromisoformat(entry["timestamp"]))
    except (KeyError, ValueError, TypeError):
        return datetime.date.today()


def _today() -> datetime.date:
    return logical_day(datetime.datetime.now().astimezone())


def _week_range() -> tuple[datetime.date, datetime.date]:
    """本周逻辑日范围（周一 ~ 周日）。"""
    today = _today()
    monday = today - datetime.timedelta(days=today.weekday())
    return monday, monday + datetime.timedelta(days=6)


def _month_range() -> tuple[datetime.date, datetime.date]:
    """本月逻辑日范围（1 号 ~ 月底）。"""
    first = _today().replace(day=1)
    if first.month == 12:
        last = datetime.date(first.year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last = datetime.date(first.year, first.month + 1, 1) - datetime.timedelta(days=1)
    return first, last


def count_today(*, namespace: str | None = None) -> int:
    """今日日志条数（早 6 点分区）。"""
    return len(read_logs(_today(), namespace=namespace))


def count_week(*, namespace: str | None = None) -> int:
    """本周日志条数（周一 ~ 周日，早 6 点分区）。"""
    d1, d2 = _week_range()
    return len(read_range(d1, d2, namespace=namespace))


def count_month(*, namespace: str | None = None) -> int:
    """本月日志条数（1 号 ~ 月底）。"""
    d1, d2 = _month_range()
    return len(read_range(d1, d2, namespace=namespace))


# ----------------------------------------------------------------------------
# 公开的日期范围（供 UI 层获取 logs 与周期文案）
# ----------------------------------------------------------------------------
def current_day() -> datetime.date:
    """当前「逻辑日」（早 6 点分区）。"""
    return _today()


def week_range() -> tuple[datetime.date, datetime.date]:
    """本周逻辑日范围（周一 ~ 周日）。"""
    return _week_range()


def month_range() -> tuple[datetime.date, datetime.date]:
    """本月逻辑日范围（1 号 ~ 月底）。"""
    return _month_range()


def stats_today(*, namespace: str | None = None) -> dict:
    """今日统计：事件数 / HP、MP、金钱净变化 / 经验 / 标签 TOP3。"""
    logs = read_logs(_today(), namespace=namespace)
    agg = _aggregate(logs)
    return {
        "period": "今日",
        "events": agg["total_events"],
        "hp_delta": agg["hp"],
        "mp_delta": agg["mp"],
        "gold_delta": agg["gold"],
        "exp_gain": agg["exp"],
        "top_tags": agg["top_tags"][:3],
        "mood_distribution": agg["mood_distribution"],
        "dominant_mood": agg["dominant_mood"],
    }


def stats_week(*, namespace: str | None = None) -> dict:
    """本周统计：总事件数 / 日均 HP、金钱 / 周累计经验 / 标签 TOP5。"""
    d1, d2 = _week_range()
    logs = read_range(d1, d2, namespace=namespace)
    agg = _aggregate(logs)
    days = agg["days_with_logs"]
    return {
        "period": "本周",
        "events": agg["total_events"],
        "avg_hp": round(agg["hp"] / days) if days else 0,
        "avg_gold": round(agg["gold"] / days) if days else 0,
        "exp_gain": agg["exp"],
        "top_tags": agg["top_tags"][:5],
        "mood_distribution": agg["mood_distribution"],
        "dominant_mood": agg["dominant_mood"],
    }


def stats_month(*, namespace: str | None = None) -> dict:
    """本月统计：总事件数 / 月均 HP、MP、金钱 / 月累计经验 / 等级轨迹 / 标签 TOP5。"""
    d1, d2 = _month_range()
    logs = read_range(d1, d2, namespace=namespace)
    agg = _aggregate(logs)
    days = agg["days_with_logs"]
    return {
        "period": "本月",
        "events": agg["total_events"],
        "avg_hp": round(agg["hp"] / days) if days else 0,
        "avg_mp": round(agg["mp"] / days) if days else 0,
        "avg_gold": round(agg["gold"] / days) if days else 0,
        "exp_gain": agg["exp"],
        "level_track": agg["level_track"],
        "top_tags": agg["top_tags"][:5],
        "mood_distribution": agg["mood_distribution"],
        "dominant_mood": agg["dominant_mood"],
    }
