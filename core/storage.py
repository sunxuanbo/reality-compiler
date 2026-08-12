# -*- coding: utf-8 -*-
"""浏览器 localStorage 持久化的「数据层」（v2.6，bug4）。

背景：
    Streamlit 的 st.session_state 是「服务端内存」，关闭标签页 / 换浏览器即丢失，
    与产品定位「我的人生 RPG（数据持续累积）」冲突。bug4 选择浏览器 localStorage：
    同一浏览器永久保存，换浏览器 / 清缓存才丢失（Demo / 个人工具可接受）。

分层约定（Agent.md 铁律）：
    本模块属于 core/，只做「数据快照的构建 / 恢复 / 清理 / 序列化」这类纯 Python
    逻辑，【禁止 import streamlit】——真正的 localStorage 读写（浏览器 JS 桥接）
    放在 app.py（流程层）完成，本模块只提供它要用的数据格式与规则。

存储内容（与 bug4 对齐）：
    {
        "world":       世界观摘要（名称/背景/货币名/stat_mapping）
        "stats":       最近一次编译的属性面板（hp/mp/gold/exp/level）
        "logs":        最近 30 天的日志列表（超过 30 天自动清理）
        "last_update": 最近一次写入时间（ISO 8601）
    }
"""

from __future__ import annotations

import datetime
import json
from typing import Any

STORAGE_KEY = "reality_compiler_data"   # localStorage / session_state 中的统一存储键
MAX_LOG_DAYS = 30                       # 日志保留天数（localStorage 有容量上限，滚动清理）
SNAPSHOT_VERSION = 1                    # 快照结构版本号，将来结构变化时便于迁移


# ----------------------------------------------------------------------------
# 序列化 / 反序列化
# ----------------------------------------------------------------------------
def serialize(data: dict) -> str:
    """把快照 dict 序列化成 JSON 字符串（localStorage 只能存字符串）。"""
    payload = dict(data)
    payload["_v"] = SNAPSHOT_VERSION
    return json.dumps(payload, ensure_ascii=False)


def deserialize(raw: str | None) -> dict | None:
    """把 JSON 字符串还原成快照 dict；损坏 / 版本不符返回 None（安全降级）。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("_v") != SNAPSHOT_VERSION:
        return None
    return data


# ----------------------------------------------------------------------------
# 快照构建（数据变化后调用）
# ----------------------------------------------------------------------------
def build_snapshot(
    world: Any,
    stats: dict | None,
    logs: list[dict] | None,
    *,
    now: datetime.datetime | None = None,
) -> dict:
    """把当前会话的关键数据打包成一份快照。

    参数：
        world: WorldProfile 对象（取 label / desc / 可变属性名 / stat_mapping）
        stats: 最近一次编译的 RuntimeState 的 dict（hp/mp/vstat/exp/level）
        logs:  最近日志列表（core.logger.read_range 的返回，会先按 30 天清理）
        now:   可注入的当前时间（测试用）
    返回：
        结构化快照 dict（可直接 serialize() 存 localStorage）
    """
    now = now or datetime.datetime.now().astimezone()
    vstat_name = world.variable_stat.name if world else ""
    return {
        "world": {
            "world_name": world.label if world else "",
            "world_description": world.desc if world else "",
            "currency_name": vstat_name,
            "stat_mapping": {
                "hp": "生命值",
                "mp": "精力值",
                "gold": vstat_name,
            },
        },
        "stats": {
            "hp": int(stats.get("hp", 0)) if stats else 0,
            "mp": int(stats.get("mp", 0)) if stats else 0,
            "gold": int(stats.get("vstat", stats.get("gold", 0))) if stats else 0,
            "exp": int(stats.get("exp", 0)) if stats else 0,
            "level": int(stats.get("level", 1)) if stats else 1,
        },
        "logs": clean_old_logs(list(logs or []), now=now),
        "last_update": now.isoformat(timespec="seconds"),
    }


# ----------------------------------------------------------------------------
# 日志滚动清理（bug4 存储空间管理：只保留最近 30 天）
# ----------------------------------------------------------------------------
def clean_old_logs(
    logs: list[dict],
    *,
    days: int = MAX_LOG_DAYS,
    now: datetime.datetime | None = None,
) -> list[dict]:
    """删除超过 days 天的日志条目。

    logs 每条需含 ISO 8601 的 timestamp 字段（core.logger.build_entry 的输出）；
    无法解析时间戳的条目按「保留」处理（宁多勿丢）。
    """
    now = now or datetime.datetime.now().astimezone()
    cutoff = now - datetime.timedelta(days=days)
    kept: list[dict] = []
    for entry in logs:
        ts = entry.get("timestamp")
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            kept.append(entry)          # 无有效时间戳 → 保留
            continue
        # 统一成带时区比较（无时区视为本地时区）
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        if dt >= cutoff:
            kept.append(entry)
    return kept


# ----------------------------------------------------------------------------
# 恢复（页面加载时调用）：把快照字段映射回当前项目使用的 key
# ----------------------------------------------------------------------------
def restore_session(snapshot: dict) -> dict:
    """把快照转成「可写回 st.session_state 的 key-value 映射」。

    返回形如 {"cfg_key": value} 的字典，由 app.py 负责写入 session_state。
    只做纯映射，不触碰任何 Streamlit API。
    """
    result: dict[str, Any] = {}
    world = snapshot.get("world") or {}
    if world:
        result["world_name"] = world.get("world_name", "")
        result["world_description"] = world.get("world_description", "")
        result["currency_name"] = world.get("currency_name", "")
    stats = snapshot.get("stats") or {}
    if stats:
        result["hp"] = int(stats.get("hp", 0))
        result["mp"] = int(stats.get("mp", 0))
        result["gold"] = int(stats.get("gold", 0))
        result["exp"] = int(stats.get("exp", 0))
        result["level"] = int(stats.get("level", 1))
    logs = snapshot.get("logs")
    if logs is not None:
        result["logs"] = clean_old_logs(list(logs))
    if snapshot.get("last_update"):
        result["last_update"] = snapshot["last_update"]
    return result
