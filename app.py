# -*- coding: utf-8 -*-
"""Reality Compiler v3.2 —— 把「现实日常」编译成「伪代码」并模拟运行的 Web Agent。

启动方式：
    pip install -r requirements.txt
    streamlit run app.py

分层结构（改代码时先看这里）：
    core/   业务引擎：AI 编译（DeepSeek API）-> 运行时结算，纯 Python，不依赖 Streamlit
    core/agent/       Agent 层（v3.0 Phase 2）：Planner -> LLM -> Validator -> Runtime -> Reflection
    core/database/    存储层（v3.0 Phase 3）：SQLite（用户档案 / 历史事件 / 长期偏好）
    core/memory/      记忆系统（v3.0 Phase 3）：short/long term + retriever
    core/simulation/  世界模拟（v3.0 Phase 4）：事件 -> 状态 -> 规则 -> 衍生事件
    ui/     渲染层：把结果拼成 HTML 字符串，纯函数
    ui/pages/  页面层：主页 / 设置页 / 报告页的页面编排（v2.6 由 app.py 拆分）
    app.py  本文件：入口 + 路由 + CSS 注入 + session_state 初始化 + 每日世界观状态机
"""

from __future__ import annotations

import datetime                 # 获取当前系统日期，用于「每日世界观」确定性轮换
import hashlib                  # API Key 只取不可逆指纹参与缓存键，绝不把原文写入缓存
import os                       # 读取可选的平台 Secret，只用于计算有效配置指纹
import sys                       # 用来把项目根目录塞进模块搜索路径
import uuid                      # 生成一次会话的随机 id
from pathlib import Path         # 处理文件路径，比字符串拼接更安全
from urllib.parse import urlsplit  # 判断本地兼容接口是否允许无 Key 运行

import streamlit as st           # Web 框架本体

# --- 让脚本无论在哪个目录下启动都能 import 到 core / ui ---------------------
APP_DIR = Path(__file__).resolve().parent      # 当前文件所在目录 = 项目根目录
if str(APP_DIR) not in sys.path:               # 避免重复插入
    sys.path.insert(0, str(APP_DIR))

from core.world_config import world_from_ai, FALLBACK_WORLD   # noqa: E402  AI 世界观转换 / 兜底
from core.content_provider import today_world_id   # noqa: E402  今日世界观 id
from core import storage as storage_lib            # noqa: E402  localStorage 数据层（bug4）
from ui import render                            # noqa: E402  HTML 渲染函数集合


# ============================================================================
# 1. 页面级配置（必须是第一个 Streamlit 调用）
# ============================================================================
st.set_page_config(
    page_title="Reality Compiler v3.2",   # 浏览器标签页标题
    page_icon="◈",                        # 标签页图标，与世界观主卡保持一致
    layout="wide",                        # CSS 再限制正文宽度，兼顾桌面与移动端
    initial_sidebar_state="collapsed",   # 移动端不再被侧栏遮挡；导航已移到页面顶部
)


# ============================================================================
# 2. 注入自定义样式
# ============================================================================
CSS_PATH = APP_DIR / "assets" / "terminal.css"   # 样式文件路径


@st.cache_data(show_spinner=False)               # 缓存读取结果，避免每次交互都读磁盘
def load_css(path_str: str, mtime: float) -> str:
    """读取 CSS 文件内容。

    参数里带上 mtime（文件修改时间）是个小技巧：
    文件一改动，mtime 变化 -> 缓存自动失效 -> 开发时改样式能立刻看到效果。
    """
    return Path(path_str).read_text(encoding="utf-8")


@st.cache_data(ttl=86400, show_spinner=False)    # v2.6 世界观按天缓存（bug7）
def generate_world_cached(
    today_str: str,
    key_fingerprint: str,
    refresh_nonce: int,
    _api_key: str | None,
    _base_url: str | None,
    _model: str | None,
) -> dict:
    """生成今日世界观，按「日期 + 完整模型配置 + 手动刷新次数」缓存 24 小时。

    同一天内多次刷新页面 -> 命中缓存，不再重复调用 DeepSeek API（省钱、提速）；
    跨天（today_str 变化）或换了 Key -> 缓存自动失效，重新生成。
    放在 app.py（流程层）而非 core：遵守 Agent.md 铁律「core 层禁止 import streamlit」。
    """
    from core.content_provider import fetch_world   # 延迟 import，避免模块顶部耦合
    return fetch_world(
        api_key=_api_key or None,
        base_url=_base_url or None,
        model=_model or None,
    )


# 把 CSS 包进 <style> 标签注入页面
st.markdown(
    f"<style>{load_css(str(CSS_PATH), CSS_PATH.stat().st_mtime)}</style>",
    unsafe_allow_html=True,
)


# ============================================================================
# 3. 会话状态初始化
# ============================================================================
# Streamlit 每次交互都会从头执行整个脚本，
# 所以「编译结果」这类需要跨交互保留的数据必须放进 st.session_state。
DEFAULT_STATE = {
    "result": None,     # CompileResult：最近一次编译产物
    "log": None,        # RuntimeLog：最近一次运行时产物
    "reflection": None, # ReflectionResult：最近一次 AI 自我反思结论（v3.0 Agent 化）
    "simulation": None, # SimulationResult：最近一次世界演化结论（v3.0 Phase 4）
    "error": "",        # 错误提示文案，空字符串表示没有错误
    "nonce": 0,         # 输入框的版本号，用于实现「清空」
    "sid": uuid.uuid4().hex[:6],   # 本次会话 id，只在标题栏展示
    "world_id": None,  # 当前世界观 id（由日期生成，如 "day-2026-08-03"）
    "world_data": None,  # 当前世界观 dict（AI 生成，跨天才刷新）
    "world_key_fingerprint": None,  # 生成当前世界观时使用的有效 Key 指纹
    "world_refresh_nonce": 0,  # 手动刷新递增；确保真正绕过同日缓存
    "api_connection_status": "missing",  # missing / checking / verified / failed
    "last_world_date": None,  # 上次处理时的系统日期；跨天则触发硬重置（重新生成世界观 + 清空旧数据）
    "auto_run": False,  # 「生成今日冒险」后触发的自动编译标记
    "sim_state": None,  # 跨编译累积的隐藏世界状态；跨天时清空
    "memory_id": uuid.uuid4().hex,  # 会话隔离的记忆库 id（不直接展示）
    # 设置值使用非 widget 业务键保存；否则切离设置页后 Streamlit 会清理未渲染 widget 的状态。
    "cfg_api_provider": "DeepSeek",
    "cfg_api_key": "",
    "cfg_api_base": "",
    "cfg_api_model": "",
    "enable_logging": False,
    "enable_memory": False,
    "enable_ai_reflection": False,
    "enable_emotion_effects": True,
    "emotion_override_choice": "自动",
    "cfg_deposit": 0,
    "cfg_deposit_warn": 500,
}
for key, value in DEFAULT_STATE.items():
    st.session_state.setdefault(key, value)   # setdefault：不存在才写入，已有值不覆盖

# --- 模型设置（API 接入）初始值 ---
# 公开发布采用「每人填自己的 Key」策略：Key 默认留空，不预填任何环境变量 / 平台 Secret。
# 设置页使用 `_cfg_*_widget` 临时键，业务逻辑只读上面的持久配置键；
# 这样页面切换导致 widget 清理时，实际配置仍保留在当前会话内存。

INPUT_KEY = f"reality_input_{st.session_state['nonce']}"   # 当前输入框的 key
st.session_state["INPUT_KEY"] = INPUT_KEY                  # 供 ui/pages/* 读取，避免重复计算


# ============================================================================
# 3.5 每日世界观（AI 动态生成）+ 跨天硬重置（核心状态机）
# ============================================================================
# 世界观由 DeepSeek AI 按日期实时生成（见 core.content_provider.fetch_world）：
#   每天首次打开页面 -> 调用 AI 生成全新世界观（名称/背景/货币名都不同）；
#   同一天刷新页面 -> 复用 session_state 里的世界观，不重复调用；
#   跨天 -> 硬重置（清空旧数据 + 重新生成世界观）。
# AI 不可用（缺 Key / 网络异常）时回退到内置兜底世界，页面永远可用。
_today_str = datetime.date.today().isoformat()
today_wid = today_world_id()
_session_api_key = str(st.session_state.get("cfg_api_key") or "").strip()
_session_api_base = str(st.session_state.get("cfg_api_base") or "").strip()
_session_api_model = str(st.session_state.get("cfg_api_model") or "").strip()
_effective_api_key = (
    _session_api_key
    or str(os.getenv("AI_API_KEY") or "").strip()
    or str(os.getenv("DEEPSEEK_API_KEY") or "").strip()
)
_effective_api_base = (
    _session_api_base
    or str(os.getenv("AI_API_BASE") or "").strip()
    or str(os.getenv("DEEPSEEK_API_BASE") or "").strip()
    or "https://api.deepseek.com/chat/completions"
)
_effective_api_model = (
    _session_api_model
    or str(os.getenv("AI_MODEL") or "").strip()
    or str(os.getenv("DEEPSEEK_MODEL") or "").strip()
    or "deepseek-chat"
)
_api_hostname = urlsplit(_effective_api_base).hostname
_connection_configured = bool(_effective_api_key) or _api_hostname in {
    "localhost", "127.0.0.1", "::1",
}
_key_fingerprint = (
    hashlib.sha256(
        "\0".join((_effective_api_key, _effective_api_base, _effective_api_model)).encode("utf-8")
    ).hexdigest()[:16]
    if _connection_configured else "none"
)

# Key 在设置页修改后，必须立即废弃此前由“无 Key / 旧 Key”生成的世界观。
# 旧逻辑只检查 world_data 是否为空，因此会永久沿用首次打开时的兜底世界。
if st.session_state.get("world_key_fingerprint") != _key_fingerprint:
    st.session_state["world_key_fingerprint"] = _key_fingerprint
    st.session_state["world_data"] = None
    st.session_state["result"] = None
    st.session_state["log"] = None
    st.session_state["reflection"] = None
    st.session_state["simulation"] = None
    st.session_state["sim_state"] = None
    st.session_state["emotion_override_choice"] = "自动"
    st.session_state["error"] = ""
    st.session_state["api_connection_status"] = (
        "checking" if _connection_configured else "missing"
    )

if st.session_state.get("last_world_date") != _today_str:
    st.session_state[INPUT_KEY] = ""      # 清空输入框
    st.session_state["result"] = None     # 清空编译结果
    st.session_state["log"] = None
    st.session_state["reflection"] = None
    st.session_state["simulation"] = None
    st.session_state["sim_state"] = None
    st.session_state["emotion_override_choice"] = "自动"
    st.session_state["error"] = ""        # 清空错误提示
    st.session_state["world_data"] = None  # 置空，触发下方重新生成世界观
    st.session_state["last_world_date"] = _today_str

# 当天尚未生成世界观（首次打开 / 跨天）：调用 AI 生成（失败自动回退兜底世界）
# v2.6：走 @st.cache_data 按天缓存，同一天刷新页面不重复调 API（bug7）。
if not st.session_state.get("world_data"):
    st.session_state["world_data"] = generate_world_cached(
        _today_str,
        _key_fingerprint,
        int(st.session_state.get("world_refresh_nonce") or 0),
        _session_api_key or None,
        _session_api_base or None,
        _session_api_model or None,
    )
world_data = st.session_state["world_data"]          # 今日世界观 dict（AI 生成）
if _connection_configured:
    st.session_state["api_connection_status"] = (
        "verified" if world_data.get("_source") == "ai" else "failed"
    )
    st.session_state["api_connection_error"] = str(world_data.get("_error") or "")
else:
    st.session_state["api_connection_status"] = "missing"
    st.session_state["api_connection_error"] = ""
world = world_from_ai(world_data, today_wid)         # 转成 WorldProfile，编译/渲染都基于它
st.session_state["world"] = world                    # 供 ui/pages/* 复用，避免重复计算


# ============================================================================
# 3.6 localStorage 持久化（v2.6，bug4）
# ============================================================================
# Streamlit 是服务端渲染，Python 无法直接访问浏览器 localStorage。桥接方式：
#   保存：st.markdown(unsafe_allow_html=True) 里的 <script> 在父页面 DOM 中执行
#        （非 components.html 的沙箱 iframe），可直接 localStorage.setItem；
#   恢复：首屏 script 检测到 localStorage 有快照时，用 URL 参数 ?rc=... 带回，
#        Python 端读取 st.query_params 解码后写回 session_state，随即清掉参数。
# 快照只含「世界观摘要 + 最近属性面板」（数据量小，URL 无压力）；日志本身走
# 服务端 JSONL（见 core/logger.py），不重复塞进 localStorage。
import json as _json_module  # noqa: E402  仅本桥接使用

_STORAGE_RESTORED_FLAG = "_storage_restored_v26"


def _persist_storage_snapshot() -> None:
    """把「世界观摘要 + 最近属性面板」写入浏览器 localStorage。

    只有编译出结果后才写；失败静默（localStorage 被禁 / 存储满都无碍）。
    """
    world = st.session_state.get("world")
    log = st.session_state.get("log")
    if world is None or log is None:
        return
    stats = None
    if log.state is not None:
        stats = {
            "hp": log.state.hp,
            "mp": log.state.mp,
            "vstat": log.state.vstat,
            "exp": log.state.exp,
            "level": log.state.level,
        }
    snap = storage_lib.build_snapshot(world, stats, [])
    payload = _json_module.dumps(storage_lib.serialize(snap), ensure_ascii=False)
    # 父页面 script 直写 localStorage（可访问），失败静默
    st.markdown(
        f"<script>"
        f"try{{localStorage.setItem('{storage_lib.STORAGE_KEY}',{payload});}}catch(e){{}}"
        f"</script>",
        unsafe_allow_html=True,
    )


def _try_restore_from_storage() -> None:
    """首屏尝试从 localStorage 恢复上次会话的「世界观摘要 + 属性面板」。

    一次会话只尝试一次（flag 防重复）；script 会把快照经 ?rc= 参数带回，
    该机制在 AppTest 无头环境不触发（无浏览器），安全降级为零数据。
    """
    if st.session_state.get(_STORAGE_RESTORED_FLAG):
        return
    st.session_state[_STORAGE_RESTORED_FLAG] = True

    rc = st.query_params.get("rc")
    if rc:
        # 第二次进入（带参）：解码快照并写回 session_state，随后清掉参数
        try:
            snap = storage_lib.deserialize(rc)
            if snap:
                st.session_state["last_snapshot"] = snap
        except Exception:
            pass
        st.query_params.clear()
        return

    # 首次进入：让父页面 script 检查 localStorage，有数据就带参重载
    st.markdown(
        "<script>"
        f"try{{var d=localStorage.getItem('{storage_lib.STORAGE_KEY}');"
        "if(d&&!location.search.includes('rc=')){"
        "location.replace(location.pathname+'?rc='+encodeURIComponent(d));"
        "}}catch(e){}"
        "</script>",
        unsafe_allow_html=True,
    )


_try_restore_from_storage()   # 首屏恢复（放在世界观状态机之后，保证 world 已就绪）


# ============================================================================
# 4. 页面路由（bug6 拆分：app.py 只保留入口 + 路由）
# ============================================================================
# 顶部品牌区与三段式导航不依赖浏览器 URL，桌面/移动端共用且 AppTest 可测。
# 页面模块见 ui/pages/{home,settings,report}.py。
PAGES = ["🏠 主页", "⚙️ 设置", "📊 报告"]
st.markdown(
    render.header_html(str(st.session_state.get("sid") or "")),
    unsafe_allow_html=True,
)
with st.container(key="top_navigation"):
    page = st.radio(
        "页面",
        PAGES,
        key="nav_page",
        horizontal=True,
        label_visibility="collapsed",
    )

if page == PAGES[0]:
    from ui.pages import home as home_page
    home_page.render()
elif page == PAGES[1]:
    from ui.pages import settings as settings_page
    settings_page.render()
else:
    from ui.pages import report as report_page
    report_page.render()

# 数据变化后同步写入 localStorage（bug4）：编译成功 / 世界观刷新后都会触发
_persist_storage_snapshot()

# ============================================================================
# 8. 页脚（所有页面共享）
# ============================================================================
st.markdown(render.footer_html(), unsafe_allow_html=True)
