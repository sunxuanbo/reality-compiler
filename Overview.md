# Reality Compiler · 项目概览

把一句现实日常编译成 Python 伪代码、模拟运行、结算属性（HP / MP / 钱包 / 等级）的单页 Web 应用。
技术栈固定为 **Python + Streamlit**，不引入前端框架，不引入数据库。已发布为**纯在线 AI Agent**：编译数据统一由 **DeepSeek API** 实时生成，本地词库已废弃。

## 目录结构

```
reality-compiler/
├── app.py              # 入口 + 路由 + CSS 注入 + session_state 初始化 + 每日世界观状态机
├── requirements.txt    # 依赖：streamlit + requests + python-dotenv + reportlab
├── .env.example        # 环境变量模板（复制为 .env 填 Key）
│
├── core/                     # 【引擎层】纯 Python，不依赖 Streamlit，可单独测试
│   ├── __init__.py           # 包说明与模块导出
│   ├── llm_client.py         # DeepSeek API 封装：事件 / 今日冒险 / 报告 / 反思（Session 复用）
│   ├── schema_validator.py   # Schema 安全门（v2.6）：Pydantic 校验 + JSON 提取 + 修复 + 兜底
│   ├── agent/                # 【Agent 层】v3.0 Phase 2：编排完整编译生命周期
│   │   ├── __init__.py       # 包说明与导出（RealityAgent / Planner / Validator / Reflector）
│   │   ├── planner.py        # 执行计划：输入 + 世界观 + 上下文 → AgentPlan
│   │   ├── validator.py      # 语义校验：格式关（schema）+ 语义关（数量/质量）
│   │   ├── reflector.py      # AI 自我反思：合理性 / 符合人物 / 违规（可降级本地规则）
│   │   └── agent.py          # RealityAgent：Planner→LLM→Validator→Runtime→Reflection
│   ├── database/             # 【数据库层】v3.0 Phase 3：SQLite 存储（零依赖）
│   │   ├── __init__.py       # 包说明与导出（Database / Repository）
│   │   ├── db.py             # 连接管理 + WAL + 三表建表（档案/事件/偏好）
│   │   └── repository.py     # 仓储：档案 upsert / 事件查询 / 偏好权重累计
│   ├── memory/               # 【记忆系统】v3.0 Phase 3：让 Agent 记住用户
│   │   ├── __init__.py       # 包说明与导出（ShortTerm / LongTerm / Retriever）
│   │   ├── short_term.py     # 短期记忆：进程内 FIFO（最近 N 条，不落盘）
│   │   ├── long_term.py      # 长期记忆：SQLite 持久化（档案 / 事件 / 偏好）
│   │   └── retriever.py      # 检索器：组装 Planner 的 context（profile/recent/prefs）
│   ├── simulation/           # 【世界模拟】v3.0 Phase 4：让世界自己发展（事件影响事件）
│   │   ├── __init__.py       # 包说明与导出（SimState / RuleEngine / SimulationEngine）
│   │   ├── state.py          # 隐藏状态 Energy/Stress/SleepDebt + 事件→状态推导
│   │   ├── rules.py          # 声明式规则：状态阈值 → 衍生事件/标签（含内置 3 条）
│   │   └── engine.py         # 模拟引擎：事件→状态→规则→衍生事件编排
│   ├── compiler.py           # 编译器：日常文本 → Python 伪代码 + 告警（build_compile_result 供 Agent 复用）
│   ├── runtime.py            # 运行时：事件列表 → 终端日志 + 属性结算（EXP 截断 + 指数等级曲线）
│   ├── world_config.py       # 世界观转换（AI 生成 JSON → WorldProfile）+ 兜底世界
│   ├── content_provider.py   # 今日冒险供应 + 每日世界观生成器
│   ├── logger.py             # JSONL 本地日志 + 日/周/月统计（需用户开启日志开关）
│   ├── storage.py            # localStorage 数据层（v2.6）：快照构建 / 序列化 / 30 天清理
│   ├── pdf_exporter.py       # PDF 日志报告导出（reportlab 深色终端风格）
│   └── lexicon.py            # 历史词库（仅保留数据结构，已不再是数据来源）
│
├── ui/                       # 【渲染层】纯函数，数据 → HTML 字符串
│   ├── __init__.py           # 包说明
│   ├── render.py             # 标题 / 空状态 / 告警 / 终端 / 属性 / 标签墙 / 反思 / 页脚
│   └── pages/                # 【页面层】app.py 的导航目标（v2.6 由 app.py 拆分）
│       ├── __init__.py       # 包说明与拆分约定
│       ├── home.py           # 主页：标题区 + 输入区 + 编译执行（走 Agent）+ 输出面板
│       ├── settings.py       # 设置页：API Key + 日志开关 + 初始存款
│       └── report.py         # 报告页：日/周/月统计 + PDF 导出
│
├── assets/
│   └── terminal.css          # 终端主题：暗绿底色、磷光绿强调、扫描线质感
│
├── tests/                    # 自检脚本，不依赖 pytest，直接 python 运行
│   ├── test_core.py          # 引擎层自检：编译 / 结算 / API 错误分支 / 今日冒险
│   ├── test_agent.py         # Agent 层自检：Planner / Validator / Reflector / 全链路
│   ├── test_memory.py        # 记忆系统自检：database / short/long term / retriever / Agent 接入
│   ├── test_simulation.py    # 世界模拟自检：state / rules / engine / 规则触发
│   ├── test_app.py           # 界面层自检：Streamlit AppTest 无头跑页面
│   └── run_all.py            # 带超时的全量核查：逐个跑全部套件，超时强杀报 HANG
│
├── archive/
│   └── CHANGELOG.md          # 改动记录（倒序）
│
├── Overview.md               # 本文档
├── Agent.md                  # 给 AI 看的开发约束与决策记录
└── README.md                 # 给人类看的使用说明
```

## 数据是怎么流动的

```
用户输入文本
   │
   ▼
core/agent.RealityAgent.run()  （v3.0 Phase 2/3 Agent 化：编排完整生命周期）
   │
   ├─ 0. 记忆检索（可选，v3.0 Phase 3）   core.memory.MemoryRetriever → context
   ├─ 1. Planner.create_plan()    输入 + 世界观 + 上下文（含记忆）→ AgentPlan
   ├─ 2. LLM（core.llm_client）   按计划调用 DeepSeek → 结构化事件（已过 schema 安全门）
   ├─ 3. Validator.check_data()   语义合理性校验（数量 / 质量 / 修复提示）
   ├─ 4. Runtime（core.compiler.build_compile_result）→ 伪代码 + 告警 + 命中事件
   ├─ 5. Reflector.reflect()      AI 自我反思（合理性 / 符合人物 / 违规）
   ├─ 5.5 SimulationEngine       世界模拟：事件→状态→规则→衍生事件（v3.0 Phase 4）
   └─ 6. 记忆归档（可选）         事件快照 + 标签偏好 → core.database（SQLite）
   │
   ▼
core/runtime.simulate_runtime()  →  终端日志 + 属性结算 + 标签墙
   │
   ▼
ui/render.*_html()  →  HTML 字符串（含「🔎 AI 自我反思」「🌍 世界演化」面板）
   │
   ▼
app.py 用 st.markdown(unsafe_allow_html=True) 拼到页面上
```

兼容性：Agent 链路异常时 `ui/pages/home.py` 回退旧入口 `compile_reality()`，
产物类型均为 CompileResult，渲染层无需改动。记忆默认关闭，开启才读写；
世界模拟默认开启（纯本地计算，不调 LLM 不写存储）。

「生成今日冒险」按钮同理：`content_provider.fetch_daily_event()` → `call_llm_for_daily()` → AI 生成文本；AI 不可用时回退内置素材。

## 速查表：我想改 X，打开哪个文件

| 我想改… | 打开这个文件 | 具体位置 |
| --- | --- | --- |
| 改 AI 系统提示词（数值口径 / 世界观风格） | `core/llm_client.py` | `_build_system_prompt()` / `_build_daily_prompt()` |
| 改默认模型 / API 地址 / 超时 | `core/llm_client.py` | 顶部常量 |
| 改数值范围 / 硬上限 | `core/schema_validator.py` + `core/runtime.py` | 顶部 `HP_MIN` 等常量 / `MAX_EXP_PER_EVENT` |
| 改等级公式 | `core/runtime.py` | `_level_from()` + `MAX_LEVEL` |
| 加一个世界观 | `core/content_provider.py` | `fetch_world()`（AI 生成，无硬编码注册表） |
| 改生成伪代码的样子（import、函数、注释） | `core/compiler.py` | `_render_code()` |
| 加一条编译告警 | `core/compiler.py` | `WARNING_TEXT` |
| 改初始 HP / 可变属性 / 等级 | `core/runtime.py` | 文件顶部常量 + `_level_from()` |
| 改终端里打印的内容与顺序 | `core/runtime.py` | `simulate_runtime()` 里的 `emit(...)` |
| 改 localStorage 快照内容 / 保留天数 | `core/storage.py` | `build_snapshot()` / `MAX_LOG_DAYS` |
| 改配色、字体、间距、扫描线 | `assets/terminal.css` | 顶部 `:root` 变量优先 |
| 改标题栏 / 空状态 / 页脚文案 | `ui/render.py` | 对应的 `*_html()` 函数 |
| 改页面顺序、加新区块 | `app.py` | 第 4 节路由；页面实现在 `ui/pages/*.py` |
| 改快捷样本 | `ui/pages/home.py` | `_render_input_area()` 里的 `SAMPLES` |
| 改伪代码是否默认展开 | `ui/pages/home.py` | `_render_output_area()` 里的 `st.expander(..., expanded=False)` |
| 改模型设置 / 日志开关 / 存款设置 | `ui/pages/settings.py` | `_render_model_settings()` / `_render_logging_settings()` / `_render_deposit_settings()` |
| 改日志统计 / PDF 导出 | `ui/pages/report.py` | `_render_log_stats()` / `_render_pdf_export()` |
| 改每日世界观状态机 / 跨天重置 | `app.py` | 第 3.5 节 |
| 改 localStorage 桥接 | `app.py` | 第 3.6 节 |
| 改执行计划（约束/目标/输出规格） | `core/agent/planner.py` | `create_plan()` |
| 改语义校验规则（数量/质量阈值） | `core/agent/validator.py` | `check_data()` + 顶部常量 |
| 改反思逻辑（AI/本地规则） | `core/agent/reflector.py` | `reflect()` / `_rule_check()` |
| 改 Agent 编排流程 | `core/agent/agent.py` | `RealityAgent.run()` |
| 改反思提示词 / 入口 | `core/llm_client.py` | `_build_reflection_prompt()` / `call_llm_for_reflection()` |
| 改反思面板样式 | `ui/render.py` | `reflection_html()` |
| 改记忆表结构 / 建表 | `core/database/db.py` | `SCHEMA_SQL` |
| 改档案 / 事件 / 偏好读写 | `core/database/repository.py` | 各语义化方法 |
| 改短期记忆容量 | `core/memory/short_term.py` | `ShortTermMemory(capacity=...)` |
| 改记忆检索组装 | `core/memory/retriever.py` | `retrieve()` / `_compact_events()` |
| 改记忆上下文注入提示词 | `core/llm_client.py` | `_build_memory_context_block()` |
| 改隐藏状态推导关键词 | `core/simulation/state.py` | `DEFAULT_DERIVERS` |
| 改规则（阈值/触发事件） | `core/simulation/rules.py` | `DEFAULT_RULES` |
| 改模拟编排 | `core/simulation/engine.py` | `SimulationEngine.simulate()` |
| 改世界演化面板样式 | `ui/render.py` | `simulation_html()` |

## 自检

```bash
python tests/test_core.py       # 引擎层：编译 / 流水号可复现 / 运行时结算 / API 错误分支 / 今日冒险
python tests/test_agent.py      # Agent 层：Planner / Validator / Reflector / RealityAgent 全链路
python tests/test_memory.py     # 记忆系统：database / short/long term / retriever / Agent 接入
python tests/test_simulation.py # 世界模拟：state / rules / engine / 规则触发衍生事件
python tests/test_app.py        # 界面层：首屏 / 空输入拦截 / 完整编译 / 清空 / 每日世界
python tests/run_all.py         # 带超时的全量核查：逐个跑上面全部套件，超时强杀并报 HANG
```
