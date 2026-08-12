# -*- coding: utf-8 -*-
"""主页：核心交互区（输入 → 编译 → 结算 → 展示）（v2.6，由 app.py 拆分而来）。

职责边界（bug6 拆分约定）：
    - 本模块只编排「主页」的页面顺序与交互，业务规则全部下沉到 core/。
    - 依赖 app.py 入口已完成初始化：
        st.session_state["world"]      今日 WorldProfile（跨页面共享）
        st.session_state["INPUT_KEY"]  当前输入框 key（nonce 版本号已算好）
    - widget key 与 v2.5 完全一致，保证 tests/test_app.py 可无头跑通。
"""

from __future__ import annotations

import datetime                 # 「今日世界」展示日期
import time                      # 记录真实编译耗时
from html import escape
from pathlib import Path

import streamlit as st           # Web 框架本体

from core.runtime import simulate_runtime, RuntimeState   # 运行时入口
from core.content_provider import fetch_daily_event   # 今日冒险
from core.agent import RealityAgent              # v3.0 Agent 化：编排编译生命周期
from core.memory import LongTermMemory, MemoryRetriever   # v3.0 Phase 3 记忆系统
from core.database import Database
from core.simulation import SimulationEngine     # v3.0 Phase 4 世界模拟引擎
from core.world_config import world_from_ai
from core import logger                          # 本地 JSONL 日志

# 默认 Agent 不创建数据库；记忆关闭时做到真正的「不读、不写、不建库」。
_AGENT = RealityAgent(simulation_engine=SimulationEngine())


def _agent_and_memory() -> tuple[RealityAgent, LongTermMemory | None]:
    """返回当前会话的 Agent / 记忆库；记忆默认关闭并完全惰性创建。

    托管部署可能同时服务多个访客，因此每个 Streamlit 会话使用独立 SQLite 文件，
    避免模块级全局数据库导致访客之间互相读到记忆。
    """
    if not st.session_state.get("enable_memory", False):
        return _AGENT, None

    memory = st.session_state.get("_memory_resource")
    agent = st.session_state.get("_memory_agent")
    if memory is None or agent is None:
        root = Path(__file__).resolve().parents[2]
        memory_id = str(st.session_state.get("memory_id") or "session")
        db_path = root / "data" / f"reality_{memory_id}.db"
        memory = LongTermMemory(Database(db_path))
        agent = RealityAgent(
            retriever=MemoryRetriever(long_term=memory),
            simulation_engine=SimulationEngine(),
        )
        st.session_state["_memory_resource"] = memory
        st.session_state["_memory_agent"] = agent
    return agent, memory


def _boot_html(lines: list[str]) -> str:
    """把「编译启动」的逐行日志拼成一个迷你终端块（动画占位符用）。

    样式内联，不依赖 terminal.css，方便复用且不会改到现有皮肤。
    """
    body = "".join(f'<div class="rc-boot-line">{escape(ln)}</div>' for ln in lines)
    return (
        '<div class="rc-boot" style="'
        'background:#05070a;border:1px solid #1c2a22;border-radius:2px;'
        'padding:.6rem .8rem;margin:.4rem 0;min-height:1.2rem;'
        'font-family:JetBrains Mono,Consolas,monospace;font-size:.82rem;'
        'color:#7fe08a;line-height:1.6;letter-spacing:.2px">'
        + body
        + "</div>"
    )


def _render_header_and_world() -> None:
    """今日世界观主卡（全站品牌标题由 app.py 统一渲染）。"""
    from ui import render
    world = st.session_state["world"]
    _today_disp = datetime.date.today().strftime("%Y-%m-%d")
    st.markdown(
        render.world_card_html(
            world,
            _today_disp,
            st.session_state.get("api_connection_status") == "verified",
        ),
        unsafe_allow_html=True,
    )


def _render_action_buttons() -> None:
    """生成今日冒险 / 刷新世界观 两个快捷动作。"""
    from ui import render  # noqa: F401  保持 import 集中在函数内，避免顶层导入 ui 包循环
    INPUT_KEY = st.session_state["INPUT_KEY"]

    with st.container(key="world_actions"):
        _col_act1, _col_act2 = st.columns(2)
        with _col_act1:
            if st.button("✦ 生成今日冒险", key="btn_daily"):
                # 优先取 AI 世界观自带的 daily_story（200-300 字）；为空则临时调 AI 生成
                world_data = st.session_state.get("world_data")
                daily = fetch_daily_event(
                    world_data,
                    api_key=st.session_state.get("cfg_api_key"),
                    base_url=st.session_state.get("cfg_api_base"),
                    model=st.session_state.get("cfg_api_model"),
                )
                st.session_state[INPUT_KEY] = daily
                st.session_state["error"] = ""
                st.session_state.update(result=None, log=None, reflection=None, simulation=None)
                st.session_state["auto_run"] = True     # 标记自动编译，进入 section 6 时触发
                st.rerun()

        with _col_act2:
            # v2.5 「刷新世界观」：手动强制重新生成今日世界观（清空旧编译结果）
            if st.button("↻ 刷新世界观", key="btn_refresh_world"):
                st.session_state["world_refresh_nonce"] = int(
                    st.session_state.get("world_refresh_nonce") or 0
                ) + 1
                st.session_state["world_data"] = None   # 置空，app.py 3.5 节会自动重新生成
                st.session_state["api_connection_status"] = (
                    "checking"
                    if st.session_state.get("cfg_api_key") or st.session_state.get("cfg_api_base")
                    else "missing"
                )
                st.session_state["result"] = None       # 世界观已变，旧面板货币不匹配，清空
                st.session_state["log"] = None
                st.session_state["reflection"] = None
                st.session_state["simulation"] = None
                st.session_state["sim_state"] = None
                st.session_state["error"] = ""
                st.rerun()


def _render_input_area() -> tuple[str, bool]:
    """输入区（快捷样本 + 主输入框 + 操作行）。

    返回：(当前输入文本, 执行编译按钮是否被点击)
    """
    from ui import render
    INPUT_KEY = st.session_state["INPUT_KEY"]

    st.markdown(
        render.label_html("01 · 输入现实", "越具体，AI 编译与数值结算越准确"),
        unsafe_allow_html=True,
    )

    # 5.1 快捷样本：点一下直接填进输入框，降低「不知道写什么」的门槛
    SAMPLES: list[tuple[str, str]] = [
        ("加班到凌晨", "今天加班到凌晨一点，中间靠两杯美式续命，回家路上还赶上下雨"),
        ("健康作息", "早起跑了五公里，中午和同事吃了顿好的，下午学习两小时，十一点睡觉"),
        ("事故日", "上午连开三个会，下午线上出事故排查到七点，晚上还被骂了一顿"),
        ("周末独处", "一个人去海边散步，回来打了两局游戏，点了杯奶茶，十点就躺下了"),
    ]
    with st.container(key="sample_prompts"):
        sample_cols = st.columns(len(SAMPLES))
        for col, (label, text) in zip(sample_cols, SAMPLES):
            with col:
                # 按钮在输入框「之前」渲染，所以可以安全地修改输入框的 session_state
                if st.button(label, key=f"sample_{label}"):
                    st.session_state[INPUT_KEY] = text
                    st.session_state["error"] = ""
                    # 铁律 3：样本只是「换输入」，不触发编译、不清空旧面板。

    # 5.2 主输入框
    st.text_area(
        label="现实日常输入",
        key=INPUT_KEY,
        height=150,
        placeholder="例如：今天完成了什么、花了多久、身体和情绪感觉如何……",
        label_visibility="collapsed",
    )
    current_text: str = st.session_state.get(INPUT_KEY, "")

    # 5.3 操作行：执行编译 / 清空 / 字数统计
    with st.container(key="compile_actions"):
        col_run, col_clear, col_meta = st.columns([1.35, 0.75, 2.2])
        with col_run:
            run_clicked = st.button("▶ 开始编译", type="primary", key="btn_run")
        with col_clear:
            if st.button("清空", key="btn_clear"):
                st.session_state["nonce"] += 1
                st.session_state.update(
                    result=None, log=None, reflection=None, simulation=None, error="",
                    emotion_override_choice="自动",
                )
                st.rerun()
        with col_meta:
            st.markdown(
                '<div class="rc-input-meta">'
                f'<span>{len(current_text)} 字</span><span>Ctrl + Enter 快速提交</span>'
                '</div>',
                unsafe_allow_html=True,
            )
    return current_text, run_clicked


def _run_compile(current_text: str, run_clicked: bool) -> None:
    """执行编译：AI 编译 → 运行时结算 → 装饰动画 → 写入日志。"""
    world = st.session_state["world"]

    auto_run = st.session_state.pop("auto_run", False)
    if not (run_clicked or auto_run):
        return

    if not current_text.strip():
        # 空输入：给内联错误提示，不做弹窗，也不清掉已有结果
        st.session_state["error"] = "输入为空。编译器至少需要一句现实日常。"
        return

    st.session_state["error"] = ""
    reflection = None
    simulation = None
    try:
        # v3.0 Agent 化：走 Agent 完整生命周期（Planner → LLM → Validator → Runtime → Reflection）。
        # Agent 内部复用 core.llm_client（含 schema 安全门 + 格式重试 + 兜底），
        # 产出 CompileResult 类型与旧 compile_reality 完全一致。
        # v3.0 Phase 4：Agent 内部还会跑世界模拟（事件→状态→规则→衍生事件）。
        agent, memory = _agent_and_memory()
        with st.status("正在连接现实编译器…", expanded=False) as compile_status:
            started_at = time.perf_counter()
            run_result = agent.run(
                current_text,
                world,
                api_key=st.session_state.get("cfg_api_key"),
                base_url=st.session_state.get("cfg_api_base"),
                model=st.session_state.get("cfg_api_model"),
                memory=memory,
                simulation_state=st.session_state.get("sim_state"),
                enable_reflection=bool(st.session_state.get("enable_ai_reflection", False)),
                enable_local_reflection=True,
            )
            compile_status.update(
                label=f"编译完成 · {time.perf_counter() - started_at:.1f}s",
                state="complete",
                expanded=False,
            )
        result = run_result.compile
        reflection = run_result.reflection
        simulation = run_result.simulation
        # 存款模式：用户设置了初始存款即启用（所有世界观下货币都扣减存款）
        deposit = int(st.session_state.get("cfg_deposit") or 0)
        warn_line = int(st.session_state.get("cfg_deposit_warn") or 0)
        deposit_on = deposit > 0
        st.session_state["deposit_on"] = deposit_on
        st.session_state["deposit_initial"] = deposit if deposit_on else None
        log = simulate_runtime(
            result.matched,
            world,
            initial_vstat=deposit if deposit_on else None,
            warn_threshold=warn_line if deposit_on else None,
        )
    except Exception as exc:
        # 仅展示错误，绝不覆盖 result/log，旧属性面板继续显示
        st.session_state["error"] = str(exc) or "编译失败，请稍后重试。"
        return

    # 保存反思结论 + 世界演化结论（供输出区展示「AI 自我反思」「🌍 世界演化」面板）
    st.session_state["reflection"] = reflection
    st.session_state["simulation"] = simulation
    if simulation is not None and simulation.final_state is not None:
        st.session_state["sim_state"] = simulation.final_state

    st.session_state["result"] = result
    st.session_state["log"] = log
    st.session_state["emotion_override_choice"] = "自动"

    # v2.3 日志系统：编译成功即写入 JSONL 日志；写入失败绝不影响编译主流程。
    # v2.6（bug5）：是否写盘由设置页「启用本地日志记录」开关控制，默认关闭。
    # 隐私设计：用户输入内容默认不落盘，只有主动开启日志记录才写入本地 JSONL。
    if st.session_state.get("enable_logging", False):
        try:
            logger.append_log(
                logger.build_entry(result, log, world, current_text),
                namespace=str(st.session_state.get("memory_id") or "session"),
            )
        except Exception:
            pass


def _render_output_area() -> None:
    """输出区：伪代码 / 终端 / 属性面板 / 复盘 / 标签墙 / 导出运行日志。"""
    from ui import render
    world = st.session_state["world"]

    # 7.1 错误优先展示
    if st.session_state["error"]:
        st.markdown(render.error_html(st.session_state["error"]), unsafe_allow_html=True)

    result = st.session_state["result"]
    log = st.session_state["log"]

    # 铁律 1：属性结算面板 / 标签墙的渲染强绑定 session_state['log']。
    if log is None:
        # 7.2 空状态（Idle）：从没编译过，或已清空
        st.markdown(render.label_html("02 · 编译结果", "等待现实输入"), unsafe_allow_html=True)
        snap = st.session_state.get("last_snapshot") or {}
        snap_stats = snap.get("stats") if isinstance(snap, dict) else None
        snap_world_data = snap.get("world") if isinstance(snap, dict) else None
        if isinstance(snap_stats, dict) and isinstance(snap_world_data, dict):
            restored_world = world_from_ai(snap_world_data, "restored-snapshot")
            restored_state = RuntimeState(
                hp=int(snap_stats.get("hp", 0)),
                mp=int(snap_stats.get("mp", 0)),
                vstat=int(snap_stats.get("gold", 0)),
                exp=int(snap_stats.get("exp", 0)),
                level=int(snap_stats.get("level", 1)),
            )
            st.markdown(
                render.label_html("上次保存的属性快照", "仅供查看，下一次编译会重新结算"),
                unsafe_allow_html=True,
            )
            st.markdown(render.stats_html(restored_state, restored_world), unsafe_allow_html=True)
        st.markdown(render.idle_html(), unsafe_allow_html=True)
        return

    # 世界观当天恒定，渲染直接使用当前世界对象
    display_world = world
    deposit_initial = st.session_state.get("deposit_initial")

    st.markdown(
        render.label_html("02 · 编译结果", f"BUILD {result.build_id}"),
        unsafe_allow_html=True,
    )

    # 情绪氛围与手动校准：校准值仅影响本次展示，不修改 CompileResult / 日志 / 记忆。
    mood_options = ["自动", "joyful", "calm", "sad", "anxious", "angry", "mixed"]
    if st.session_state.get("emotion_override_choice") not in mood_options:
        st.session_state["emotion_override_choice"] = "自动"
    choice = str(st.session_state.get("emotion_override_choice") or "自动")
    override = None if choice == "自动" else choice
    if st.session_state.get("enable_emotion_effects", True):
        st.markdown(
            render.mood_ambience_html(result.emotion, override),
            unsafe_allow_html=True,
        )
    st.markdown(
        render.emotion_card_html(result.emotion, override),
        unsafe_allow_html=True,
    )
    st.radio(
        "情绪判定不准确？仅校准当前氛围",
        mood_options,
        key="emotion_override_choice",
        format_func=lambda value: {
            "自动": "自动",
            "joyful": "开心",
            "calm": "平静",
            "sad": "难过",
            "anxious": "焦虑",
            "angry": "生气",
            "mixed": "复杂",
        }[value],
        horizontal=True,
    )

    st.markdown(render.label_html("事件叙事", f"{len(result.matched)} 个现实切片"), unsafe_allow_html=True)
    st.markdown(render.event_cards_html(result, display_world), unsafe_allow_html=True)

    # 7.3 先展示最重要的结算结果；技术细节下沉到折叠区，减少首屏滚动。
    st.markdown(render.stats_html(log.state, display_world), unsafe_allow_html=True)

    # 7.6b 今日复盘（v2.1）
    if result.summary or result.advice:
        st.markdown(render.label_html("今日复盘", "AI SUMMARY"), unsafe_allow_html=True)
        st.markdown(render.replay_html(result.summary, result.advice), unsafe_allow_html=True)

    # 7.6c AI 自我反思（v3.0 Agent 化：Reflection 结论）
    _refl = st.session_state.get("reflection")
    if _refl is not None:
        st.markdown(render.label_html("AI 自我反思", "QUALITY CHECK"), unsafe_allow_html=True)
        st.markdown(
            render.reflection_html(
                _refl.reasonable, _refl.source, _refl.issues, _refl.suggestion,
            ),
            unsafe_allow_html=True,
        )

    # 7.6d 世界演化（v3.0 Phase 4：Simulation 结论）
    _sim = st.session_state.get("simulation")
    if _sim is not None and _sim.evolved:
        st.markdown(render.label_html("世界演化", "SIMULATION STATE"), unsafe_allow_html=True)
        st.markdown(
            render.simulation_html(
                _sim.trajectory,
                _sim.triggered_rules,
                _sim.derived_events,
                _sim.final_state.to_dict() if _sim.final_state else {},
            ),
            unsafe_allow_html=True,
        )

    # 7.7 buff / debuff 标签墙
    st.markdown(render.chips_html(log.chips, display_world), unsafe_allow_html=True)

    # 7.8 技术细节默认折叠：保留可解释性，又不让结果页被长日志占满。
    st.markdown(render.label_html("技术细节", "可选查看"), unsafe_allow_html=True)
    with st.expander("生成的伪代码", expanded=False):
        st.code(result.code, language="python")
        if result.warnings:
            st.markdown(render.warnings_html(result.warnings), unsafe_allow_html=True)

    with st.expander("运行时 · 终端日志", expanded=False, key="exp_terminal"):
        st.markdown(render.terminal_html(log.lines), unsafe_allow_html=True)

    with st.expander("属性计算过程", expanded=False):
        st.markdown(render.calc_html(log, display_world, deposit_initial), unsafe_allow_html=True)

    # 7.7 导出运行日志（纯文本）
    export_text = "\n".join(log.lines)
    st.download_button(
        label="↓ 导出运行日志",
        data=export_text.encode("utf-8"),
        file_name=f"reality_{result.build_id}.log",
        mime="text/plain",
        key="btn_download",
    )

    # 运算规则 / 设定说明：放底部、默认折叠，不干扰编译主流程
    with st.expander("运算规则 · 设定说明", expanded=False):
        st.markdown(render.rules_html(), unsafe_allow_html=True)


def render() -> None:
    """主页入口：按顺序编排全部区块（app.py 路由调用）。"""
    _render_header_and_world()      # 标题区 + 今日世界观
    _render_action_buttons()        # 生成今日冒险 / 刷新世界观
    current_text, run_clicked = _render_input_area()   # 输入区
    _run_compile(current_text, run_clicked)            # 执行编译（含动画）
    _render_output_area()           # 输出区
