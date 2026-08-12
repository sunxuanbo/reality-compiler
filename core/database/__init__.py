# -*- coding: utf-8 -*-
"""数据库层（v3.0 Phase 3 · 记忆系统的底座）：SQLite 存储。

设计（对齐优化方案）：
    - 底层用 Python 标准库 sqlite3，零第三方依赖；
    - 表结构覆盖「用户档案 / 历史事件 / 长期偏好」三张核心表；
    - 全部读写收敛在 repository.py，上层（memory / agent）不直接写 SQL。

分层约定（Agent.md 铁律）：
    本包属于 core/ 引擎层，纯 Python，【禁止 import streamlit】。

对外主要暴露：
    Database（core.database.db）      连接管理 + 建表 + 路径
    Repository（core.database.repository） 档案 / 事件 / 偏好的增删查改
"""

from .db import Database, default_db_path   # noqa: F401
from .repository import Repository           # noqa: F401

__all__ = ["Database", "Repository", "default_db_path"]
