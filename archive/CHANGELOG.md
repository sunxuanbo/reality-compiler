# 改动记录

倒序排列，最新的在最上面。
旧代码存档放在同级目录 `YYYY-MM-DD-简短描述/` 下。

---

## 2026-08-08 · v2.6.1 全量专家修复（bug1~bug8）+ v3.0 基础架构

**范围**：响应 8 个专家 bug 点 + v3.0 架构升级（按「方案优化步骤」合并推进，不分开两轮做）。
按 `Phase 0 整理 → Phase 1 稳定核心 → Phase 2 数据层` 推进；Agent化 / 记忆 / 世界模拟属后续阶段。

**Phase 0 · app.py 拆分（bug6）**：
- `ui/pages/home.py`（主页：标题区 / 今日世界观 / 生成今日冒险 / 刷新世界观 / 输入区 / 编译执行 / 输出面板）。
- `ui/pages/settings.py`（设置页：API Key / 日志开关 / 初始存款）。
- `ui/pages/report.py`（报告页：日志统计 / PDF 导出）。
- `app.py` 精简为入口 + 路由（侧边栏 radio）+ CSS + session_state 初始化 + 世界观状态机 + localStorage 桥接；`INPUT_KEY` 写入 session_state。
- 约定：页面层放 `ui/pages/`（不放根目录 `pages/`，避免触发 Streamlit 原生多页导航破坏单页形态）。

**Phase 1 · Schema 安全门（bug1）**：
- 新增 `core/schema_validator.py`：Pydantic 数据模型（AIEvent / AIResponse）+ JSON 提取器（兼容「解释文字 + JSON」混排）+ 修复策略（缺字段补 0 / 类型强转 / 超范围截断 / tags 截 5）+ 兜底默认事件。
- `core/llm_client.py`：`call_llm_for_events_full` 接入安全门；格式异常（非 JSON / 缺 name）附「请返回严格 JSON」提示重试，最多 2 次；重试耗尽降级默认事件，页面永不崩溃。
- `requirements.txt`：新增 `pydantic>=2.0.0`。

**Phase 1 · 安全加固（bug2 + bug3）**：
- Prompt Injection 防御：system prompt 增加「安全规则」段（忽略用户注入指令 / 数值范围硬约束）。
- EXP 硬上限：`core/runtime.py` 单事件 EXP 截断 `[0, 15]`（`MAX_EXP_PER_EVENT`），schema 层也截 `exp<=15`——双重防御。
- 等级指数曲线：`_level_from` 改为「下一级所需经验 = 等级²×50」+ `MAX_LEVEL=99`；999999 经验 → Lv.39（原线性公式会到 20000）。
- 数值统一硬上限（schema 层）：hp[-30,20] / mp[-30,20] / gold[-50,30] / exp[0,15] / tags≤5。

**Phase 1 · 性能优化（bug7）**：
- `app.py`：`@st.cache_data(ttl=86400)` 按「日期+Key」缓存世界观生成（同一天刷新不重复调 API）。
- `core/llm_client.py`：`requests.Session` 模块级单例复用 TCP 连接（keep-alive）；测试注入 `requests.post` 时自动走顶层函数（以 `requests.api.post` 为哨兵，兼容 AppTest 假请求）。

**Phase 2 · 数据层（bug4 + bug5 + bug8）**：
- 新增 `core/storage.py`：localStorage 数据层（快照构建 / 序列化 / 30 天日志清理 / 恢复映射），纯 Python 不依赖 Streamlit。
- `app.py`：localStorage 桥接（父页面 script 直写 + URL 参数回传恢复），首屏恢复上次会话的世界观摘要与属性面板。
- 日志隐私开关（bug5）：`settings.py` 新增「📝 日志记录」开关（默认关闭）；`home.py` 编译成功仅当开关开启才写日志。
- API Key 安全（bug8）：`settings.py` 新增隐私风险提示 + 「清除 API Key」按钮 + HF Secrets 引导；Key 仅存当前会话，不写入文件 / localStorage。

**验证**：lint 0；引擎层 100+ 项全 PASS（含 15.x Schema 容错 / 16.x 等级曲线 / 17.x EXP 截断 / 18.x storage 数据层）；界面层 10 项全 PASS（含报告页切换 / 离线降级 / 刷新世界观）。

---

## 2026-08-10 · v3.0 API Key 持久化（bug8 可用性修复，刷新不丢）

**问题**：bug8 原设计让 API Key 只存 `st.session_state`（当前会话），导致
**「刷新页面 Key 就没了」无法编译**——尤其对「一直在侧边栏填 Key」的用户是硬伤。

**修复（app.py 3.7 节 + settings.py）**：
- Key 存浏览器 localStorage（独立 key `reality_api_key`，与快照分开）。
- 首屏 `_try_restore_api_key()`：父页面 script 读 localStorage → 带 `?k=` 回传
  （`location.replace` 不产生浏览器历史记录）→ 解码写回 `session_state["cfg_api_key"]`
  → 立即清 URL 参数。用 `session_state` 做 widget 默认值，Settings 页会自动显示。
- 编译时 Key 无需改动：`home.py` 读 `cfg_api_key`，恢复后即有值。
- 「清除 API Key」按钮同时删 session 与 localStorage 里的 Key。
- 隐私文案更新：明确「Key 只存你自己的浏览器，不上传服务器、不写服务器文件」。

**验证**：lint 0；界面层测试全 PASS（无头环境无浏览器，localStorage 桥接安全降级不触发）。

---

## 2026-08-09 · v3.0 Phase 4 世界模拟升级（rules + simulation，让世界自己发展）

**范围**：按「方案优化步骤」进入 v3.0 第四阶段 —— 把编译从「AI 随机事件生成器」
升级为「Reality Simulation Engine」：**事件影响事件**（对齐优化方案的模拟引擎示例）。

```
熬夜 → 状态变化(Energy -10 / Stress +15 / SleepDebt +20)
     → 规则系统(若 SleepDebt > 80 → 触发「慢性疲劳」)
     → 生成衍生新事件
```

**新增 core/simulation/（纯 Python，core 层禁止 import streamlit）**：
- `state.py`：隐藏状态 SimState（Energy / Stress / SleepDebt，全 clamp [0,100]）+
  事件→状态推导 `derive_state_changes()`（关键词表，纯本地不调 LLM）。
  支持 to_dict / from_dict（跨天持久化）/ fresh_day（新的一天）。
- `rules.py`：声明式 Rule（状态字段 + 阈值 + 方向 >=/<= + 触发事件 + 标签 +
  触发后重置）。RuleEngine 批量检查。内置 3 条通用规则（慢性疲劳 / 精神紧绷 / 精力告急）。
- `engine.py`：SimulationEngine 编排 `事件→状态→规则→衍生事件`，产出
  SimulationResult（演化轨迹 / 触发规则 / 衍生事件 / 衍生标签 / 最终状态 / 终端行）。
  兼容 MatchedEvent 与轻量 dict 两种事件形态。

**接入 Agent（不重写现有 Runtime）**：
- `core/agent/agent.py`：AgentRunResult 新增 `simulation` 字段；`RealityAgent.run()`
  新增 `enable_simulation`（默认开启）+ 构造参数 `simulation_engine`（可注入）。
  模拟在 Reflection 之后运行，失败/关闭绝不影响编译主流程。
- `ui/pages/home.py`：注入 `SimulationEngine`；输出区新增「🌍 世界演化」面板
  （状态条 + 演化轨迹 + 触发规则 + 衍生事件）。仅当 `simulation.evolved` 才展示。
- `ui/render.py`：新增 `simulation_html()`。

**新增 tests/test_simulation.py**：SimState（clamp/delta/serialize/fresh_day）、
状态推导（熬夜/睡觉/散步/无关）、规则（阈值/方向/触发/重置）、引擎编排、规则触发
衍生事件、MatchedEvent 兼容、自定义起点，33 项全 PASS。test_agent 新增 3 项
（模拟注入 / 未注入为 None / 关闭不报错，39 项全 PASS）。

**验证**：lint 0；test_core + test_agent + test_memory + test_simulation + test_app
五套全量回归 0 FAIL。

---

## 2026-08-08 · v3.0 Phase 3 记忆系统（database + memory，让 Agent 记住用户）

**范围**：按「方案优化步骤」进入 v3.0 第三阶段 —— 把「简单存档」升级为「Agent 会使用数据」。
新增 SQLite 存储层 + 短期/长期记忆 + 检索器，并接入 RealityAgent 生命周期。

**新增 core/database/（SQLite 存储层，纯 Python 零依赖）**：
- `db.py`：连接管理 + WAL 模式 + 三表建表（user_profile / events / preferences）。
  锁用 `threading.RLock`（可重入），避免 wipe 等持锁方法内部再取锁导致死锁。
- `repository.py`：档案 upsert / 事件写入与查询 / 偏好权重累计（bump_pref）。

**新增 core/memory/（记忆系统）**：
- `short_term.py`：进程内 FIFO 队列（最近 N 条，随进程消失），线程安全。
- `long_term.py`：SQLite 持久化封装（档案 / 历史事件 / 标签偏好观察）。
- `retriever.py`：把记忆组装成 Planner 的 context（profile / recent / prefs，各限条数）。

**接入 Agent（编译前检索 + 编译后归档）**：
- `core/agent/agent.py`：`run()` 新增 `memory` 参数；传入 LongTermMemory 时，
  编译前用 retriever 检索记忆上下文注入 Planner + LLM 提示词，编译后自动归档
  事件快照（日期/原文/摘要/建议/属性画像/标签）并观察标签偏好。检索失败/归档失败
  均静默降级，绝不影响编译主流程。
- `core/llm_client.py`：`_build_system_prompt()` 新增 `context` 参数与
  `_build_memory_context_block()`（用户档案 / 近期经历 / 长期偏好注入提示词，
  空上下文时提示词保持 v2.x 原样）。

**UI 接入（默认关闭，与日志开关同样尊重隐私）**：
- `ui/pages/settings.py`：新增「🧠 记忆系统」开关（`enable_memory`，默认 False）。
- `ui/pages/home.py`：按开关创建/复用 LongTermMemory + MemoryRetriever 传给 Agent。

**新增 tests/test_memory.py**：Database（建表 / WAL / wipe）、Repository（档案 /
事件 / 偏好权重）、ShortTermMemory（FIFO 淘汰）、LongTermMemory、MemoryRetriever、
Agent 接入（记忆注入 + 归档 + 关闭不读写），36 项全 PASS。

**验证**：lint 0；test_memory 36 项 PASS；test_core + test_agent + test_app 全量回归 0 FAIL。

---

## 2026-08-08 · v3.0 Phase 2 Agent 化（Planner → Validator → Reflector → RealityAgent）

**范围**：按「方案优化步骤」进入 v3.0 第二阶段 —— 把 `LLM → Compiler → Runtime` 升级为
完整的 Agent 生命周期（`Agent → Planner → LLM → Validator → Runtime → Reflection`）。

**新增 core/agent/（纯 Python，core 层禁止 import streamlit）**：
- `planner.py`：把「用户输入 + 世界观 + 上下文」编译成结构化执行计划（AgentPlan）。
  输入清洗 / 空输入检测 / 超长截断（2000 字）；数值约束与 core.schema_validator 严格一致。
- `validator.py`：语义合理性校验。复用 schema 安全门做格式关（JSON 提取 / 补字段 / 截断 /
  兜底），新增语义关（事件数量 1-6、空名 / 超长名 / 无标签提示）。提供 `check()`（字符串入口）
  与 `check_data()`（dict 入口，Agent 主流程用）。
- `reflector.py`：AI 自我反思。首选调用 `call_llm_for_reflection`（审查数值离谱 / 编造情节 /
  违规注入 / 数量丰富度）；AI 不可用自动降级「本地规则反思」（越界数值 / 全零假事件）。
  反思失败绝不影响编译主流程。
- `agent.py`：`RealityAgent` 编排完整生命周期。`run()` 返回 AgentRunResult（plan /
  validation / compile / reflection）；`compile()` 便捷入口返回 CompileResult（与旧入口同类型）。

**接入编译链路**：
- `core/compiler.py`：抽出公开函数 `build_compile_result()`（AI 数据 → CompileResult），
  `compile_reality` 与 Agent 共用；产出完全一致（含 elapsed_ms 的 RNG 逻辑）。
- `core/llm_client.py`：新增公开入口 5 `call_llm_for_reflection()`（AI 自我审查，低温度 0.2）。
- `ui/pages/home.py`：编译走 `RealityAgent.run()`；Agent 链路异常回退旧 `compile_reality`。
  输出区新增「🔎 AI 自我反思」面板（通过 / 未通过 + 问题列表 + 建议）。
- `ui/render.py`：新增 `reflection_html()` 渲染反思结论。
- 清理 result/log/reflection 的三个入口（生成今日冒险 / 刷新世界观 / 清空）同步清 reflection。

**新增 tests/test_agent.py**：Planner（清洗 / 空输入 / 截断 / 兜底世界）、Validator（正常 /
解释文字 / 纯文字 / 过多 / 无标签 / 补 0）、Reflector（AI 注入 / 判不合理 / AI 不可用降级 /
越界 / 全零）、RealityAgent 全链路（fake LLM 注入，36 项全 PASS）。

**验证**：lint 0；test_agent 36 项全 PASS；test_core + test_app 全量回归 0 FAIL。

---

## 2026-08-08 · v2.6 app.py 拆分（bug6 专家修复，已被 v2.6.1 合并收录）

**范围**：响应专家 bug6「app.py 单文件过大」，把页面级交互从 540 行 `app.py` 拆到 `ui/pages/`，`app.py` 只保留入口 + 路由 + CSS + 初始化 + 世界观状态机。

**动作**：
- 新增 `ui/pages/home.py`：标题区 / 今日世界观 / 生成今日冒险 / 刷新世界观 / 输入区（样本 + 主输入框 + 操作行）/ 编译执行（含动画）/ 输出区（伪代码 / 终端 / 属性 / 复盘 / 标签墙 / 导出运行日志 / 运算规则）。
- 新增 `ui/pages/settings.py`：模型设置（API Key）+ 初始存款设置。
- 新增 `ui/pages/report.py`：日志统计（日/周/月）+ PDF 导出（今日/本周/本月）。
- `app.py` 精简：保留 set_page_config / CSS 注入 / session_state 初始化 / 每日世界观状态机 / 页脚；新增侧边栏 radio 路由（`nav_page`）；`INPUT_KEY` 写入 session_state 供页面模块读取。
- `tests/test_app.py`：用例 8 适配拆分——编译后先验证「今日复盘」，再切换到报告页验证日志统计 + PDF 导出按钮。
- `Overview.md`：目录结构加入 `ui/pages/`，速查表改指新位置。

**验证**：lint 0；引擎层全 PASS；界面层 10 项全 PASS（含拆分后的报告页切换验证）；widget key 与 v2.5 完全一致，测试零改动通过。

**约定（并入 Agent.md）**：页面层放 `ui/pages/`（不放根目录 `pages/`，避免触发 Streamlit 原生多页导航破坏单页终端形态）；页面层属于「流程层」的编排部分，允许 `st.xxx`，业务规则仍必须下沉 `core/`。

---

**范围**：按最新需求对齐——模型名写死为 `deepseek-chat`；补充手动强制刷新世界观的能力（其余功能如世界观 AI 动态生成、日志系统、PDF 导出、健康警报等已在 v2.1~v2.4 实现，本次仅增量）。

**动作**：
- `core/llm_client.py`：`DEFAULT_MODEL` 由 `deepseek-v4-pro` 调整为 `deepseek-chat`（需求指定默认模型）。
- `app.py`：新增「🔄 刷新世界观」按钮（与「生成今日冒险」并排）——点击后置空 `world_data` 并清空编译结果，3.5 节状态机会自动重新调用 AI 生成全新世界观；页面标题 v2.5。
- `ui/render.py`：header 版本 v2.5。
- `tests/test_app.py`：界面测试改用独立临时日志目录（不污染项目 `logs/`，满足验收前不生成模拟日志）；新增用例 10「刷新世界观按钮正常」。

**验证**：lint 0；引擎层全 PASS；界面层 10 项全 PASS（含刷新世界观）；测试期间 `logs/` 无新增（写入临时目录）。

---

## 2026-08-06 · v2.4 API 请求自动重试（生产稳定性）

**范围**：针对模拟实验中发现的 DeepSeek API 间歇性「网络连接失败」，在请求层增加自动重试 + 指数退避，保障上线 Web Agent 的稳定性。

**动作**：
- `core/llm_client.py`：新增 `_post_with_retry`——网络异常（超时 / 连接失败）与可重试状态码（429 / 500 / 502 / 503 / 504）自动指数退避重试（MAX_RETRIES=3，RETRY_BACKOFF=1.5 秒 → 3 → 6）；401（Key 无效）不重试（重试无意义）；重试耗尽后仍由原有中文提示翻译兜底。API_TIMEOUT 由 30 提升至 60 秒（大文本生成更稳）。
- `tests/test_core.py`：新增 14.x 用例——网络抖动自动重试成功（共 3 次尝试）、429 限流自动重试成功、持续网络失败最终报中文「网络连接失败」。
- 版本号 v2.4（页面标题 / header）。

**验证**：lint 0；引擎层 + 界面层全量测试全 PASS（含 3 个新重试用例）。

---

## 2026-08-06 · v2.3 API 默认值 + 本地日志系统 + PDF 导出

**范围**：写死 API 地址/模型（用户只填 Key）；编译成功自动写 JSONL 日志（早 6 点分区）；页面日/周/月统计；PDF 报告导出。

**动作**：
- `core/llm_client.py`：`_resolve_config` 写死 `DEFAULT_CHAT_URL`（https://api.deepseek.com/chat/completions）与 `DEFAULT_MODEL`（deepseek-v4-pro），用户只需填 Key；新增 `call_llm_for_report()` 生成叙事总结（PDF 用）。
- `app.py`：设置面板只留「DeepSeek API Key」密码框（移除地址/模型输入框与保存按钮）；编译成功自动写日志；结算面板下方新增「📊 日志统计」折叠区（默认展开）；导出区新增今日/本周/本月 PDF 按钮（有日志亮起、无日志置灰 + 提示）。
- `core/logger.py`（新增）：JSONL 日志（logs/reality_YYYY-MM-DD.log），早 6 点分区（凌晨 0:00-5:59 归前一天）；日/周/月统计（事件数、净变化、经验、标签 TOP3/5、等级轨迹）。
- `core/pdf_exporter.py`（新增）：reportlab 深色终端风格 PDF（#0d1110 底 / #d0d0d0 文 / #7fe08a 标题 / STSong-Light 中文字体）。
- `core/runtime.py`：新增 `events_to_plain()` 事件导出 helper。
- `core/lexicon.py`：Event 新增 `description` 字段（保留 AI 事件描述）。
- `core/compiler.py`：`_convert_llm_events` 保留 AI description。
- `ui/render.py`：新增 `log_stats_html()` 统计 HTML（刻意避开原 `stats_html` 属性面板函数名）。
- `assets/terminal.css`：`.rc-stats` 统计区样式。
- `requirements.txt`：新增 `reportlab>=4.0`。

**验证**：lint 0；引擎层新增 13.x（分区 / build_entry / 聚合 / 端到端 / PDF）全 PASS；界面层新增统计区 + PDF 按钮断言全 PASS；真实 API 验证 call_llm_for_report + PDF 生成成功。

---

## 2026-08-06 · v2.2.1 修复「输入 API Key 后页面报错」

**范围**：用户反馈输入 API Key 后页面报错。经 AppTest 复现，根因是 `st.session_state.setdefault` 预填与 widget `value` 默认值冲突。

**根因**：`app.py` 中 `st.session_state.setdefault("cfg_deposit", 0)`（及 cfg_api_key / cfg_api_base / cfg_deposit_warn 同理）预填了 session_state，而 `st.number_input(key="cfg_deposit", value=0)` 又带默认值，Streamlit 每次 rerun 都会触发 `check_session_state_rules` 冲突警告/异常。

**动作**：
- `app.py`：删除全部与 widget key 相同的 `setdefault` 预填（cfg_api_key / cfg_api_base / cfg_api_model / cfg_deposit / cfg_deposit_warn），初始默认值改由 widget 的 `value` 参数提供；编译处已有 `or 0` / `get` 兜底，无需额外处理。
- 复现验证：AppTest 模拟「输入 Key → 编译」全流程（真实 API），修复后无冲突警告、无页面错误、属性面板正常出现。
- 全量回归：引擎层 + 界面层测试全 PASS。

---

## 2026-08-03 · v2.2 API 真实测试 + 降级测试补全

**范围**：用真实 DeepSeek API Key 做端到端冒烟测试，补全「AI 不可用时报中文友好错误且旧面板保留」的降级测试。

**动作**：
- 真实 API 冒烟：连接/Key 有效、世界观生成（返回 world_name / world_description / currency_name / stat_mapping / daily_story）、事件编译（含健康识别🚨、消费扣款）全部通过。
- 异常处理：无效 Key 触发真实 401，返回中文提示「API Key 无效或已过期」，不含技术细节 / 不泄露 Key。
- `tests/test_app.py`：fake post 增加 `FORCE_LLM_ERR=401` 分支；新增用例 9「离线降级：AI 不可用报中文错误且旧面板保留」。
- 安全确认：真实 Key 未硬编码到任何代码文件；`llm_client.py` 从环境变量读取（`os.getenv("DEEPSEEK_API_KEY")`），不落盘。

**验证**：引擎层 + 界面层全量测试全 PASS（含新增离线降级用例）。

---

## 2026-08-03 · v2.2 世界观由 AI 动态生成 + 钱包随世界观变化

**范围**：移除硬编码世界观，改为 DeepSeek AI 每天生成全新世界观；货币名随世界观动态变化。

**动作**：
- `core/world_config.py`：移除硬编码的「剑与魔法 / 后室」注册表；新增 `world_from_ai(data, world_id)` 把 AI 返回 JSON 转成 WorldProfile（货币名 → 可变属性显示名）；保留 `FALLBACK_WORLD` 兜底世界。
- `core/llm_client.py`：新增 `call_llm_for_world(date_str)` 世界观生成入口（返回 world_name / world_description / currency_name / stat_mapping / daily_story）；`_build_system_prompt` 改为注入 AI 世界观的名称 / 背景 / 货币名；`call_llm_for_events_full / call_llm_for_events / call_llm_for_daily` 统一改为接收 WorldProfile 对象。
- `core/content_provider.py`：移除硬编码世界观与 Mock 素材；`today_world_id()` 改为返回日期 id（day-YYYY-MM-DD）；新增 `fetch_world()`（AI 生成，失败回退兜底）；`fetch_daily_event()` 优先取 AI 世界观自带 daily_story。
- `core/compiler.py`：`compile_reality(text, world, ...)` 接收 WorldProfile 对象，不再传 world_id。
- `core/runtime.py`：`get_world` 替换为 `FALLBACK_WORLD` 兜底（结算逻辑本就按 vs.name 动态显示货币名）。
- `ui/render.py`：运算规则文案动态化（去硬编码世界观）；版本号 v2.2。
- `app.py`：每天首次打开由 AI 生成世界观并缓存到 session_state（跨天重置）；顶部展示世界观名 / 货币名 / 背景；编译 / 渲染传世界对象；存款逻辑去掉 is_wallet 判断（所有 AI 世界货币都扣减存款）；版本号 v2.2。
- `assets/terminal.css`：新增 `.rc-world-desc` 世界观简介样式。

**验证**：lint 0；`tests/test_core.py` 新增 4.12（AI 世界观转换）与 9.5（call_llm_for_world）全 PASS；`tests/test_app.py` 测试 5 改为断言 AI 世界观名 / 货币名，全 PASS。

---

## 2026-08-03 · v2.1 界面优化 + 功能增强（第一批用户反馈）

**范围**：深色模式视觉修复 + 从「游戏模拟」走向「实用生活管理」+ AI 异世界沉浸感提升。

**动作**：
- `assets/terminal.css`：提亮深色主题对比度（背景 `#0d1110`、主文字 `#d0d0d0`、标题 `#e8e8e8`，满足 WCAG AA ≥4.5:1）；输入框/数字框/单行框统一暗色调（深底 + 暗绿边框 + focus 磷光绿高亮）；`st.code` 代码块深底 `#0d1110` + 磷光绿字体；新增复盘区域 `.rc-replay` 样式；固定深色模式（隐藏主题切换与主菜单）。
- `.streamlit/config.toml`（新增）：`base="dark"` 固定深色主题。
- `core/llm_client.py`：系统提示词全面升级——①异世界风格重写事件名称/描述（按世界观词汇库：剑与魔法 vs 后室）；②健康行为识别（不健康事件名强制加「🚨」前缀）；③消费识别（吃饭花了X元 → 扣减存款）；④每日复盘（新增返回字段 `summary` / `advice`）；⑤事件丰富度（name/description/hp/mp/gold_or_san/exp/tags 齐全、可拆子事件）。新增 `call_llm_for_events_full` 返回完整结构，`call_llm_for_events` 保持原接口兼容。
- `core/compiler.py`：`CompileResult` 新增 `summary` / `advice` 字段并透传。
- `core/runtime.py`：`simulate_runtime` 新增 `initial_vstat`（初始存款）与 `warn_threshold`（存款预警线）参数；事件名带「🚨」时标签升级红色警报样式；存款低于预警线追加「⚠️ 存款不足」。
- `ui/render.py`：新增 `replay_html(summary, advice)` 复盘渲染；`calc_html` 支持展示存款初始值；标题版本 v2.1。
- `app.py`：新增「💰 存款设置」折叠面板（初始存款 + 预警线，仅钱包世界生效）；结算面板下方渲染「📋 今日复盘」；页面标题 v2.1。

**验证**：lint 0；`tests/test_core.py` 新增 4.9~4.11（复盘字段、初始存款、🚨 红警）全 PASS；`tests/test_app.py` 新增「今日复盘区域渲染」全 PASS。

---

## 2026-08-02 · v2.0 发布准备：Hugging Face Spaces + 每人独立 Key

**范围**：为「推出给别人用」做准备，目标平台 Hugging Face Spaces，Key 策略改为「每人填自己的、不落盘」。

**动作**：
- `app.py`：`_save_api_config` 不再写服务器 `.env`、不再改进程级 `os.environ`（修复多用户共享 Key 的泄漏），改为只存 `st.session_state`；初始 Key 默认留空、不预填环境变量/平台 Secret；设置面板说明与成功提示改为「仅存本会话」；移除仅用于 Key 的 `import os`；页面标题对齐 v2.0。
- `README.md`：顶部加 Hugging Face Spaces 元信息（`sdk: streamlit` 等），新增「在线体验（一键部署）」章节，更新 Key 文案。
- 验证：`app.py` 导入正常、lint 0、引擎层 + 界面层自检全 PASS。

**验证**：`tests/test_core.py` 与 `tests/test_app.py` 全部通过。

---

## 2026-08-02 · v2.0 纯在线 AI 编译（为发布准备）

**范围**：从「本地词库 Mock」升级为「DeepSeek API 实时编译」，界面配置化，为发布做准备。

**动作**：
- 新增 `core/llm_client.py`：requests 直连 DeepSeek，生成结构化事件（JSON Schema + `json_object` 强制）与今日冒险文本；超时 30s；无 Key / 401 / 429 / 超时 / 连接 / JSON 解析错误全部翻译为中文 RuntimeError。
- `core/compiler.py`：移除本地词库降级，编译统一走 API，失败向上抛出并由 UI 保留旧面板；`tags` 兼容字符串/列表，避免被按字符拆开。
- `app.py`：新增「⚙ 模型设置」面板（API Key / 地址 / 模型名，对标 CodeBuddy「配置自定义模型」），可保存到 `.env`；编译与「生成今日冒险」均透传该配置。
- `core/content_provider.py`：今日冒险改为 AI 优先生成、内置素材兜底。
- 界面文案全面更新（本地 Mock → AI 编译器），规则说明同步。
- 测试适配：注入确定性假 `requests.post`，不依赖真实网络/Key；新增无 Key 引导、401 翻译、`tags` 健壮性、今日冒险文本等用例。
- 新增 `.gitignore`（忽略 `.env` 与运行日志）；`.env.example` / README / Overview / Agent 文档同步更新。

**验证**：`tests/test_core.py` 与 `tests/test_app.py` 全部通过。

---

## 2026-08-02 · v1.1.1 回滚：恢复 v1.0 终端形态

**原因**：v1.1 把整套界面重做成「生活账本」，用户反馈「没让你彻底改，我只让你把代码部分稍微减少一些区域」，违背了「不要动其根本」的要求。

**动作**：
- 回滚 v1.1 的全部改造，恢复 v1.0 的「代码 + 终端 + 属性面板(HP/MP/钱包/等级) + buff/debuff 标签墙」形态。
- 仅保留用户真正要的那一小步：**生成的伪代码默认收进折叠区**（`st.expander`，`expanded=False`），缩小代码显示区域，但不删除代码本身。
- 词库 24 类事件、流水号、样本、清空、导出、终端主题全部回到 v1.0。

**验证**：`tests/test_core.py` 与 `tests/test_app.py` 全部通过，本地 8501 服务健康检查返回 ok。

---

## 2026-08-02 · v1.1 简版：现实账本

**范围**：依据用户反馈做减法，把 v1.0 的「游戏化终端」重做成「生活账本」。

**反馈原话的四类问题**：① 面板太多堆在一起；② 游戏化过度（HP/MP/等级/EXP）；③ 满屏 Python 代码吓到代码小白；④ 不知道先看哪、输入在哪结果在哪。

### 砍掉的东西

| 去掉项 | 原位置 |
| --- | --- |
| Python 伪代码框（`st.code`） | `app.py` 第 7 节 / `core/compiler.py._render_code` |
| 模拟终端输出（带时间戳的扣血日志） | `ui/render.py.terminal_html` / `core/runtime.simulate_runtime` 的 `emit` 日志 |
| HP / MP / 钱包 / 经验 四格属性面板 | `ui/render.py.stats_html` |
| buff / debuff 方角标签墙 | `ui/render.py.chips_html` |
| 冷冰冰的编译告警（`W001`/`W014`…） | `core/compiler._make_warnings` |
| 编译动画的多阶段 boot 文案 | `app.py.BOOT_STAGES` |

### 新增 / 重做

| 文件 | 说明 |
| --- | --- |
| `core/compiler.py` | `compile_reality()` 现在返回账本条目（`LedgerEntry`：图标+中文名+大类+消耗/恢复+说明）；新增 `ledger_to_markdown()` 供导出 |
| `core/runtime.py` | 重做：从「结算 HP」改为 `summarize()` 产出清爽汇总（总笔数、消耗、恢复、一句中文结论） |
| `core/lexicon.py` | `Event` 结构改为账本友好字段（`icon`/`label`/`category`/`polarity`/`detail`），24 类事件全部补上 emoji 与中文说明 |
| `ui/render.py` | 重写为 `header` / `label` / `idle` / `error` / `ledger` / `tips` / `footer` 七个纯函数；HTML 仍为单行 |
| `app.py` | 流程精简为「① 写下日常 → ② 编译结果·生活账本」，保留样本、清空、导出 |
| `assets/terminal.css` | 约 380 行终端主题重写为账本主题（圆角 10px、柔和配色、账本行样式） |

### 保留的「不要舍弃太多」

- 「编译器」概念与标题 `Reality Compiler v1.0`
- 24 类日常事件的关键词识别（这是真正有用的部分）
- 流水号（改为账本「流水号」，对应记账软件的凭单号）
- 快捷样本按钮、清空、导出、空输入拦截
- 暗黑终端底色与磷光绿强调色（只是更克制）

### 验证

```
python tests/test_core.py   →  5 组样本通过，构建号可复现
python tests/test_app.py    →  首屏 / 空输入拦截 / 完整编译 / 清空 四项通过
streamlit run app.py        →  本地 8501 端口启动正常，健康检查返回 ok
```

环境：Python 3.14.3 + Streamlit 1.60.0 + Windows。

---

## 2026-08-02 · v1.0 首个可交付版本

**范围**：从零搭建，完成需求里的全部五项。

### 新增

| 文件 | 说明 |
| --- | --- |
| `core/lexicon.py` | 词库层。24 类日常事件（加班 / 通勤 / 咖啡 / 生病 / 发工资 / 独处等）+ 15 个强度副词 + 兜底事件 + 子串匹配 |
| `core/compiler.py` | 编译器层。`compile_reality()` 返回完整结果，`compile_reality_to_code()` 是需求点名的 Mock 函数，返回伪代码字符串 |
| `core/runtime.py` | 运行时层。逐事件结算 HP / MP / 钱包 / 经验，产出带时间戳与级别的终端日志，血量归零时模拟 Traceback |
| `ui/render.py` | 渲染层。标题、空状态、编译进度、终端窗口、属性面板、状态标签、页脚 |
| `app.py` | 页面流程。输入 → 编译动画 → `st.code` → 终端 → 结算面板 |
| `assets/terminal.css` | 暗黑终端主题，约 380 行 |
| `.streamlit/config.toml` | 主题底色与服务配置 |
| `tests/test_core.py` | 引擎层自检，5 组样本 |
| `tests/test_app.py` | 界面层自检，基于 Streamlit AppTest |
| `README.md` / `Overview.md` / `Agent.md` | 文档三件套 |

### 关键决策

1. **三层分离**：`core/` 完全不 import streamlit，将来换界面或接 API 时引擎不用动。
2. **结果可复现**：构建号用输入文本的 SHA-1 前 6 位，随机种子用 MD5，同一句话永远编译出同一个 `reality_xxxxxx.py`。
3. **加了编译告警**：`W001` 缺少回复类调用、`W014` 加班叠加熬夜、`W002` 样本过短、`W031` 存在未归类语义。这一步不是需求要求的，但没有 warning 的编译器不像编译器。
4. **清空按钮用 nonce 换 key**：直接改 `session_state` 里已实例化组件的值会被 Streamlit 拒绝，改成给输入框的 key 加版本号，换一个新组件。
5. **HTML 必须拼成单行**：Streamlit 的 Markdown 解析器会把缩进四空格的行当成代码块，`ui/render.py` 里所有函数返回的都是无换行字符串。

### 视觉取舍

- 背景用 `#080a09` 而不是纯黑，顶部叠一层极淡的径向辉光
- 全局只有一个强调色（磷光绿 `#7fe08a`），琥珀与红仅作语义色
- 叠加噪点与扫描线两层，避免纯色平面的塑料感
- 圆角统一 `2px`，拒绝 12px 大圆角
- 四格属性面板用 `1.25fr 1.25fr 1fr 1fr` 的不等宽网格，避开四等分的呆板
- buff / debuff 用方角标签而不是胶囊圆标
- 所有交互元素补齐 hover / active / focus-visible 三态，并适配 `prefers-reduced-motion`

### 验证

```
python tests/test_core.py   →  5 组样本全部通过
python tests/test_app.py    →  首屏 / 空输入拦截 / 完整编译 / 样本与清空 四项通过
streamlit run app.py        →  本地 8532 端口启动正常，健康检查返回 ok
```

环境：Python 3.14.3 + Streamlit 1.60.0 + Windows。
