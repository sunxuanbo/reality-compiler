---
title: Reality Compiler
emoji: 🎮
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: "1.38.0"
app_file: app.py
pinned: false
---

# Reality Compiler

把一句「现实日常」编译成一段 Python 伪代码，再模拟运行，最后给你结算出 **HP / MP / 可变属性 / 等级**——像在玩一个把生活当 RPG 的命令行编译器。

> 纯在线 AI Agent：编译数据由 **OpenAI Chat Completions 兼容接口**实时生成，
> 内置 DeepSeek / OpenAI / 本地模型预设，也可连接自定义兼容服务。
> 输入会发送给大模型用于生成结果。

## 在线体验（一键部署）

本项目已配置好 Hugging Face Spaces 元数据（见本文件顶部 `---` 区块）。把整个仓库上传到
Hugging Face 创建一个 **Streamlit** Space 即可在线访问，**访客无需安装任何东西**。

部署步骤（约 2 分钟）：

1. 注册 / 登录 [huggingface.co](https://huggingface.co)，右上角 **New Space**。
2. 选 **Streamlit** 作为 SDK，Repo 名随意（如 `reality-compiler`），可见性选 **Public**。
3. 把本仓库文件（`app.py`、`core/`、`ui/`、`assets/`、`requirements.txt`、本 `README.md`）
   上传 / 用 git 推上去。HF 读到 README 顶部的 `sdk: streamlit` 会自动识别并安装依赖。
4. 打开 Space 链接即可使用。每个访客在页面顶部 **「⚙ 模型设置」** 选择服务、填写接口地址、
   模型名和自己的 Key（仅存浏览器会话，**不落盘、不共享**），填完直接编译。

> 不需要在 HF 后台设置任何 Secret——Key 由每位用户自己填。

## 跑起来（本地）

```bash
pip install -r requirements.txt
cp .env.example .env          # 填入 AI_API_KEY / AI_API_BASE / AI_MODEL（也可在页面里填）
streamlit run app.py
```

打开 http://localhost:8501 即可。

**没有 API Key？** 切到顶部 **「⚙️ 设置」** 页，填写你的模型连接后立即生效
（仅保存在当前浏览器会话，刷新会清空，不写文件）。

## 它长什么样

```
① 写下你的现实日常
  [输入框] 今天加班到凌晨一点，靠两杯美式续命……
  [执行编译] [清空]

② 编译结果
  ┌ 生成的伪代码（点开看）────────────┐   ← 默认折叠，缩小代码显示区域
  │ import life                         │
  │ player.log_event('加班', hp=-20…)   │
  └────────────────────────────────────┘
  运行时 · 终端        runtime · life 3.0
    💼 加班     hp=-20 mp=-10 …
    ☕ 咖啡因   hp=0   mp=+15 …
    [stat] HP 65/100 · MP 95/100 · 钱包 -40 · EXP 14 (Lv.1)
  属性结算   HP ▁▁▁▁  MP ▁▁▁▁  钱包 -40  等级 1
  buff/debuff 标签墙： 加班 / 熬夜 / 咖啡因 …
```

## 功能

- **多世界观**：AI 按日期每天动态生成全新世界观（名称 / 背景 / 货币名都不同），同日不变、跨天切换；AI 不可用时回退内置兜底世界。
- **AI 编译（Agent 化）**：把输入交给当前配置的模型，由模型直接给出结构化事件与数值（不再本地匹配）。
  v3.0 起编译由 `RealityAgent` 编排完整生命周期：规划（Planner）→ 生成（LLM）→ 校验（Validator）
  → 执行（Runtime）→ 自我反思（Reflection）。
- **情绪互动**（v3.1）：同一次编译识别开心 / 平静 / 难过 / 焦虑 / 生气 / 复杂六类情绪，
  置信度不足或旧格式响应自动使用本地规则兜底；结果页显示情绪卡、强度条、叙事事件卡与
  克制的粒子氛围。用户可手动校准当前氛围，校准不会修改原始结果、日志或记忆。
- **AI 自我反思**：每次编译后，Agent 会以第三方审查者身份检查事件是否合理（数值离谱 /
  编造情节 / 违反规则），结论展示在「🔎 AI 自我反思」面板。主页默认使用零网络请求的本地
  快速复核，避免一次提交等待两次模型响应；可在设置中启用 AI 深度反思。
- **记忆系统**（可选，默认关闭）：开启后 Agent 会记住你的用户档案与近期事件，编译前自动
  检索注入（更连贯、更有个人特色），编译后自动归档到会话隔离的本地 SQLite
  （`data/reality_<会话ID>.db`），避免托管部署时不同访客共享记忆。
- **世界模拟**（v3.0 Phase 4）：事件不只是「-5 HP」就结束——还会累积隐藏状态
  （精力 / 压力 / 睡眠债），累积到阈值时触发规则（如睡眠债爆表 → 慢性疲劳），
  生成衍生新事件，让世界自己发展。
- **今日冒险**：一键由 AI 生成今日流水账并自动编译。
- **透明结算**：每一步「初始值 → 事件增量 → 夹紧 → 结算」都逐步展示，不黑盒。
- **容错安全门**：AI 返回的数据先过 Schema 校验（缺字段补 0 / 类型强转 / 数值硬截断），任何非预期输出都不会导致页面崩溃。
- **通用模型设置**：顶部「⚙️ 设置」页可选 DeepSeek、OpenAI、本地模型或自定义兼容接口；
  地址、模型和 Key 在当前会话内跨页面保持，Key 不落盘、不共享，可一键清除。
- **旧面板保护**：编译失败只报错，不清空已生成的结果面板。
- **日志与报告**：需在「设置」页主动开启「日志记录」才写入本地 JSONL；报告页提供日 / 周 / 月统计与 PDF 导出。
- **本地持久化**：编译结果自动保存到浏览器 localStorage，关闭页面再打开可恢复上次的世界观与属性面板。

## 目录结构

```
reality-compiler/
├── app.py              # 入口 + 路由 + CSS + session_state 初始化 + 世界观状态机
├── core/               # 引擎层：AI 编译 → 运行时，纯 Python，不依赖 Streamlit
│   ├── llm_client.py   # 通用 Chat Completions 封装：事件 + 今日冒险 + 报告
│   ├── schema_validator.py # Schema 安全门：Pydantic 校验 + JSON 提取 + 修复 + 兜底
│   ├── compiler.py     # 编译成 Python 伪代码 + 编译告警
│   ├── emotion.py      # 六类情绪状态 + 低置信度本地兜底
│   ├── runtime.py      # 模拟运行，输出终端日志 + 属性结算 + 标签墙（EXP 截断 + 指数等级曲线）
│   ├── world_config.py # AI 世界观转换 + 兜底世界
│   ├── content_provider.py # 今日冒险供应 + 每日世界观生成器
│   ├── logger.py       # JSONL 日志 + 日/周/月统计（需用户开启日志开关）
│   ├── storage.py      # localStorage 数据层：快照构建 / 序列化 / 30 天清理
│   ├── pdf_exporter.py # PDF 日志报告导出
│   └── lexicon.py      # 历史词库（仅保留数据结构，已不再是数据来源）
├── ui/                 # 渲染层 + 页面层
│   ├── render.py       # 结果 → HTML 字符串（纯函数）
│   └── pages/          # 页面：home（主页）/ settings（设置）/ report（报告）
├── assets/terminal.css # 终端主题（暗绿、扫描线质感）
├── tests/              # 自检：python tests/test_core.py / test_app.py
└── .env.example        # 环境变量模板（复制为 .env 填 Key）
```

## 想改点什么

| 我想改… | 打开这个文件 | 具体位置 |
| --- | --- | --- |
| 改 AI 系统提示词（数值口径 / 世界观风格） | `core/llm_client.py` | `_build_system_prompt()` |
| 改默认模型 / API 地址 / 超时 | `core/llm_client.py` | 顶部常量 `DEFAULT_MODEL` 等 |
| 改世界观生成 / 今日冒险 | `core/content_provider.py` | `fetch_world()` / `fetch_daily_event()` |
| 改生成伪代码的样子 | `core/compiler.py` | `_render_code()` |
| 改数值范围 / 硬上限 | `core/schema_validator.py` + `core/runtime.py` | 顶部常量 / `MAX_EXP_PER_EVENT` |
| 改初始 HP / 可变属性 / 等级 | `core/runtime.py` | 文件顶部常量 + `_level_from()` |
| 改终端里打印的内容与顺序 | `core/runtime.py` | `simulate_runtime()` 里的 `emit(...)` |
| 改 localStorage 快照 / 保留天数 | `core/storage.py` | `build_snapshot()` / `MAX_LOG_DAYS` |
| 改配色 / 字体 / 扫描线 | `assets/terminal.css` | 顶部 `:root` 变量优先 |
| 改标题栏 / 空状态 / 页脚文案 | `ui/render.py` | 对应的 `*_html()` 函数 |
| 改主页交互 / 快捷样本 | `ui/pages/home.py` | `SAMPLES` / 各区渲染函数 |
| 改 API Key / 存款设置 | `ui/pages/settings.py` | `_render_model_settings()` 等 |
| 改日志统计 / PDF 导出 | `ui/pages/report.py` | `_render_log_stats()` 等 |
| 改路由 / 世界观状态机 | `app.py` | 第 3.5 节 + 第 4 节 |

## 自检

```bash
python tests/run_all.py     # 引擎 / 情绪 / Agent / 记忆 / 模拟 / 界面全量回归
```

自检不依赖真实网络与真实 Key：测试会注入一个确定性的假 `requests.post`，跑通完整链路；API 的错误分支（无 Key / 401 / 429）另有独立用例覆盖。

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `AI_API_KEY` | 否 | 远程服务的密钥；本机 localhost 接口可留空 |
| `AI_API_BASE` | 否 | 接口根地址或完整 `/chat/completions` 地址；默认 DeepSeek |
| `AI_MODEL` | 否 | 服务商提供的模型 ID；默认 `deepseek-chat` |

旧版 `DEEPSEEK_API_KEY`、`DEEPSEEK_API_BASE`、`DEEPSEEK_MODEL` 仍兼容。

> 默认行为：访客在顶部「⚙️ 设置」页填自己的 Key，仅存浏览器会话、不落盘。
> `.env` 仅作本地开发兜底，含密钥，已被 `.gitignore` 忽略，请勿提交到版本库。
