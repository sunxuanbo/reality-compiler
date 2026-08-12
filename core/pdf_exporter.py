# -*- coding: utf-8 -*-
"""PDF 导出：把一段时间日志导出为深色终端风格的 PDF 报告（v2.3）。

技术选型：reportlab（对中文支持好，可精确控制样式）。
字体：reportlab 内置 CID 字体 STSong-Light（简体中文），保证中文正常显示。
样式：深色背景 #0d1110，正文浅色 #d0d0d0，标题磷光绿 #7fe08a，
      次要信息 #9aa8a1，分隔线用 ━ 字符；整体保持终端感。

对外入口：build_report_pdf(period_label, logs, ai_report) -> bytes
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


def build_report_pdf(period_label: str, logs: list[dict], ai_report: str) -> bytes:
    """生成一份深色终端风格的 PDF 报告，返回 PDF 二进制内容。

    参数：
        period_label: 报告周期说明（如「2026年8月6日（周三）」）
        logs: 该时间段的日志记录（core.logger.read_range 的返回）
        ai_report: AI 生成的叙事总结文本（core.llm_client.call_llm_for_report）
    返回：
        PDF 文件字节（可直接给 st.download_button 使用）
    """
    _register_font()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    content_w = width - _MARGIN * 2

    y = height - _MARGIN

    def _new_page() -> None:
        nonlocal y
        c.showPage()
        _paint_bg()
        y = height - _MARGIN

    def _paint_bg() -> None:
        c.setFillColor(_BG)
        c.rect(0, 0, width, height, fill=1, stroke=0)

    def _draw(text: str, color: object = _INK, size: float = _BODY_SIZE,
              indent: float = 0, after: float = 7) -> None:
        nonlocal y
        for ln in _wrap_text(text, size, content_w - indent):
            if y < _MARGIN:
                _new_page()
            c.setFillColor(color)
            c.setFont(_FONT, size)
            c.drawString(_MARGIN + indent, y, ln)
            y -= size + after
        # 空行时也保留一个行距
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

    # —— 起始深色背景 ——
    _paint_bg()

    # —— 标题区 ——
    _draw("REALITY COMPILER · 日志报告", _GREEN, _TITLE_SIZE, after=6)
    _draw(f"报告周期：{period_label}", _INK, _SUB_SIZE, after=14)
    _sep()

    # —— AI 概览与复盘 ——
    _draw("今日概览与复盘", _GREEN, _SUB_SIZE, after=4)
    for line in (ai_report or "（AI 报告暂不可用）").splitlines():
        _draw(line, _INK, _BODY_SIZE, after=6)
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
