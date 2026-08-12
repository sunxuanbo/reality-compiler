# -*- coding: utf-8 -*-
"""报告页：日志统计（日/周/月）+ PDF 导出（v2.6，由 app.py 拆分而来）。

职责边界（bug6 拆分约定）：
    - 只负责统计展示与 PDF 导出按钮，业务计算全部下沉到 core/logger 与 core/pdf_exporter。
    - widget key 与 v2.5 完全一致，保证 tests/test_app.py 可无头跑通。

说明：本页面在有日志数据时才亮起导出按钮；无日志时按钮置灰并提示「暂无日志」。
"""

from __future__ import annotations

import datetime                 # 报告周期日期格式化

import streamlit as st           # Web 框架本体

from core import logger                          # 本地 JSONL 日志 + 日/周/月统计
from core import pdf_exporter                    # PDF 导出（reportlab 深色终端风格）
from core.llm_client import call_llm_for_report  # AI 报告总结


def _log_namespace() -> str:
    """当前访客的日志命名空间，防止托管部署时跨会话读取。"""
    return str(st.session_state.get("memory_id") or "session")


def _fmt_date(d) -> str:
    """把 date 格式化为「2026年8月6日」中文文案。"""
    return f"{d.year}年{d.month}月{d.day}日"


def _gen_report_pdf(slot: str, period_label: str, logs: list[dict]) -> None:
    """生成某时间段 PDF 并缓存到 session_state；失败记录错误文案。

    slot: "today" / "week" / "month"，用于区分三个导出按钮的缓存位。
    """
    try:
        report = call_llm_for_report(
            period_label, logs,
            api_key=st.session_state.get("cfg_api_key"),
            base_url=st.session_state.get("cfg_api_base"),
            model=st.session_state.get("cfg_api_model"),
        )
        st.session_state[f"pdf_{slot}_bytes"] = pdf_exporter.build_report_pdf(
            period_label, logs, report,
        )
        st.session_state[f"pdf_{slot}_err"] = ""
    except Exception as exc:
        st.session_state[f"pdf_{slot}_bytes"] = None
        st.session_state[f"pdf_{slot}_err"] = str(exc) or "生成 PDF 失败，请稍后重试。"


def _render_log_stats() -> None:
    """日志统计（日 / 周 / 月）展示区。"""
    from ui import render
    st.markdown(render.label_html("日志统计", "日 / 周 / 月"), unsafe_allow_html=True)
    st.markdown(
        render.log_stats_html(
            logger.stats_today(namespace=_log_namespace()),
            logger.stats_week(namespace=_log_namespace()),
            logger.stats_month(namespace=_log_namespace()),
        ),
        unsafe_allow_html=True,
    )


def _render_pdf_export() -> None:
    """PDF 日志报告：今日 / 本周 / 本月，有日志才亮起。"""
    from ui import render
    st.markdown(render.label_html("PDF 日志报告"), unsafe_allow_html=True)
    _pdf_container = st.container(key="pdf_exports")
    _pd1, _pd2, _pd3 = _pdf_container.columns(3)

    # —— 今日 ——
    _today_day = logger.current_day()
    _today_logs = logger.read_logs(_today_day, namespace=_log_namespace())
    _period_today = f"{_fmt_date(_today_day)}（今日）"
    with _pd1:
        if _today_logs:
            if st.button("📄 导出今日日志 (PDF)", key="btn_pdf_today"):
                _gen_report_pdf("today", _period_today, _today_logs)
            _b = st.session_state.get("pdf_today_bytes")
            if _b:
                st.download_button(
                    "⬇ 下载今日 PDF", data=_b, mime="application/pdf",
                    file_name=f"reality_report_{_today_day.isoformat()}.pdf",
                    key="dl_pdf_today",
                )
            elif st.session_state.get("pdf_today_err"):
                st.caption(f"⚠ {st.session_state['pdf_today_err']}")
        else:
            st.button("📄 导出今日日志 (PDF)", disabled=True, key="btn_pdf_today_dis")
            st.caption("今日暂无日志")

    # —— 本周 ——
    _w1, _w2 = logger.week_range()
    _week_logs = logger.read_range(_w1, _w2, namespace=_log_namespace())
    _period_week = f"本周（{_fmt_date(_w1)} ~ {_fmt_date(_w2)}）"
    with _pd2:
        if _week_logs:
            if st.button("📄 导出本周日志 (PDF)", key="btn_pdf_week"):
                _gen_report_pdf("week", _period_week, _week_logs)
            _b = st.session_state.get("pdf_week_bytes")
            if _b:
                st.download_button(
                    "⬇ 下载本周 PDF", data=_b, mime="application/pdf",
                    file_name=f"reality_report_week_{_w1.isoformat()}.pdf",
                    key="dl_pdf_week",
                )
            elif st.session_state.get("pdf_week_err"):
                st.caption(f"⚠ {st.session_state['pdf_week_err']}")
        else:
            st.button("📄 导出本周日志 (PDF)", disabled=True, key="btn_pdf_week_dis")
            st.caption("本周暂无日志")

    # —— 本月 ——
    _m1, _m2 = logger.month_range()
    _month_logs = logger.read_range(_m1, _m2, namespace=_log_namespace())
    _period_month = f"本月（{_m1.year}年{_m1.month}月）"
    with _pd3:
        if _month_logs:
            if st.button("📄 导出本月日志 (PDF)", key="btn_pdf_month"):
                _gen_report_pdf("month", _period_month, _month_logs)
            _b = st.session_state.get("pdf_month_bytes")
            if _b:
                st.download_button(
                    "⬇ 下载本月 PDF", data=_b, mime="application/pdf",
                    file_name=f"reality_report_month_{_m1.year}{_m1.month:02d}.pdf",
                    key="dl_pdf_month",
                )
            elif st.session_state.get("pdf_month_err"):
                st.caption(f"⚠ {st.session_state['pdf_month_err']}")
        else:
            st.button("📄 导出本月日志 (PDF)", disabled=True, key="btn_pdf_month_dis")
            st.caption("本月暂无日志")


def render() -> None:
    """报告页入口：编排统计与导出区块（app.py 路由调用）。"""
    from ui import render
    st.markdown(
        render.page_intro_html(
            "▥",
            "现实运行报告",
            "查看按会话隔离的日、周、月趋势，并导出可保存的 PDF 复盘。",
        ),
        unsafe_allow_html=True,
    )
    if not st.session_state.get("enable_logging", False):
        st.markdown(
            render.notice_html(
                "日志当前未启用",
                "前往设置开启本地日志后，新编译记录才会进入统计；历史数据不会被删除。",
                "warn",
            ),
            unsafe_allow_html=True,
        )
    _render_log_stats()
    _render_pdf_export()
