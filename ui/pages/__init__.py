# -*- coding: utf-8 -*-
"""页面层：app.py 的导航目标模块（v2.6）。

按 bug6 拆分约定，app.py 只保留「入口 + 路由 + CSS + session_state 初始化」，
把页面级交互拆到本包：

    ui/pages/home.py       主页：标题区 + 输入区 + 编译执行 + 输出面板
    ui/pages/settings.py   设置页：API Key / 初始存款
    ui/pages/report.py     报告页：日/周/月统计 + PDF 导出

本层属于「流程层」的页面编排部分：允许使用 st.xxx 组件，
但业务规则仍必须下沉到 core/（引擎层）。
"""
