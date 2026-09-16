# -*- coding: utf-8 -*-
"""HTML 渲染层：把编译结果拼成一段段 HTML，交给 st.markdown(unsafe_allow_html=True)。

重要约定：
    所有返回的 HTML **必须是单行字符串**（不能有换行和缩进）。
    因为 Streamlit 的 Markdown 解析器会把「缩进 4 个空格的行」当成代码块，
    一旦换行加缩进，页面上就会出现一堆多余的灰色代码框。
"""

from __future__ import annotations

from html import escape          # 转义用户输入里的 < > & ，防止 HTML 注入
import re

from core.compiler import CompileResult
from core.emotion import EmotionState, MOOD_ICONS, MOOD_LABELS, MOODS
from core.runtime import HP_MAX, MP_MAX, RuntimeLog, RuntimeState
from core.world_config import WorldProfile


# ----------------------------------------------------------------------------
# 顶部标题区
# ----------------------------------------------------------------------------
def header_html(session_id: str = "") -> str:
    """全站页眉：品牌、版本、会话状态与一句话定位。"""
    session = (
        f'<span class="rc-session"><i></i>SESSION {escape(session_id.upper())}</span>'
        if session_id else ""
    )
    return (
        '<header class="rc-head">'
        '<div class="rc-head-meta"><span>PERSONAL REALITY ENGINE</span>'
        f'{session}</div>'
        '<h1 class="rc-title"><span>Reality</span> Compiler<em>v3.0</em>'
        '<span class="rc-caret" aria-hidden="true"></span></h1>'
        '<div class="rc-sub">把真实生活编译成可读、可复盘、可持续演化的人生运行日志。</div>'
        '</header>'
    )


def page_intro_html(icon: str, title: str, description: str) -> str:
    """设置、报告等次级页面的统一标题卡。"""
    return (
        '<section class="rc-page-intro">'
        f'<span class="rc-page-icon">{escape(icon)}</span>'
        '<div>'
        f'<h2>{escape(title)}</h2>'
        f'<p>{escape(description)}</p>'
        '</div></section>'
    )


def world_card_html(world: WorldProfile, date_text: str, ai_connected: bool = False) -> str:
    """今日世界观主卡片；所有 AI 字段都必须转义。"""
    connection_class = "" if ai_connected else " offline"
    connection_text = "AI ONLINE" if ai_connected else "LOCAL MODE"
    return (
        '<section class="rc-world-card">'
        '<div class="rc-world-orb" aria-hidden="true">◈</div>'
        '<div class="rc-world-copy">'
        '<span class="rc-eyebrow">TODAY\'S WORLD / 今日世界</span>'
        f'<h2>{escape(world.label)}</h2>'
        f'<p>{escape(world.desc)}</p>'
        '<div class="rc-world-meta">'
        f'<span>◷ {escape(date_text)}</span>'
        f'<span>{escape(world.variable_stat.icon)} 通用资产 · {escape(world.variable_stat.name)}</span>'
        '</div></div>'
        f'<span class="rc-live{connection_class}"><i></i>{connection_text}</span>'
        '</section>'
    )


def settings_status_html(
    api_status: str,
    logging_on: bool,
    memory_on: bool,
    emotion_on: bool = True,
) -> str:
    """设置页概览：让用户不用展开每一项也能看到当前状态。"""
    def _item(label: str, enabled: bool, enabled_text: str, disabled_text: str) -> str:
        cls = "on" if enabled else "off"
        value = enabled_text if enabled else disabled_text
        return (
            f'<div class="rc-status-item {cls}"><i></i><span>{escape(label)}</span>'
            f'<b>{escape(value)}</b></div>'
        )

    api_states = {
        "verified": ("on", "连接已验证"),
        "failed": ("warn", "连接失败"),
        "checking": ("warn", "正在验证"),
        "missing": ("off", "未填写"),
    }
    api_cls, api_text = api_states.get(str(api_status), api_states["missing"])
    api_item = (
        f'<div class="rc-status-item {api_cls}"><i></i><span>模型连接</span>'
        f'<b>{escape(api_text)}</b></div>'
    )
    return (
        '<section class="rc-status-grid">'
        + api_item
        + _item("本地日志", logging_on, "记录中", "已关闭")
        + _item("长期记忆", memory_on, "已启用", "已关闭")
        + _item("情绪氛围", emotion_on, "已启用", "已关闭")
        + '</section>'
    )


def notice_html(title: str, body: str, kind: str = "info") -> str:
    """统一提示条；kind 仅允许 info / warn / ok。"""
    safe_kind = kind if kind in {"info", "warn", "ok"} else "info"
    return (
        f'<aside class="rc-notice {safe_kind}"><i></i><div>'
        f'<b>{escape(title)}</b><span>{escape(body)}</span>'
        '</div></aside>'
    )


def label_html(main: str, note: str = "") -> str:
    """小节标题，例如「运行时 · 终端窗口」。"""
    extra = f'<span>{escape(note)}</span>' if note else ""
    return f'<div class="rc-label">{escape(main)}{extra}</div>'


# ----------------------------------------------------------------------------
# 空状态 / 错误
# ----------------------------------------------------------------------------
def idle_html() -> str:
    """待机面板：没编译过任何东西时显示，告诉用户该干嘛。"""
    return (
        '<div class="rc-idle">'
        '<b>把今天发生的事写下来</b><br>'
        '每天的世界观都由 AI 现场生成；编译器会把你的日常交给 AI，生成一段「人生代码」，'
        '再模拟运行，最后给你结算出 HP / MP / 可变属性 / 等级。<br>'
        '试着写清楚<u>做了什么</u>、<u>做了多久</u>、<u>感觉如何</u>，记录会更准。'
        '</div>'
    )


def error_html(message: str) -> str:
    """内联错误提示，比 st.error 的默认红框更克制。"""
    return f'<div class="rc-err">error: {escape(message)}</div>'


# ----------------------------------------------------------------------------
# 告警
# ----------------------------------------------------------------------------
def warnings_html(warnings: list[str]) -> str:
    """把编译告警渲染成一组小条。没有告警时返回空字符串。"""
    if not warnings:
        return ""
    items = "".join(
        f'<div class="rc-warn">⚠ {escape(w)}</div>' for w in warnings
    )
    return f'<div class="rc-warns">{items}</div>'


# ----------------------------------------------------------------------------
# 终端窗口
# ----------------------------------------------------------------------------
def terminal_html(lines: list[str]) -> str:
    """把运行时日志渲染成一个带标题栏的终端窗口。"""
    body = "".join(f'<div class="rc-line">{escape(l)}</div>' for l in lines)
    return (
        '<section class="rc-term">'
        '<div class="rc-term-bar">'
        '<span class="rc-dot"></span><span class="rc-dot"></span><span class="rc-dot"></span>'
        '<b>runtime · life 3.0</b>'
        '</div>'
        f'<div class="rc-term-body">{body}</div>'
        '</section>'
    )


# ----------------------------------------------------------------------------
# 属性面板（HP / MP / 钱包 / 等级 四格）
# ----------------------------------------------------------------------------
def _cell(name: str, val: int, maxv: int | None = None, unit: str = "") -> str:
    """生成一格属性：名称 + 数值 + 可选的进度条。"""
    if maxv is not None:
        pct = max(0, min(100, round(val / maxv * 100)))
        bar = f'<div class="rc-bar"><i style="width:{pct}%"></i></div>'
    else:
        bar = ""
    return (
        f'<div class="rc-cell">'
        f'<span class="rc-k">{escape(name)}</span>'
        f'<b class="rc-v">{val}{unit}</b>'
        f'{bar}'
        f'</div>'
    )


def _calc_row(label: str, before: int, delta: int, after: int) -> str:
    """计算过程里的一行：属性名 before ±delta = after。"""
    sign = "+" if delta >= 0 else ""
    return f'<div class="rc-cd">{escape(label)} {before} {sign}{delta} = {after}</div>'


def calc_html(log: RuntimeLog, world: WorldProfile | None = None,
              initial_vstat: int | None = None) -> str:
    """把「属性是怎么算出来的」逐步透明化展示出来。

    面板始终可见（不折叠），让用户点击编译后就能直接看到：
      初始值 -> 每个命中事件的逐属性增量与夹紧 -> 最终结算值。
    world 为当前世界观；为 None 时退化显示「钱包」。
    initial_vstat 为可变属性初始值（如用户设置的初始存款），None 时用世界默认。
    """
    vs = world.variable_stat if world else None
    vname = (f"{vs.icon} {vs.name}") if vs else "钱包"

    hp0, mp0 = HP_MAX, MP_MAX
    v0 = int(initial_vstat) if initial_vstat is not None else (vs.initial if vs else 0)
    exp0 = 0

    rows: list[str] = []
    rows.append(
        f'<div class="rc-calc-line rc-calc-init">'
        f'▶ 初始：HP {hp0} · MP {mp0} · {escape(vname)} {v0} · EXP {exp0}</div>'
    )

    if not log.steps:
        rows.append(
            '<div class="rc-calc-line rc-calc-note">无命中事件，属性保持初始值。</div>'
        )
    else:
        for s in log.steps:
            head = f'{s.order}. {escape(s.icon)} {escape(s.name)} ×{s.scale:.2f}'
            block = (
                _calc_row("HP ", s.hp_before, s.dhp, s.hp_after)
                + _calc_row("MP ", s.mp_before, s.dmp, s.mp_after)
                + _calc_row(vname + " ", s.v_before, s.dv, s.v_after)
                + _calc_row("EXP", s.exp_before, s.dexp, s.exp_after)
            )
            clamp = (
                f'<div class="rc-calc-clamp">⚠ 上限/下限{escape(s.clamp)}</div>'
                if s.clamp else ""
            )
            rows.append(
                f'<div class="rc-calc-step"><div class="rc-calc-ev">{head}</div>'
                f'{block}{clamp}</div>'
            )

    st_state = log.state
    final = (
        f'▶ 结算：HP {st_state.hp}/{HP_MAX} · MP {st_state.mp}/{MP_MAX} · '
        f'{escape(vname)} {st_state.vstat} · EXP {st_state.exp} (Lv.{st_state.level})'
    )
    rows.append(f'<div class="rc-calc-line rc-calc-final">{final}</div>')

    return '<section class="rc-calc">' + "".join(rows) + '</section>'


def stats_html(state: RuntimeState, world: WorldProfile | None = None) -> str:
    """把角色面板渲染成属性卡：HP / MP / 等级 为固定格，外加一个随世界观切换的可变属性格。

    world 为当前世界观；为 None 时退化为旧版（可变属性格显示「钱包」）。
    """
    if world is None:
        v_cell = _cell("钱包", state.vstat)               # 兼容：无世界信息时用「钱包」
    else:
        vs = world.variable_stat
        # 可变属性格：带图标与显示名；有上限（如 San 0~100）才画进度条
        v_cell = _cell(f"{vs.icon} {vs.name}", state.vstat, vs.max_val)
    return (
        '<section class="rc-stats">'
        + _cell("HP", state.hp, HP_MAX)
        + _cell("MP", state.mp, MP_MAX)
        + v_cell
        + _cell("等级", state.level)
        + '</section>'
    )


# ----------------------------------------------------------------------------
# buff / debuff 标签墙
# ----------------------------------------------------------------------------
def _chip_extra_class(name: str, world: WorldProfile | None) -> str:
    """若当前世界为该事件名定义了配色（如后室杏仁水=蓝、实体=红），返回额外 class。"""
    if world and name in world.chip_colors:
        return " " + _safe_css_classes(world.chip_colors[name])
    return ""


def _safe_css_classes(value: str) -> str:
    """只保留普通 CSS class token，阻止属性值注入。"""
    return " ".join(re.findall(r"[A-Za-z0-9_-]+", str(value)))


def chips_html(chips: list[tuple[str, str]], world: WorldProfile | None = None) -> str:
    """把事件渲染成一排方角标签，消耗为 debuff（红），恢复为 buff（绿）。

    world 提供世界特定的配色语义；定义配色的事件（如后室杏仁水/实体）会覆盖默认绿/红。
    """
    items = "".join(
        f'<span class="rc-chip {_safe_css_classes(kind)}{_chip_extra_class(name, world)}">'
        f'{escape(name)}</span>'
        for name, kind in chips
    )
    return f'<div class="rc-chips">{items}</div>'


# ----------------------------------------------------------------------------
# 今日复盘（v2.1：AI 生成的整体总结 + 改进建议）
# ----------------------------------------------------------------------------
def replay_html(summary: str, advice: str) -> str:
    """「📋 今日复盘」：展示 AI 生成的每日复盘总结与改进建议。

    两个字段都来自 DeepSeek 返回的 summary / advice；为空时隐藏对应块。
    """
    body = ""
    if summary:
        body += f'<div class="rc-replay-sum">{escape(summary)}</div>'
    if advice:
        body += f'<div class="rc-replay-adv"><b>改进建议</b>{escape(advice)}</div>'
    if not body:
        return ""
    return f'<section class="rc-replay">{body}</section>'


# ----------------------------------------------------------------------------
# 情绪氛围 + 叙事事件卡（v3.1）
# ----------------------------------------------------------------------------
def _display_mood(emotion: EmotionState, override: str | None = None) -> str:
    return override if override in MOODS else emotion.mood if emotion.mood in MOODS else "calm"


def mood_ambience_html(emotion: EmotionState, override: str | None = None) -> str:
    """固定在页面背景的纯装饰层；类名来自白名单，绝不拼接用户文本。"""
    mood = _display_mood(emotion, override)
    gentle = " gentle" if emotion.gentle else ""
    particles = "" if emotion.gentle else "".join(
        f'<i aria-hidden="true" style="--i:{index}"></i>' for index in range(1, 17)
    )
    return (
        f'<div class="rc-mood-ambience rc-mood-{mood}{gentle}" '
        f'data-mood="{mood}" aria-hidden="true">{particles}</div>'
    )


def emotion_card_html(emotion: EmotionState, override: str | None = None) -> str:
    """情绪结果卡；手动校准只替换展示标签，不修改原始 EmotionState。"""
    mood = _display_mood(emotion, override)
    label = MOOD_LABELS[mood]
    icon = MOOD_ICONS[mood]
    source = "手动校准 · 仅改变氛围" if override in MOODS else (
        "AI 情绪识别" if emotion.source == "ai" else "本地安全兜底"
    )
    reason = emotion.reason or "这段记录的情绪线索比较平稳。"
    gentle_note = (
        '<div class="rc-emotion-gentle">界面已切换为安静模式。此刻可以先停一下，联系信任的人陪伴你；如有立即危险，请联系当地紧急服务。</div>'
        if emotion.gentle else ""
    )
    return (
        f'<section class="rc-emotion-card mood-{mood}">'
        f'<span class="rc-emotion-icon">{icon}</span>'
        '<div class="rc-emotion-copy">'
        f'<span class="rc-emotion-kicker">EMOTION SIGNAL · {escape(source)}</span>'
        f'<h3>{escape(label)}</h3><p>{escape(reason)}</p>{gentle_note}'
        '</div>'
        '<div class="rc-emotion-meter">'
        f'<span>强度 {emotion.intensity}</span><i><b style="width:{max(2, min(100, emotion.intensity))}%"></b></i>'
        f'<em>置信度 {emotion.confidence}%</em>'
        '</div></section>'
    )


def event_cards_html(result: CompileResult, world: WorldProfile | None = None) -> str:
    """把编译事件渲染成逐张出现的叙事卡，所有模型文本都经过 HTML 转义。"""
    currency = world.variable_stat.name if world else "资产"
    cards: list[str] = []
    for index, matched in enumerate(result.matched or [], start=1):
        event = matched.event
        scale = float(getattr(matched, "scale", 1.0) or 1.0)
        values = (
            ("HP", round(event.hp * scale)),
            ("MP", round(event.mp * scale)),
            (currency, round(event.gold * scale)),
            ("EXP", round(event.exp * scale)),
        )
        deltas = "".join(
            f'<span class="{"up" if value > 0 else "down" if value < 0 else "flat"}">'
            f'{escape(label)} {_signed(value)}</span>' for label, value in values
        )
        tags = "".join(
            f'<span>{escape(str(tag))}</span>' for tag in (event.keywords or ())[:5]
        )
        description = event.description or "现实被编译成了一条新的世界事件。"
        cards.append(
            f'<article class="rc-event-card" style="--order:{index}">'
            f'<div class="rc-event-index">{index:02d}</div>'
            '<div class="rc-event-body">'
            f'<h3>{escape(event.icon)} {escape(event.name)}</h3>'
            f'<p>{escape(description)}</p><div class="rc-event-tags">{tags}</div>'
            f'</div><div class="rc-event-deltas">{deltas}</div></article>'
        )
    if not cards:
        return ""
    return '<section class="rc-event-list">' + "".join(cards) + '</section>'


# ----------------------------------------------------------------------------
# AI 自我反思（v3.0 Agent 化：Reflection 结论展示）
# ----------------------------------------------------------------------------
def reflection_html(reasonable: bool, source: str, issues: list[str],
                    suggestion: str) -> str:
    """「🔎 AI 自我反思」：展示 Agent 对本次编译的自我审查结论。

    reasonable: 是否合理
    source:     "ai"（AI 反思）或 "rule"（本地规则反思，AI 不可用时的降级）
    issues:     发现的问题列表
    suggestion: 改进建议
    """
    tag = "通过" if reasonable else "未通过"
    cls = "ok" if reasonable else "warn"
    src_txt = "AI 深度审查" if source == "ai" else "本地快速复核（零额外请求）"
    body = (
        f'<div class="rc-refl-head">'
        f'<span class="rc-refl-badge {cls}">{escape(tag)}</span>'
        f'<span class="rc-refl-src">{escape(src_txt)}</span>'
        f'</div>'
    )
    if issues:
        body += '<div class="rc-refl-issues">' + "".join(
            f'<div class="rc-refl-item">· {escape(str(i))}</div>' for i in issues
        ) + '</div>'
    if suggestion:
        body += f'<div class="rc-refl-adv"><b>建议</b>{escape(suggestion)}</div>'
    return f'<section class="rc-refl">{body}</section>'


# ----------------------------------------------------------------------------
# 世界演化（v3.0 Phase 4：Simulation 结论展示）
# ----------------------------------------------------------------------------
def simulation_html(
    trajectory: list,
    triggered: list,
    derived_events: list,
    final_state: dict,
) -> str:
    """「🌍 世界演化」：展示事件如何影响状态、状态如何触发规则、衍生新事件。

    trajectory:   [(事件名, 状态增量 dict, 演化后状态 dict), ...]
    triggered:    [Rule, ...]（触发规则）
    derived_events: [事件 dict, ...]（衍生事件）
    final_state:  {energy, stress, sleep_debt} 演化后的状态
    """
    body = ""
    # 状态条：当前隐藏状态
    state_bars = []
    for key, label, warn in (("energy", "精力", "低"),
                             ("stress", "压力", "高"),
                             ("sleep_debt", "睡眠债", "高")):
        val = int(final_state.get(key, 0) or 0)
        cls = "ok"
        if (key == "energy" and val < 30) or ((key in ("stress", "sleep_debt")) and val > 70):
            cls = "warn"
        state_bars.append(
            f'<span class="rc-sim-bar"><b>{label}</b>'
            f'<i class="{cls}" style="width:{max(2, val)}%"></i>'
            f'<em>{val}</em></span>'
        )
    body += f'<div class="rc-sim-state">{"".join(state_bars)}</div>'

    # 演化轨迹（精简展示：只列出有状态变化的事件）
    changed = [t for t in trajectory if t[1]]
    if changed:
        body += '<div class="rc-sim-traj">'
        for name, delta, _after in changed[:6]:
            d_txt = " ".join(
                f"{k}{_signed(v)}" for k, v in sorted(delta.items())
            )
            body += f'<div class="rc-sim-item">· {escape(str(name))} → {escape(d_txt)}</div>'
        body += '</div>'

    # 触发的规则 + 衍生事件
    for rule in triggered:
        body += (
            f'<div class="rc-sim-rule warn">⚡ 触发「{escape(getattr(rule, "name", ""))}」'
            f'（{escape(getattr(rule, "state_field", ""))} '
            f'{escape(getattr(rule, "direction", ">="))}{getattr(rule, "threshold", 0)}）</div>'
        )
    if derived_events:
        names = "、".join(escape(str(e.get("name", ""))) for e in derived_events[:5])
        body += f'<div class="rc-sim-rule">↳ 衍生事件：{names}</div>'

    if not body:
        return ""
    return f'<section class="rc-sim">{body}</section>'


# ----------------------------------------------------------------------------
# Agent 流程可视化（v3.1：每步耗时 + 进度条）
# ----------------------------------------------------------------------------
_AGENT_STEPS = [
    ("Planner",   "🧠",  "编译计划"),
    ("LLM",       "🤖",  "AI 生成"),
    ("Validator", "🔍",  "语义校验"),
    ("Runtime",   "⚙️",  "运行结算"),
    ("Reflection","💭",  "AI 反思"),
    ("Simulation","🌍",  "世界演化"),
    ("Memory",    "💾",  "记忆归档"),
]

def flow_html(timings: dict) -> str:
    """渲染 Agent 执行流程可视化：每步图标 + 耗时 + 进度条。

    参数 timings 来自 AgentRunResult.timings，示例：
        {"Planner": 0.001, "LLM": 2.3, "total": 2.5, ...}
    """
    total = timings.get("total", 0) or 0
    if total <= 0:
        return ""

    rows = []
    for step_key, icon, label in _AGENT_STEPS:
        t = timings.get(step_key, 0) or 0
        if t == 0 and step_key not in timings:
            continue  # 跳过未启用的步骤
        pct = (t / total * 100) if total > 0 else 0
        bar_w = max(3, min(pct, 100))  # 至少 3% 宽度，让短步骤也可见
        rows.append(
            '<div class="rc-flow-step">'
            f'<span class="rc-flow-icon">{icon}</span>'
            f'<span class="rc-flow-label">{escape(label)}</span>'
            f'<span class="rc-flow-bar"><span style="width:{bar_w}%"></span></span>'
            f'<span class="rc-flow-time">{t:.1f}s</span>'
            '</div>'
        )
    body = "".join(rows)
    return (
        '<section class="rc-flow">'
        f'<div class="rc-flow-head"><span>Agent 执行流程</span>'
        f'<span class="rc-flow-total">TOTAL {total:.1f}s</span></div>'
        f'{body}</section>'
    )


# ----------------------------------------------------------------------------
# 日志统计（v2.3：日 / 周 / 月三列，终端风格）
# ----------------------------------------------------------------------------
def _signed(n) -> str:
    """正数加 + 前缀，负数/零原样，用于展示净变化。"""
    return f"+{n}" if n > 0 else str(n)


def log_stats_html(daily: dict, weekly: dict, monthly: dict) -> str:
    """「📊 日志统计」：日 / 周 / 月三列，展示事件数 / 属性净变化 / 经验 / 标签 TOP。

    注意：函数名刻意避开 stats_html（那是属性结算面板，接收 state/world）。
    daily / weekly / monthly 为 core.logger.stats_today() 等返回的 dict。
    """
    def _row(k, v):
        return f'<div class="rc-stats-row"><span>{escape(str(k))}</span><b>{escape(str(v))}</b></div>'

    def _tags(tags, label):
        if not tags:
            return f'<div class="rc-stats-row"><span>{escape(label)}</span><b>暂无</b></div>'
        chips = "".join(f'<span class="rc-chip buff">{escape(t)}</span>' for t in tags)
        return f'<div class="rc-stats-row"><span>{escape(label)}</span></div><div class="rc-stats-tags">{chips}</div>'

    def _col(title, rows, tags, tags_label):
        body = "".join(_row(k, v) for k, v in rows)
        return (f'<div class="rc-stats-col"><h4>{escape(title)}</h4>{body}{_tags(tags, tags_label)}</div>')

    def _mood_label(data: dict) -> str:
        mood = str(data.get("dominant_mood") or "")
        return MOOD_LABELS.get(mood, "暂无")

    daily_col = _col("日统计", [
        ("总事件", daily.get("events", 0)),
        ("HP 净变化", _signed(daily.get("hp_delta", 0))),
        ("MP 净变化", _signed(daily.get("mp_delta", 0))),
        ("金钱净变化", _signed(daily.get("gold_delta", 0))),
        ("获得经验", daily.get("exp_gain", 0)),
        ("主情绪", _mood_label(daily)),
    ], daily.get("top_tags", []), "标签 TOP3")

    weekly_col = _col("周统计", [
        ("总事件", weekly.get("events", 0)),
        ("日均 HP 变化", _signed(weekly.get("avg_hp", 0))),
        ("日均金钱变化", _signed(weekly.get("avg_gold", 0))),
        ("周累计经验", weekly.get("exp_gain", 0)),
        ("主情绪", _mood_label(weekly)),
    ], weekly.get("top_tags", []), "标签 TOP5")

    monthly_col = _col("月统计", [
        ("总事件", monthly.get("events", 0)),
        ("月均 HP 变化", _signed(monthly.get("avg_hp", 0))),
        ("月均 MP 变化", _signed(monthly.get("avg_mp", 0))),
        ("月均金钱变化", _signed(monthly.get("avg_gold", 0))),
        ("月累计经验", monthly.get("exp_gain", 0)),
        ("等级轨迹", " → ".join(str(lv) for lv in monthly.get("level_track", [])) or "暂无"),
        ("主情绪", _mood_label(monthly)),
    ], monthly.get("top_tags", []), "标签 TOP5")

    return f'<section class="rc-log-stats">{daily_col}{weekly_col}{monthly_col}</section>'


# ----------------------------------------------------------------------------
# 运算规则 / 设定说明（放在页面底部折叠区，纯静态文案，无用户输入）
# ----------------------------------------------------------------------------
def rules_html() -> str:
    """把「运算规则 / 设定」渲染成一个说明块，放在输出区下方、页脚上方。

    内容严格对应 core/ 的实际实现：
      - 初始值、结算公式、事件生成、等级、上下限、buff/debuff。
    全部为静态文案，不含用户输入，无需 escape。
    """
    return (
        '<div class="rc-rules">'
        '<ol class="rc-rules-list">'
        '<li><b>世界观</b>：每天首次打开页面，由 AI 实时生成一个<strong>全新世界观</strong>'
        '（名称、背景、货币名每天都不同）；货币名决定属性面板「可变属性」的显示（如金币 / 杏仁水 / 比特币）。</li>'
        '<li><b>恒定初始值</b>：每次编译都从 <code>HP 100 / MP 100</code>、可变属性（世界默认值，'
        '或你设置的<strong>初始存款</strong>）、<code>EXP 0</code> 重新结算，不跨次、不跨天累积。</li>'
        '<li><b>结算公式</b>：<code>属性 = 初始值 + Σ(命中事件的数值 × 强度倍率)</code>。'
        '减法由「负的事件数值」表示；事件的 gold 字段会映射到当前世界的可变属性（货币）；'
        '目前只有加法与倍率乘法，没有除法。</li>'
        '<li><b>事件生成</b>：由 AI 编译器根据输入实时生成事件，按<strong>当前世界观</strong>组织描述风格；'
        '描述越具体，生成越准。</li>'
        '<li><b>数值来源</b>：事件数值由 AI 编译器直接估算，结算时倍率恒为 1.0'
        '（不再有本地词库与强度副词），描述越具体，估算越准。</li>'
        '<li><b>等级</b>：从 Lv.1 起步，升下一级所需经验为“当前等级² × 50”；等级最高 99。</li>'
        '<li><b>上下限</b>：HP / MP 夹在 <code>0~100</code> 之间（掉到 0 不再负，加满不再超）；'
        '可变属性按世界设定夹取（默认下限 0，不封顶）；每个事件 EXP 夹在 0~15。</li>'
        '<li><b>buff / debuff</b>：某事件只要「掉血 / 掉蓝 / 消耗可变属性」任一成立即标红（debuff），'
        '否则标绿（buff）；事件名带「🚨」时升级为红色警报（不健康行为）。只看单事件，不被收益掩盖。</li>'
        '<li><b>稳定性</b>：AI 必至少返回一条事件，平淡时也生成 exp=1 的「平凡日常」，保证不白屏。</li>'
        '</ol>'
        '</div>'
    )


# ----------------------------------------------------------------------------
# 页脚
# ----------------------------------------------------------------------------
def footer_html() -> str:
    """页脚：一行足够，不做四栏链接墙。"""
    return (
        '<footer class="rc-foot">'
        '<span>Reality Compiler · 通用 AI 编译器</span>'
        '<span>输入将发送给大模型以生成结果</span>'
        '</footer>'
    )
