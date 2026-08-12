# -*- coding: utf-8 -*-
"""core 包：现实编译器的「引擎层」。

这一层完全不依赖 Streamlit，可以单独用命令行测试，
这样 UI 怎么改都不会影响核心逻辑。

模块划分：
    lexicon.py   —— 词库：把中文日常关键词映射成「游戏事件」
    compiler.py  —— 编译器：文本 -> 事件列表 -> Python 伪代码字符串
    runtime.py   —— 运行时：事件列表 -> 终端日志 + 最终属性结算
"""

# __all__ 声明本包对外暴露的名字，方便 `from core import *`，也方便读者一眼看到入口
__all__ = ["lexicon", "compiler", "runtime", "llm_client"]
