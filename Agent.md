# Agent.md — 协作约定

> 这份文档写给「下一个改这个项目的人」，包括 AI Agent 和三个月后的自己。
> 动手改代码之前，先读完这一页。

## 1. 这个项目是什么

Reality Compiler：把一句现实日常编译成 Python 伪代码，并模拟运行出属性变化的单页 Web 应用。
输入日常文本，先生成一段「看起来像代码」的 Python 伪代码，再模拟运行时打印扣血日志，最后结算出 **HP / MP / 钱包 / 等级**，并给每个事件贴 buff / debuff 标签。
技术栈固定为 **Python + Streamlit**，不引入前端框架，不引入数据库。

当前版本 v2.6，是**纯在线 AI Agent**：编译数据统一由 DeepSeek API 实时生成（见 `core/llm_client.py`），本地词库已废弃（`core/lexicon.py` 仅保留数据结构）。API Key / 模型名可在「设置」页配置（仅存浏览器会话，不落盘、不写 `.env`）。

**形态说明（已回滚到 v1.0 终端风格）**：界面由「代码 + 终端 + 属性面板 + 标签墙」组成。其中生成的伪代码**默认收进折叠区**（`st.expander`，`expanded=False`），以缩小代码显示区域、避免一屏内容过多——但代码本身保留，这是用户明确要求的「不要动其根本」。

## 2. 分层规则（最重要的一条）

```
core/          引擎层   纯 Python，禁止 import streamlit
ui/            渲染层   纯函数，输入数据输出 HTML 字符串，禁止写业务逻辑
ui/pages/      页面层   流程层的编排部分：允许 st.xxx 组件，业务规则仍必须下沉 core/
app.py         流程层   只做入口 + 路由 + CSS + session_state 初始化 + 世界观状态机
```

判断标准：如果一段逻辑「换个界面还要用」，它就属于 `core/`；
如果一段逻辑「只是为了好看」，它属于 `ui/` 或 `assets/terminal.css`；
如果一段逻辑「是某个页面的交互编排」，它属于 `ui/pages/`。

**页面层约定（v2.6）**：页面模块放 `ui/pages/`，**不要**放根目录 `pages/`——根目录 `pages/` 会触发 Streamlit 原生多页导航（自动侧边栏多页入口），破坏现有单页终端形态。页面之间通过 `st.session_state` 共享状态（如 `world`、`INPUT_KEY`），新增跨页状态时先在 `app.py` 第 3 节初始化。

## 3. 开发流程

按这个顺序推进，不要跳步：

1. **搭框架** — 先把文件和空函数建好，让项目能跑起来
2. **分步实现** — 一次只做一层（引擎 → 渲染 → 页面）
3. **每步测试** — 每完成一层立刻跑对应的自检脚本
4. **迭代推进** — 修完再进下一步，不攒问题

对应命令：

```bash
python tests/test_core.py    # 改了 core/ 之后必跑
python tests/test_app.py     # 改了 ui/ 或 app.py 之后必跑
python -m streamlit run app.py   # 视觉验收
```

**未通过自检的代码不提交。** 界面改动必须实际打开浏览器看一眼，AppTest 抓不到样式问题。

## 4. 代码风格

- 全中文注释，解释「为什么这么写」而不是复述代码字面意思
- 每个模块顶部有 docstring，说明这一层负责什么、不负责什么
- 数据结构一律用 `@dataclass`，常量词库用 `frozen=True` 防止被误改
- 类型注解写全，文件顶部加 `from __future__ import annotations`
- 函数名带下划线前缀表示模块内部使用（如 `_to_entry`）
- 魔法数字必须提取成模块顶部常量

## 5. 视觉规范

改样式前先看 `assets/terminal.css` 顶部的 `:root` 变量，能用变量解决就别写死值。

已定下的取舍，不要推翻：

| 项目 | 决定 | 原因 |
| --- | --- | --- |
| 项目 | 决定 | 原因 |
| --- | --- | --- |
| 基调 | 「游戏化终端」而非「生活账本」 | v1.1 把整套重做成账本后用户要求回滚，明确「不要动其根本」 |
| 展示 | 保留代码框、终端、HP/MP/钱包/等级面板、标签墙 | 这是 v1.0 的核心形态，用户想要的就是这套 |
| 代码区 | 伪代码默认收进 `st.expander(..., expanded=False)` | 用户唯一要求的小改：缩小代码显示区域，但不删代码 |
| 背景 | `#080a09`，不用纯黑 `#000` | 纯黑在屏幕上显廉价，偏绿近黑更像显像管 |
| 强调色 | 只有一个：磷光绿 `#7fe08a` | 多强调色会打架；琥珀和红只作为语义色（告警 / 危险 / debuff） |
| 圆角 | `2px` | 终端风格用极小圆角，10px 大圆角是通用模板的味道 |
| 字体 | JetBrains Mono | 等宽，数字用 `tabular-nums` 保证结算数字不跳动 |
| 质感 | 噪点 + 扫描线两层叠加 | 纯平面色块太干净，不像终端 |
| 动效 | 只用 `transform` / `opacity` | 避免触发重排；并且尊重 `prefers-reduced-motion` |
| 状态 | hover / active / focus-visible 三态齐全 | 键盘可达性是硬要求，不是可选项 |

文案规范：不用感叹号，不用「一键」「赋能」「打造」这类词，错误提示直接说清楚发生了什么。

## 6. 文档维护规则

| 文件 | 什么时候更新 |
| --- | --- |
| `README.md` | 功能、启动方式、依赖发生变化时 |
| `Overview.md` | 增删文件、调整目录结构时（必须同步，否则文件树就废了） |
| `Agent.md` | 定下新的约定或推翻旧约定时 |
| `archive/CHANGELOG.md` | 每次完成一个可验收的改动时追加一条 |

## 7. archive/ 的用法

- 改动记录写进 `archive/CHANGELOG.md`，倒序排列，最新的在最上面
- 要删掉或大改一个文件时，先把旧版本复制到 `archive/YYYY-MM-DD-简短描述/` 下再动手
- 存档目录只进不出，不要在里面继续改代码

## 8. v3.0 基础约束（8 个专家 bug 修复后沉淀）

- **永远不要信任 AI 输出的任何数值**：schema_validator（第一层）截断 + runtime（第二层）再截断，缺一不可。
  - 数值范围：hp[-30,20] / mp[-30,20] / gold[-50,30] / exp[0,15] / tags≤5
  - 等级：指数曲线（下一级所需经验 = 等级²×50），`MAX_LEVEL = 99` 硬上限
  - 改数值边界时，`core/schema_validator.py` 顶部的 `HP_MIN` 等常量与 `core/runtime.py` 的 `MAX_EXP_PER_EVENT` 必须同步改
- **AI 返回必须先过 `schema_validator.validate_and_repair`**：新增任何 `call_llm_for_*` 入口都要走安全门，禁止直接 `json.loads`。
- **日志默认关闭**：用户未在「设置」页开启「启用本地日志记录」就不写 JSONL；`home.py` 写日志前检查 `st.session_state["enable_logging"]`。
- **API Key 只存当前会话**：不写入文件、不写入 localStorage、不在页面预填环境变量；「设置」页有「清除 API Key」按钮。
- **localStorage 桥接**：数据层在 `core/storage.py`（纯 Python，可测）；浏览器侧桥接在 `app.py` 3.6 节（父页面 script 直写 + URL 参数回传恢复）。改动快照结构时记得递增 `SNAPSHOT_VERSION`。
- **性能**：世界观生成走 `app.py` 的 `@st.cache_data(ttl=86400)`（按天）；HTTP 走 `core/llm_client.py` 的 Session 单例。测试注入 `requests.post` 依然有效（以 `requests.api.post` 为哨兵）。

## 9. Agent 层约定（v3.0 Phase 2 新增）

- **新增 `core/agent/`**：planner.py（执行计划）/ validator.py（语义校验）/ reflector.py（AI 反思）/ agent.py（编排入口）。纯 Python，禁止 import streamlit。
- **编译生命周期**：`RealityAgent.run()` = Planner → LLM（core.llm_client，已含 schema 安全门）→ Validator → Runtime（core.compiler.build_compile_result）→ Reflection。`compile()` 便捷入口返回 CompileResult，与旧 `compile_reality` 同类型。
- **任何新增的 `call_llm_for_*` 入口都要接入 schema_validator 安全门**（见 core/agent/validator.py 的 `check()`）。
- **Reflection 必须能降级**：AI 反思失败（缺 Key / 网络 / 异常返回）自动降级本地规则反思，绝不抛给 UI 层。
- **改数值范围时三处同步**：`core/schema_validator.py` 常量 + `core/runtime.py` 的 `MAX_EXP_PER_EVENT` + `core/agent/planner.py` 的 constraints（保持一致）。
- **新增测试**：`tests/test_agent.py`（36 项），改 Agent 相关代码后必跑。

## 10. 记忆系统约定（v3.0 Phase 3 新增）

- **存储**：`core/database/`（SQLite；UI 使用 `data/reality_<会话ID>.db` 隔离访客）+
  `core/memory/`（short_term / long_term / retriever）。
  纯 Python 零依赖；SQLite 锁必须用 `threading.RLock`（可重入），禁止普通 Lock（会死锁）。
- **默认关闭**：记忆开关（`enable_memory`）默认 False，与日志开关同样尊重隐私；关闭时不读取也不写入记忆。
- **接入方式**：`RealityAgent.run(memory=LongTermMemory)`——编译前自动检索注入 context，
  编译后自动归档事件与标签偏好；检索/归档失败静默降级，绝不影响编译。
- **改记忆表结构**：在 `core/database/db.py` 的 `SCHEMA_SQL` 改；已存在的库不会自动迁移
  （如需迁移在 CHANGELOG 记录，并保留 `data/` 目录）。
- **记忆上下文注入提示词**：`core/llm_client.py` 的 `_build_memory_context_block()`；
  只做辅助参考，禁止让 AI 编造档案中不存在的事实。

## 11. 世界模拟约定（v3.0 Phase 4 新增）

- **不重写现有 Runtime**（最有价值资产）。`core/simulation/` 是「世界演化」增强层：
  事件 → 隐藏状态（Energy/Stress/SleepDebt）→ 规则触发 → 衍生事件。
- **隐藏状态与可见属性分离**：可见属性（HP/MP/EXP）由 runtime 结算；隐藏状态由
  simulation 累积。两套产物在 UI 上分别展示（属性面板 + 世界演化面板）。
- **改状态推导关键词**：`core/simulation/state.py` 的 `DEFAULT_DERIVERS`（纯本地，
  不调 LLM，即使 AI 没打对标签世界也会自己演化）。
- **改规则**：`core/simulation/rules.py` 的 `DEFAULT_RULES`（声明式 Rule）；
  未来可挂到世界观（WorldProfile 加 rules 字段）。
- **Event Graph 不第一版实现**（方案明确复杂度高，留待 v3.0 之后）。
- **改模拟编排**：`core/simulation/engine.py` 的 `SimulationEngine.simulate()`。

## 12. 待办与演进方向（v3.0 路线）

- [x] 接入真实模型 API（DeepSeek，`core/llm_client.py`，页面内可配 Key / 模型）
- [x] v2.6 app.py 拆分（`ui/pages/`：home / settings / report）
- [x] v2.6.1 全量专家修复：Schema 安全门 / 注入防御 / EXP+等级限制 / 世界观缓存 / localStorage / 日志开关 / Key 安全
- [x] **Phase 2 · Agent化**：`core/agent/`（agent.py / planner.py / validator.py / reflector.py）✅ 39 项测试
- [x] **Phase 3 · 记忆系统**：`core/database/` + `core/memory/` ✅ 36 项测试
- [x] **Phase 4 · 世界模拟升级**：`core/simulation/`（state / rules / engine）✅ 33 项测试
- [ ] **Event Graph**（事件图，方案建议 v3.0 之后实现）
- [ ] LLM 抽象为 `core/llm/`（base.py / deepseek.py / openai.py / qwen.py），换模型不动 Agent
- [ ] 世界观专属规则（WorldProfile 挂 rules）
- [ ] 隐藏状态跨天持久化（SimState.from_dict 已就绪，接入记忆系统）
- [ ] 支持多服务商（OpenAI / 本地 Ollama 等）
- [ ] 生成的伪代码支持切换风格（游戏向 / 运维向 / 前端向）
- [ ] 移动端窄屏下终端字号再调一档

## 13. 明确不做的事

- 不做用户系统、不做后端存储；输入内容默认不落盘（日志 / 记忆需用户主动开启），但会发送给大模型用于生成结果（隐私边界以页面提示为准）
- API Key 不写入文件 / localStorage / 环境变量预填（仅存当前会话；生产建议用平台 Secrets）
- 不引入 React / Vue，也不引入 Tailwind，样式就用这一份 CSS
- 不把 `st.code` 换成自定义组件，需求指定了用它
- 不在生成的伪代码里放真正可执行的危险代码，它只是「看起来像代码」
- 不擅自把终端形态改成账本形态——v1.1 已验证这是用户不想要的过度改造
