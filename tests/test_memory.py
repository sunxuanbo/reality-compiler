# -*- coding: utf-8 -*-
"""记忆系统自检（v3.0 Phase 3）：database / short_term / long_term / retriever / Agent 接入。

运行方式：python tests/test_memory.py
覆盖重点：
    - Database：建表 / WAL / wipe
    - Repository：档案 upsert / 事件写入与查询 / 偏好权重累计
    - ShortTermMemory：FIFO 容量淘汰 / 清空
    - LongTermMemory：save_event / observe_tags / profiles
    - MemoryRetriever：组装 context（profile / recent / prefs）
    - RealityAgent 接入：记忆开启时检索注入 + 编译后归档（fake LLM）
"""

from __future__ import annotations

import os
import sys
import json
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.database import Database, Repository, default_db_path
from core.memory import ShortTermMemory, LongTermMemory, MemoryRetriever
from core.agent import RealityAgent
from core.world_config import world_from_ai


PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    """断言并计数。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✔ {name}")
    else:
        FAIL += 1
        print(f"  ✘ FAIL: {name}")


def _tmp_db() -> Database:
    """临时目录里的数据库（不污染项目 data/）。"""
    tmp = tempfile.mkdtemp(prefix="rc_mem_test_")
    return Database(Path(tmp) / "test.db")


def _test_world(name: str = "赛博纪元", currency: str = "比特币"):
    data = {
        "world_name": name,
        "world_description": "AI 生成的测试世界观",
        "currency_name": currency,
        "stat_mapping": {"hp": "生命值", "mp": "精力值", "gold": currency},
    }
    return world_from_ai(data, "day-test")


def main() -> None:
    print("=== 记忆系统自检 ===")

    # 1. Database 基础
    print("\n[1] Database")
    db = _tmp_db()
    check("建表成功（events 表可查）", db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='events'"))
    check("建表成功（preferences 表可查）", db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='preferences'"))
    check("建表成功（user_profile 表可查）", db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile'"))
    # WAL 模式
    wal = db.query("PRAGMA journal_mode")[0][0]
    check("WAL 模式启用", str(wal).lower() == "wal")
    db.wipe()
    check("wipe 清空事件表", db.query("SELECT COUNT(*) AS n FROM events")[0]["n"] == 0)
    db.close()
    check("close 后可重开", True)

    # 2. Repository
    print("\n[2] Repository")
    db = _tmp_db()
    repo = Repository(db)

    # 档案 upsert
    repo.set_profile("nickname", "小明")
    repo.set_profile("nickname", "小明同学")       # 覆盖
    repo.set_profile("habit", "熬夜")
    check("档案写入与覆盖", repo.get_profile("nickname") == "小明同学")
    check("档案全部读取", set(repo.all_profiles().keys()) == {"nickname", "habit"})

    # 事件写入与查询
    eid = repo.add_event(
        date="2026-08-08", source="今天加班到凌晨", summary="疲惫的一天",
        advice="早点睡", attributes={"events": 1, "hp_total": -10},
        tags=["加班", "熬夜"], world_label="赛博纪元",
    )
    check("事件写入返回 id", eid > 0)
    recent = repo.recent_events(10)
    check("事件查询", len(recent) == 1 and recent[0]["tags"] == ["加班", "熬夜"])
    check("事件属性 JSON 已解析", recent[0]["attributes"]["hp_total"] == -10)
    check("事件按日期过滤", len(repo.events_on("2026-08-08")) == 1)
    check("事件计数", repo.count_events() == 1)

    # 偏好权重累计
    repo.bump_pref("tag:加班", "加班", 1.0)
    repo.bump_pref("tag:加班", "加班", 1.0)
    repo.bump_pref("tag:熬夜", "熬夜", 1.0)
    top = repo.top_prefs(5)
    check("偏好权重累计", top[0]["key"] == "tag:加班" and top[0]["weight"] == 2.0)
    check("偏好按权重排序", top[0]["key"] == "tag:加班" and top[1]["key"] == "tag:熬夜")
    workers = [threading.Thread(
        target=lambda: [repo.bump_pref("tag:并发", "并发", 1.0) for _ in range(25)]
    ) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    concurrent = next(p for p in repo.top_prefs(20) if p["key"] == "tag:并发")
    check("并发偏好累加不丢更新", concurrent["weight"] == 100.0)

    # 3. ShortTermMemory
    print("\n[3] ShortTermMemory")
    stm = ShortTermMemory(capacity=3)
    for i in range(5):
        stm.remember({"id": i, "summary": f"事件{i}"})
    check("FIFO 淘汰最旧", len(stm) == 3 and stm.latest()["id"] == 4)
    check("recent 取最近 2 条", [x["id"] for x in stm.recent(2)] == [3, 4])
    stm.clear()
    check("clear 清空", stm.is_empty)

    # 4. LongTermMemory
    print("\n[4] LongTermMemory")
    ltm = LongTermMemory(db)
    ltm.set_profile("nickname", "小明同学")
    ltm.save_event(
        date="2026-08-08", source="早起跑步", summary="晨跑五公里",
        tags=["跑步", "健康"], world_label="赛博纪元",
    )
    ltm.observe_tags(["跑步", "健康"])
    check("档案读取", ltm.get_profile("nickname") == "小明同学")
    check("事件保存", ltm.total_events() == 2)
    check("标签偏好观察", ltm.get_pref("tag:跑步") == "跑步")
    check("偏好 Top 含健康", any(p["value"] == "健康" for p in ltm.top_prefs(10)))

    # 5. MemoryRetriever
    print("\n[5] MemoryRetriever")
    rtv = MemoryRetriever(long_term=ltm, short_term=stm, max_recent=3, max_prefs=3)
    check("空的短期记忆注入不会被替换", rtv.short_term is stm)
    ctx = rtv.retrieve(date="2026-08-08")
    check("检索返回 memory_enabled", ctx.get("memory_enabled") is True)
    check("检索含用户档案", ctx.get("profile", {}).get("nickname") == "小明同学")
    check("检索含近期事件", isinstance(ctx.get("recent"), list) and len(ctx["recent"]) >= 1)
    check("检索含偏好", isinstance(ctx.get("prefs"), list) and len(ctx["prefs"]) >= 1)
    # 检索结果可序列化（JSON 安全，供 prompt 拼装）
    check("检索结果可 JSON 序列化", isinstance(json.dumps(ctx, ensure_ascii=False), str))

    # 6. RealityAgent 接入记忆
    print("\n[6] RealityAgent + 记忆")
    db2 = _tmp_db()
    ltm2 = LongTermMemory(db2)
    rtv2 = MemoryRetriever(long_term=ltm2)
    ltm2.set_profile("nickname", "小明同学")
    ltm2.observe_tags(["健康"])

    captured = {}

    def _fake_llm(world, user_text, date_str, **kw):
        captured["context"] = kw.get("context")
        return {
            "world_display_name": world.label,
            "summary": "加班的一天。",
            "advice": "早点休息。",
            "events": [
                {"name": "加班", "description": "肝", "hp": -10, "mp": -5,
                 "gold_or_san": -3, "exp": 2, "tags": ["加班"]},
            ],
        }

    agent = RealityAgent(llm_generate=_fake_llm, retriever=rtv2)
    result = agent.run("今天加班到凌晨", _test_world(), memory=ltm2, enable_reflection=False)

    check("记忆上下文注入 LLM", captured.get("context", {}).get("profile", {}).get("nickname") == "小明同学")
    check("Agent 编译正常", result.compile.source == "今天加班到凌晨")
    check("编译后归档事件", ltm2.total_events() >= 1)
    check("编译后归档标签偏好", ltm2.get_pref("tag:加班") == "加班")
    check("编译后写入短期记忆", not rtv2.short_term.is_empty)
    check("plan 含记忆上下文", result.plan.context is not None and result.plan.context.get("profile"))
    # 记忆失败不影响编译：传损坏 retriever 也应正常
    class _BadRetriever:
        def retrieve(self, **kw):
            raise RuntimeError("boom")
    agent_bad = RealityAgent(llm_generate=_fake_llm, retriever=_BadRetriever())
    r2 = agent_bad.run("测试", _test_world(), memory=ltm2, enable_reflection=False)
    check("记忆检索失败不影响编译", r2.compile.source == "测试")

    # 7. 记忆关闭（memory=None）不读写
    print("\n[7] 记忆关闭")
    captured_off = {}

    def _fake_llm_off(world, user_text, date_str, **kw):
        captured_off["context"] = kw.get("context")
        return {
            "world_display_name": world.label,
            "summary": "关闭记忆。",
            "advice": "",
            "events": [{"name": "测试", "hp": 0, "exp": 1, "tags": []}],
        }

    _before_off = ltm2.total_events()       # 记录归档前的数量
    agent_off = RealityAgent(llm_generate=_fake_llm_off)
    r3 = agent_off.run("关闭记忆", _test_world(), memory=None, enable_reflection=False)
    check("不传 memory 正常编译", r3.compile.source == "关闭记忆")
    check("不传 memory 不注入上下文", captured_off.get("context") is None)
    check("不传 memory 不写记忆", ltm2.total_events() == _before_off)

    # 清理：关闭临时库
    for d in (db, db2):
        try:
            d.close()
        except Exception:
            pass

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    if FAIL:
        sys.exit(1)
    print("全部记忆系统自检通过 ✔")


if __name__ == "__main__":
    main()
