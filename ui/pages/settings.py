# -*- coding: utf-8 -*-
"""设置页：通用模型连接 + 日志开关 + 记忆开关 + 初始存款。

职责边界（bug6 拆分约定）：
    - 只负责设置项的输入与存储（widget 自动同步 session_state）。
    - 不参与编译流程；编译处（home.py）通过 st.session_state 读取这些配置。
    - widget key 与 v2.5 完全一致，保证 tests/test_app.py 可无头跑通。

安全说明：
    - API Key 只存当前 Streamlit 会话内存，不写文件、不写 localStorage、不放进 URL。
    - 「清除 API Key」按钮通过回调在 widget 重建前清空，避免 Session State 冲突。
    - 日志 / 记忆开关默认关闭，尊重隐私。
"""

from __future__ import annotations

import streamlit as st           # Web 框架本体


_API_WIDGET_KEY = "_cfg_api_key_widget"
_PROVIDER_WIDGET_KEY = "_cfg_api_provider_widget"
_BASE_WIDGET_KEY = "_cfg_api_base_widget"
_MODEL_WIDGET_KEY = "_cfg_api_model_widget"

_PROVIDER_PRESETS = {
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "自定义兼容接口": ("", ""),
    "本地模型": ("http://127.0.0.1:11434/v1", "qwen2.5:7b"),
}


def _prime_widget(widget_key: str, state_key: str, default) -> None:
    """把持久配置复制到临时 widget 键（只在该 widget 尚未创建时）。"""
    st.session_state.setdefault(state_key, default)
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state[state_key]


def _commit_widget(widget_key: str, state_key: str) -> None:
    """Widget 变化时写入独立业务键，避免切页后被 Streamlit 清理。"""
    st.session_state[state_key] = st.session_state.get(widget_key)


def _clear_api_key() -> None:
    """在 Streamlit widget 回调阶段清空 Key（此时允许修改对应状态）。"""
    st.session_state["cfg_api_key"] = ""
    st.session_state[_API_WIDGET_KEY] = ""
    st.session_state["api_connection_status"] = "missing"
    st.session_state["world_data"] = None


def _apply_provider_preset() -> None:
    """切换服务商时填入常用地址和模型；仍允许用户继续修改。"""
    provider = str(st.session_state.get(_PROVIDER_WIDGET_KEY) or "DeepSeek")
    st.session_state["cfg_api_provider"] = provider
    base_url, model = _PROVIDER_PRESETS.get(provider, ("", ""))
    if provider != "自定义兼容接口":
        st.session_state[_BASE_WIDGET_KEY] = base_url
        st.session_state[_MODEL_WIDGET_KEY] = model


def _save_api_key() -> None:
    """保存完整模型配置，并触发一次新的世界观请求完成连接验证。"""
    provider = str(st.session_state.get(_PROVIDER_WIDGET_KEY) or "DeepSeek")
    api_key = str(st.session_state.get(_API_WIDGET_KEY) or "").strip()
    base_url = str(st.session_state.get(_BASE_WIDGET_KEY) or "").strip()
    model = str(st.session_state.get(_MODEL_WIDGET_KEY) or "").strip()
    st.session_state["cfg_api_provider"] = provider
    st.session_state["cfg_api_key"] = api_key
    st.session_state["cfg_api_base"] = base_url
    st.session_state["cfg_api_model"] = model
    st.session_state["api_connection_status"] = "checking" if base_url and model else "missing"
    st.session_state["api_connection_error"] = ""
    st.session_state["world_data"] = None
    st.session_state["world_refresh_nonce"] = int(
        st.session_state.get("world_refresh_nonce") or 0
    ) + 1
    st.session_state["error"] = ""


def _render_model_settings() -> None:
    """模型设置：DeepSeek / OpenAI / 自定义 / 本地兼容服务共用一套配置。

    公开部署采用「每人填自己的 Key」策略：Key 默认留空，不预填任何环境变量 / 平台 Secret。
    注意：这里【不能】用 st.session_state.setdefault 预填与 widget key 相同的值——
    否则 Streamlit 会报「widget 既带默认值又从 Session State 设值」的冲突警告/异常。
    初始默认值全部交给 widget 的 value 参数，编译处再用 or 兜底。

    Key 仅保存在当前 Streamlit 会话内存；刷新导致会话重建时需要重新填写。
    """
    with st.expander(
        "模型连接 · 通用兼容接口",
        expanded=st.session_state.get("api_connection_status") != "verified",
    ):
        _prime_widget(_PROVIDER_WIDGET_KEY, "cfg_api_provider", "DeepSeek")
        provider = str(st.session_state.get("cfg_api_provider") or "DeepSeek")
        preset_base, preset_model = _PROVIDER_PRESETS.get(provider, ("", ""))
        if _BASE_WIDGET_KEY not in st.session_state:
            st.session_state[_BASE_WIDGET_KEY] = (
                st.session_state.get("cfg_api_base") or preset_base
            )
        if _MODEL_WIDGET_KEY not in st.session_state:
            st.session_state[_MODEL_WIDGET_KEY] = (
                st.session_state.get("cfg_api_model") or preset_model
            )
        _prime_widget(_API_WIDGET_KEY, "cfg_api_key", "")
        st.selectbox(
            "服务类型",
            list(_PROVIDER_PRESETS),
            key=_PROVIDER_WIDGET_KEY,
            help="选择预设会自动填入常用地址；自定义项适合兼容 OpenAI Chat Completions 的中转服务。",
            on_change=_apply_provider_preset,
        )
        _url_col, _model_col = st.columns([1.55, 1])
        with _url_col:
            st.text_input(
                "接口地址",
                key=_BASE_WIDGET_KEY,
                placeholder="https://example.com/v1",
                help="可填接口根地址，也可填完整的 /chat/completions 地址。远程接口必须使用 HTTPS。",
            )
        with _model_col:
            st.text_input(
                "模型名",
                key=_MODEL_WIDGET_KEY,
                placeholder="例如 deepseek-chat",
                help="填写服务商实际提供的模型 ID。",
            )
        st.text_input(
            "API Key", key=_API_WIDGET_KEY, type="password",
            help="远程服务通常必填；本机 localhost / 127.0.0.1 接口可以留空。",
        )
        # 使用 on_click 回调：直接在按钮分支修改已创建的 text_input key 会触发
        # StreamlitAPIException（widget 创建后不允许修改其 session_state）。
        with st.container(key="key_actions"):
            _k_save_col, _k_clear_col, _k_note_col = st.columns([1.25, 1, 2.1])
            with _k_save_col:
                st.button(
                    "保存并验证连接",
                    key="btn_save_api_key",
                    type="primary",
                    on_click=_save_api_key,
                )
            with _k_clear_col:
                st.button(
                    "清除密钥",
                    key="btn_clear_api_key",
                    on_click=_clear_api_key,
                )
            with _k_note_col:
                st.caption("主页、世界观、深度反思和 PDF 报告将统一使用这套配置。")

        if st.session_state.get("api_connection_status") == "failed":
            st.error(
                str(st.session_state.get("api_connection_error") or "连接失败，请检查接口地址、模型名和密钥。")
            )

        # 隐私说明（让用户明确知道 Key 存哪）
        st.markdown(
            '<div class="rc-privacy-note">'
            "⚠️ <b>关于 API Key 的安全说明</b><br>"
            "你的 API Key 只保存在<em>当前 Streamlit 会话内存</em>，"
            "<b>不会写入 localStorage、URL 或服务器文件</b>；调用时只发送给当前配置的模型服务。<br>"
            "如果担心 Key 泄露，可用完点击「清除 API Key」，或在生产环境改用平台的 "
            "Secrets 功能存储密钥（见下方提示）。<br>"
            "选择其他服务时，密钥和输入会发送到你填写的接口地址；请只使用可信服务。"
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "💡 部署时可用 AI_API_KEY、AI_API_BASE、AI_MODEL 三个 Secret；"
            "旧版 DEEPSEEK_API_KEY / DEEPSEEK_API_BASE / DEEPSEEK_MODEL 仍兼容。",
        )


def _render_logging_settings() -> None:
    """日志记录开关（v2.6，bug5）：默认关闭，用户主动开启才写日志。

    隐私设计：用户的输入内容（可能含情感 / 健康 / 财务隐私）默认不落盘。
    只有用户在这里主动打开开关，编译成功才会写入本地 JSONL 日志；
    关闭后不写入新日志（旧日志保留）。
    开关状态放 session_state（key="enable_logging"），home.py 写入日志前检查。
    """
    with st.expander("本地日志 · 默认关闭", expanded=False):
        widget_key = "_enable_logging_widget"
        _prime_widget(widget_key, "enable_logging", False)
        st.toggle(
            "启用本地日志记录",
            key=widget_key,
            help="用于生成日/周/月统计报告和 PDF 导出。开启后，你的输入内容将保存在本地日志文件中。",
            on_change=_commit_widget,
            args=(widget_key, "enable_logging"),
        )
        st.caption(
            "开启后，你的输入内容将保存在本地日志文件中（仅用于统计与报告导出）。"
            "关闭后，不记录任何内容，统计与 PDF 导出功能将不可用。",
        )


def _render_memory_settings() -> None:
    """记忆系统开关（v3.0 Phase 3，默认关闭，与日志开关同样尊重隐私）。

    开启后：
        - 编译前：Agent 从 SQLite 检索「用户档案 / 近期事件 / 长期偏好」，
          注入编译提示词（让 AI 记得用户是谁、最近在忙什么）。
        - 编译后：事件快照与标签偏好自动归档到会话隔离的本地 SQLite。
    关闭后：不读取也不写入任何记忆，编译行为与 v3.0 之前完全一致。
    说明：记忆只存本地，不发送给第三方；提示词里的记忆内容仍会发给大模型用于生成。
    """
    with st.expander("长期记忆 · 默认关闭", expanded=False):
        widget_key = "_enable_memory_widget"
        _prime_widget(widget_key, "enable_memory", False)
        st.toggle(
            "启用记忆",
            key=widget_key,
            help="开启后 Agent 会记住你的档案与近期事件，编译更连贯；数据存本地 SQLite。",
            on_change=_commit_widget,
            args=(widget_key, "enable_memory"),
        )
        st.caption(
            "开启后，Agent 会检索你的用户档案与近期事件来辅助编译（更连贯、更有个人特色），"
            "并在每次编译后把事件与标签偏好归档到会话隔离的本地 SQLite。"
            "关闭后不读取也不写入任何记忆。",
        )


def _render_emotion_settings() -> None:
    """情绪氛围只影响当前会话的视觉展示，默认开启且不落盘。"""
    with st.expander("情绪氛围 · 默认开启", expanded=False):
        widget_key = "_enable_emotion_effects_widget"
        _prime_widget(widget_key, "enable_emotion_effects", True)
        st.toggle(
            "启用情绪氛围效果",
            key=widget_key,
            help="编译后根据情绪显示克制的光点、细雨或呼吸光晕；不影响模型结果。",
            on_change=_commit_widget,
            args=(widget_key, "enable_emotion_effects"),
        )
        st.caption(
            "效果采用平衡强度，只出现在编译结果之后。手机端会自动减少粒子，"
            "系统开启“减少动态效果”时会停止动画。"
        )


def _render_advanced_settings() -> None:
    """可选的第二次 AI 深度审查；默认关闭以优先保证交互速度。"""
    with st.expander("高级质量检查 · 默认快速模式", expanded=False):
        widget_key = "_enable_ai_reflection_widget"
        _prime_widget(widget_key, "enable_ai_reflection", False)
        st.toggle(
            "启用 AI 深度反思",
            key=widget_key,
            help="开启后每次编译会额外请求一次当前所选模型做深度审查，因此等待时间和 API 消耗都会增加。",
            on_change=_commit_widget,
            args=(widget_key, "enable_ai_reflection"),
        )
        st.caption("关闭时仍会执行本地数值与空事件检查；推荐保持关闭，交互会明显更快。")


def _render_deposit_settings() -> None:
    """存款设置：把「钱包」变成真实存款余额。

    用户填写初始存款后，编译时作为「可变属性」初始值传入运行时；AI 识别到消费
    会自动从存款中扣减；低于预警线时标签墙显示「⚠️ 存款不足」。
    所有 AI 世界观下都生效：面板上的货币名跟随世界观变化（金币 / 杏仁水 / 比特币）。
    """
    with st.expander("初始资产 · 可选", expanded=False):
        st.caption("存款作为当前世界货币的初始余额（如「金币 3500」）；AI 识别到消费会自动扣减。")
        col_dep, col_war = st.columns(2)
        with col_dep:
            deposit_widget = "_cfg_deposit_widget"
            _prime_widget(deposit_widget, "cfg_deposit", 0)
            st.number_input(
                "初始存款（元）", key=deposit_widget, min_value=0,
                step=100, format="%d",
                help="你的当前存款余额；例如填 5000 后，输入「吃饭花了35元」会自动扣到 4965。",
                on_change=_commit_widget,
                args=(deposit_widget, "cfg_deposit"),
            )
        with col_war:
            warning_widget = "_cfg_deposit_warn_widget"
            _prime_widget(warning_widget, "cfg_deposit_warn", 500)
            st.number_input(
                "存款预警线（元）", key=warning_widget, min_value=0,
                step=100, format="%d",
                help="存款低于此值时，标签墙显示「⚠️ 存款不足」。",
                on_change=_commit_widget,
                args=(warning_widget, "cfg_deposit_warn"),
            )


def render() -> None:
    """设置页入口：编排设置项区块（app.py 路由调用）。"""
    from ui import render
    st.markdown(
        render.page_intro_html(
            "⚙",
            "控制台设置",
            "管理模型连接、隐私记录和每次编译使用的初始资产。",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        render.settings_status_html(
            str(st.session_state.get("api_connection_status") or "missing"),
            bool(st.session_state.get("enable_logging", False)),
            bool(st.session_state.get("enable_memory", False)),
            bool(st.session_state.get("enable_emotion_effects", True)),
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        render.label_html("连接与隐私", "所有敏感功能默认关闭"),
        unsafe_allow_html=True,
    )
    _render_model_settings()
    _render_logging_settings()
    _render_memory_settings()
    _render_emotion_settings()
    _render_advanced_settings()
    st.markdown(render.label_html("运行时参数", "可选"), unsafe_allow_html=True)
    _render_deposit_settings()
