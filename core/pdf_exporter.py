# -*- coding: utf-8 -*-
"""PDF 导出：把一段时间日志导出为深色终端风格的 PDF 报告（v3.1）。

v3.1 增强：支持可选的「情绪卡 / 反思摘要 / 世界演化时间线 / Agent 执行流程」
         四大附加板块，由 UI 层按需传入；未传入时降级为 v2.3 的基础报告。

技术选型：reportlab（对中文支持好，可精确控制样式）。
字体：reportlab 内置 CID 字体 STSong-Light（简体中文），保证中文正常显示。
样式：深色背景 #0d1110，正文浅色 #d0d0d0，标题磷光绿 #7fe08a，
      次要信息 #9aa8a1，分隔线用 ━ 字符；整体保持终端感。

对外入口：
    build_report_pdf(period_label, logs, ai_report, **extras) -> bytes
    build_single_compile_pdf(result, log, world, reflection, simulation, timings) -> bytes
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# 终端风格配色（与 assets/terminal.css 对齐）
_BG = HexColor("#0d1110")
_INK = HexColor("#d0d0d0")
_DIM = HexColor("#9aa8a1")
_GREEN = HexColor("#7fe08a")
_AMBER = HexColor("#e8a13a")
_CYAN = HexColor("#68d8ff")
_RED = HexColor("#ff7770")

_FONT = "STSong-Light"          # reportlab 内置简体中文 CID 字体
_BODY_SIZE = 9.5                # 正文
_TITLE_SIZE = 15                # 大标题
_SUB_SIZE = 11                  # 小节标题

_MARGIN = 46                    # 页边距


def _register_font() -> None:
    """注册中文字体（幂等；重复注册无害）。"""
    try:
        pdfmetrics.getFont(_FONT)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))


def _wrap_text(text: str, size: float, max_w: float) -> list[str]:
    """按像素宽度切分中文文本（STSong 下每字宽度近似一致）。"""
    if not text:
        return [""]
    if pdfmetrics.stringWidth(text, _FONT, size) <= max_w:
        return [text]
    lines: list[str] = []
    cur = ""
    for ch in text:
        if pdfmetrics.stringWidth(cur + ch, _FONT, size) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _build_canvas() -> tuple:
    """构造一个带深色背景的 PDF canvas。返回 (canvas, width, height, content_w)。"""
    _register_font()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    content_w = width - _MARGIN * 2
    c.setFillColor(_BG)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    return c, buf, width, height, content_w


def _make_drawer(c, width, height, content_w):
    """创建闭包风格的绘制工具函数集合。"""
    y = height - _MARGIN

    def _new_page() -> None:
        nonlocal y
        c.showPage()
        c.setFillColor(_BG)
        c.rect(0, 0, width, height, fill=1, stroke=0)
        y = height - _MARGIN

    def _draw(text: str, color=_INK, size=_BODY_SIZE, indent: float = 0, after: float = 7) -> None:
        nonlocal y
        for ln in _wrap_text(text, size, content_w - indent):
            if y < _MARGIN:
                _new_page()
            c.setFillColor(color)
            c.setFont(_FONT, size)
            c.drawString(_MARGIN + indent, y, ln)
            y -= size + after
        if not text:
            y -= after

    def _sep(after: float = 10) -> None:
        nonlocal y
        if y < _MARGIN:
            _new_page()
        c.setFillColor(_DIM)
        c.setFont(_FONT, 9)
        c.drawString(_MARGIN, y, "━" * 36)
        y -= after

    return _draw, _sep, _new_page, lambda: y


def build_report_pdf(period_label: str, logs: list[dict], ai_report: str,
                     emotion: dict | None = None,
                     reflection: dict | None = None,
                     simulation: dict | None = None,
                     timings: dict | None = None) -> bytes:
    """生成一份深色终端风格的 PDF 报告，返回 PDF 二进制内容（v3.1）。

    新增可选参数：
        emotion:    {"mood": "...", "intensity": 0.8} —— 情绪卡
        reflection: {"reasonable": True, "issues": [], "suggestion": "..."} —— 反思摘要
        simulation: {"evolved": True, "triggered_rules": [...], "derived_events": [...]} —— 世界演化
        timings:    {"Planner": 0.01, "LLM": 2.3, "total": 2.5} —— Agent 执行流程
    """
    c, buf, width, height, content_w = _build_canvas()
    _draw, _sep, _new_page, _get_y = _make_drawer(c, width, height, content_w)

    # —— 标题区 ——
    _draw("REALITY COMPILER · 日志报告", _GREEN, _TITLE_SIZE, after=6)
    _draw(f"报告周期：{period_label}", _INK, _SUB_SIZE, after=14)
    _sep()

    # —— 情绪卡（v3.1） ——
    if emotion:
        _draw("情绪状态", _GREEN, _SUB_SIZE, after=4)
        mood = emotion.get("mood", "")
        intensity = emotion.get("intensity", 0)
        _draw(f"核心情绪：{mood}", _CYAN, _BODY_SIZE, after=4)
        bar_w = int(intensity * 40)
        _draw(f"强度：[{'█' * bar_w}{'░' * (40 - bar_w)}] {intensity:.0%}", _DIM, 8.5, after=8)
        _sep()

    # —— AI 概览与复盘 ——
    _draw("今日概览与复盘", _GREEN, _SUB_SIZE, after=4)
    for line in (ai_report or "（AI 报告暂不可用）").splitlines():
        _draw(line, _INK, _BODY_SIZE, after=6)
    _sep()

    # —— 反思摘要（v3.1） ——
    if reflection:
        _draw("AI 自我反思", _GREEN, _SUB_SIZE, after=4)
        ok = reflection.get("reasonable", True)
        _draw(f"结论：{'✅ 通过' if ok else '⚠️ 未通过'}", _GREEN if ok else _AMBER, _BODY_SIZE, after=4)
        issues = reflection.get("issues") or []
        for iss in issues:
            _draw(f"  · {iss}", _RED, 8.5, after=3)
        sug = reflection.get("suggestion", "")
        if sug:
            _draw(f"建议：{sug}", _CYAN, 8.5, after=4)
        _sep()

    # —— 世界演化时间线（v3.1） ——
    if simulation and simulation.get("evolved"):
        _draw("世界演化时间线", _GREEN, _SUB_SIZE, after=4)
        rules = simulation.get("triggered_rules") or []
        events = simulation.get("derived_events") or []
        _draw(f"触发规则：{len(rules)} 条", _CYAN, _BODY_SIZE, after=4)
        for r in rules[:8]:
            if isinstance(r, dict):
                _draw(f"  ⚡ {r.get('name', str(r))}", _AMBER, 8.5, after=3)
            else:
                _draw(f"  ⚡ {r}", _AMBER, 8.5, after=3)
        _draw(f"衍生事件：{len(events)} 个", _CYAN, _BODY_SIZE, after=4)
        for ev in events[:8]:
            if isinstance(ev, dict):
                _draw(f"  🌀 {ev.get('name', str(ev))} —— {ev.get('description', '')}", _DIM, 8.5, after=3)
            else:
                _draw(f"  🌀 {ev}", _DIM, 8.5, after=3)
        _sep()

    # —— Agent 执行流程（v3.1） ——
    if timings and timings.get("total", 0) > 0:
        _draw("Agent 执行流程", _GREEN, _SUB_SIZE, after=4)
        total = timings.get("total", 0)
        _draw(f"总耗时：{total:.2f}s", _GREEN, _BODY_SIZE, after=4)
        step_order = ["Planner", "LLM", "Validator", "Runtime", "Reflection", "Simulation", "Memory"]
        step_labels = {"Planner": "🧠 编译计划", "LLM": "🤖 AI 生成",
                       "Validator": "🔍 语义校验", "Runtime": "⚙️ 运行结算",
                       "Reflection": "💭 AI 反思", "Simulation": "🌍 世界演化",
                       "Memory": "💾 记忆归档"}
        for sk in step_order:
            t = timings.get(sk, 0)
            if t == 0 and sk not in timings:
                continue
            pct = (t / total * 100) if total > 0 else 0
            bar_w = max(2, min(int(pct / 2), 50))
            _draw(f"  {step_labels.get(sk, sk):<12s} [{'█' * bar_w}{'░' * (50 - bar_w)}] {t:.3f}s ({pct:.0f}%)",
                  _DIM, 8.5, after=3)
        _sep()

    # —— 事件流水 ——
    _draw("事件流水", _GREEN, _SUB_SIZE, after=4)
    for entry in logs:
        ts = str(entry.get("timestamp", ""))[:16]
        currency = entry.get("currency_name", "金钱")
        for ev in entry.get("events", []):
            _draw(
                f"[{ts}] {ev.get('name', '')}：{ev.get('description', '')} "
                f"hp {ev.get('hp', 0)}  mp {ev.get('mp', 0)}  "
                f"{currency} {ev.get('gold', 0)}  exp {ev.get('exp', 0)}",
                _INK, 8.5, after=5,
            )
    _sep()

    # —— 属性变化趋势 ——
    _draw("属性变化趋势", _GREEN, _SUB_SIZE, after=4)
    for entry in logs:
        stats = entry.get("stats") or {}
        currency = entry.get("currency_name", "金钱")
        _draw(
            f"[{str(entry.get('timestamp', ''))[:16]}]  HP {stats.get('hp')}  "
            f"MP {stats.get('mp')}  {currency} {stats.get('gold')}  "
            f"Lv.{stats.get('level')}  EXP {stats.get('exp')}",
            _DIM, 8.5, after=5,
        )
    _sep()

    # —— 附录 ——
    _draw("若已启用日志，原始记录保存在项目 logs/ 的会话子目录（JSONL，按天分割）", _AMBER, 8.5, after=4)

    c.showPage()
    c.save()
    return buf.getvalue()


def build_single_compile_pdf(result, log, world, reflection=None, simulation=None, timings=None) -> bytes:
    """生成「单次编译」的 PDF 报告（v3.1 新增，供主页导出）。

    参数：
        result:     CompileResult
        log:        RuntimeLog
        world:      WorldProfile
        reflection: ReflectionResult | None
        simulation: SimulationResult | None
        timings:    dict | None（来自 AgentRunResult.timings）
    """
    c, buf, width, height, content_w = _build_canvas()
    _draw, _sep, _new_page, _get_y = _make_drawer(c, width, height, content_w)

    # —— 标题区 ——
    _draw("REALITY COMPILER · 单次编译报告", _GREEN, _TITLE_SIZE, after=6)
    _draw(f"世界观：{world.label}", _CYAN, _SUB_SIZE, after=4)
    _draw(f"货币：{world.variable_stat.name} · 结算值 {world.variable_stat.icon}", _DIM, 9, after=14)
    _sep()

    # —— 情绪卡 ——
    emo = getattr(result, "emotion", None)
    if emo is not None:
        _draw("情绪状态", _GREEN, _SUB_SIZE, after=4)
        _draw(f"核心情绪：{emo.mood}", _CYAN, _BODY_SIZE, after=3)
        bar_w = int(emo.intensity * 40)
        _draw(f"强度：[{'█' * bar_w}{'░' * (40 - bar_w)}] {emo.intensity:.0%}", _DIM, 8.5, after=8)
        src = getattr(emo, "source", "")
        if src:
            _draw(f"来源：{src}", _DIM, 8.5, after=4)
        _sep()

    # —— 属性结算 ——
    _draw("属性结算", _GREEN, _SUB_SIZE, after=4)
    s = log.state
    _draw(f"HP {s.hp}/{100}   MP {s.mp}/{100}   {world.variable_stat.icon} {s.vstat}   Lv.{s.level}   EXP {s.exp}",
          _INK, _BODY_SIZE, after=6)
    for chip_name, chip_kind in log.chips:
        _draw(f"  [{chip_kind}] {chip_name}", _AMBER if chip_kind == "debuff" else _GREEN, 8.5, after=3)
    _sep()

    # —— 今日复盘 ——
    if result.summary or result.advice:
        _draw("今日复盘", _GREEN, _SUB_SIZE, after=4)
        for line in (result.summary or "").splitlines():
            _draw(line, _INK, _BODY_SIZE, after=5)
        if result.advice:
            _draw("建议：" + result.advice, _CYAN, _BODY_SIZE, after=5)
        _sep()

    # —— AI 反思 ——
    if reflection is not None:
        _draw("AI 自我反思", _GREEN, _SUB_SIZE, after=4)
        ok = getattr(reflection, "reasonable", True)
        _draw(f"结论：{'✅ 通过' if ok else '⚠️ 未通过'}", _GREEN if ok else _AMBER, _BODY_SIZE, after=4)
        for iss in getattr(reflection, "issues", []) or []:
            _draw(f"  · {iss}", _RED, 8.5, after=3)
        sug = getattr(reflection, "suggestion", "")
        if sug:
            _draw(f"建议：{sug}", _CYAN, 8.5, after=4)
        src = getattr(reflection, "source", "")
        if src:
            _draw(f"反思模式：{src}", _DIM, 8.5, after=4)
        _sep()

    # —— 世界演化 ——
    if simulation is not None and getattr(simulation, "evolved", False):
        _draw("世界演化时间线", _GREEN, _SUB_SIZE, after=4)
        rules = getattr(simulation, "triggered_rules", []) or []
        events = getattr(simulation, "derived_events", []) or []
        _draw(f"触发规则：{len(rules)} 条", _CYAN, _BODY_SIZE, after=4)
        for r in rules[:8]:
            if isinstance(r, dict):
                _draw(f"  ⚡ {r.get('name', str(r))}", _AMBER, 8.5, after=3)
            else:
                _draw(f"  ⚡ {r}", _AMBER, 8.5, after=3)
        _draw(f"衍生事件：{len(events)} 个", _CYAN, _BODY_SIZE, after=4)
        for ev in events[:8]:
            if isinstance(ev, dict):
                _draw(f"  🌀 {ev.get('name', str(ev))} —— {ev.get('description', '')}", _DIM, 8.5, after=3)
            else:
                _draw(f"  🌀 {ev}", _DIM, 8.5, after=3)
        # 最终状态
        fs = getattr(simulation, "final_state", None)
        if fs is not None:
            fd = fs.to_dict() if hasattr(fs, "to_dict") else dict(fs)
            _draw(f"最终状态：压力 {fd.get('stress',0)}  精力 {fd.get('energy',0)}  睡眠债 {fd.get('sleep_debt',0)}",
                  _GREEN, 8.5, after=4)
        _sep()

    # —— Agent 执行流程 ——
    if timings and timings.get("total", 0) > 0:
        _draw("Agent 执行流程", _GREEN, _SUB_SIZE, after=4)
        total = timings.get("total", 0)
        _draw(f"总耗时：{total:.2f}s", _GREEN, _BODY_SIZE, after=4)
        step_order = ["Planner", "LLM", "Validator", "Runtime", "Reflection", "Simulation", "Memory"]
        step_labels = {"Planner": "🧠 编译计划", "LLM": "🤖 AI 生成",
                       "Validator": "🔍 语义校验", "Runtime": "⚙️ 运行结算",
                       "Reflection": "💭 AI 反思", "Simulation": "🌍 世界演化",
                       "Memory": "💾 记忆归档"}
        for sk in step_order:
            t = timings.get(sk, 0)
            if t == 0 and sk not in timings:
                continue
            pct = (t / total * 100) if total > 0 else 0
            bar_w = max(2, min(int(pct / 2), 50))
            _draw(f"  {step_labels.get(sk, sk):<12s} [{'█' * bar_w}{'░' * (50 - bar_w)}] {t:.3f}s ({pct:.0f}%)",
                  _DIM, 8.5, after=3)
        _sep()

    # —— 事件明细 ——
    _draw("命中事件", _GREEN, _SUB_SIZE, after=4)
    for ev in result.matched:
        _draw(f"◆ {ev.event.name}：{ev.event.description}", _INK, 9.5, after=4)
        _draw(f"  hp {ev.event.hp:+d}  mp {ev.event.mp:+d}  gold {ev.event.gold:+d}  exp {ev.event.exp:+d}",
              _DIM, 8.5, after=5)
    _sep()

    # —— 附录 ——
    _draw(f"Build ID：{result.build_id}", _DIM, 8.5, after=4)
    _draw("Reality Compiler v3.1 · 由现实编译器自动生成", _AMBER, 8.5, after=4)

    c.showPage()
    c.save()
    return buf.getvalue()
