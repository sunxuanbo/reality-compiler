# -*- coding: utf-8 -*-
"""界面层自检：用 Streamlit AppTest 无头跑页面，验证交互链路。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest

# 本项目已「舍弃本地词库」，编译需要 API。界面层自检无真实 Key/网络，
# 这里注入一个确定性的假 requests.post，让 AppTest 能跑通完整编译链路。
import os
import json as _json

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")

import requests as _req

# v2.5：界面测试使用独立临时日志目录，避免污染项目 logs/
# （用户要求验收时不要自行生成任何模拟日志）
import tempfile
import shutil as _shutil
from core import logger as _test_logger

_TEST_LOGS_DIR = Path(tempfile.mkdtemp(prefix="rc_test_logs_"))
_test_logger.LOGS_DIR = _TEST_LOGS_DIR


class _FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


def _fake_post(url, headers=None, json=None, timeout=None):
    # 根据系统提示词区分「世界观生成 / 今日冒险 / 事件生成」三种请求
    sys_prompt = ""
    if json and isinstance(json, dict):
        msgs = json.get("messages") or []
        if msgs:
            sys_prompt = msgs[0].get("content", "")
    if "世界观生成器" in sys_prompt:
        # 世界观生成：返回一个固定的「赛博纪元」世界（含货币/今日冒险）
        return _FakeResp({"choices": [{"message": {
            "content": _json.dumps({
                "world_name": "赛博纪元",
                "world_description": "霓虹与数据交织的都市",
                "currency_name": "比特币",
                "stat_mapping": {"hp": "生命值", "mp": "精力值", "gold": "比特币"},
                "daily_story": "今天你穿越到赛博纪元，在霓虹街巷里替人修了一次义体，赚了一点比特币，回来已经很晚。",
            })
        }}]})
    if os.environ.get("FORCE_LLM_ERR") == "401":
        # 模拟无效 Key（401），用于验证「报中文错误 + 旧面板保留」
        return _FakeResp({}, status=401)
    if "今日事件供给器" in sys_prompt:
        return _FakeResp({"choices": [{"message": {
            "content": "今天去铁匠铺看了一把微光的剑，晚上熬夜加班到很晚。"
        }}]})
    return _FakeResp({
        "choices": [{
            "message": {
                "content": _json.dumps({
                    "world_display_name": "赛博纪元",
                    "summary": "疲惫的一天",
                    "mood": "sad",
                    "mood_intensity": 76,
                    "mood_confidence": 92,
                    "mood_reason": "加班和熬夜带来了明显的疲惫与低落",
                    "events": [
                        {"name": "加班", "description": "肝到凌晨",
                         "hp": -20, "mp": -10, "gold_or_san": -15,
                         "exp": 8, "tags": ["加班", "疲惫"]},
                        {"name": "熬夜", "description": "凌晨未眠",
                         "hp": -8, "mp": -4, "gold_or_san": -5,
                         "exp": 3, "tags": ["熬夜"]},
                    ],
                })
            }
        }]
    })


_req.post = _fake_post


def run() -> None:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)

    # 1. 首屏：标题 + 待机面板都在（标题用 st.markdown 渲染）
    at.run()
    assert any("Reality Compiler" in m.value for m in at.markdown), "首屏应有标题"
    assert any("把今天发生的事写下来" in m.value for m in at.markdown), "首屏应有待机面板"
    print("[PASS] 首屏渲染正常")

    # 2. 空输入：应被拦截并提示错误
    at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at2.run()
    at2.button(key="btn_run").click().run()
    assert any("输入为空" in m.value for m in at2.markdown), "空输入应被拦截"
    print("[PASS] 空输入被拦截")

    # 3. 完整编译：生成伪代码（折叠区里）+ 终端日志 + 属性面板 + 标签墙
    at3 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at3.run()
    at3.text_area[0].set_value("今天加班到凌晨一点，靠两杯美式续命，回家路上还赶上下雨")
    at3.button(key="btn_run").click().run()
    md = "\n".join(m.value for m in at3.markdown)
    assert "runtime · life 3.0" in md, "应有运行时终端"
    assert "HP" in md, "应有属性面板"
    assert "加班" in md, "标签墙应有命中的事件"
    assert "EMOTION SIGNAL" in md and "难过" in md, "应展示情绪结果卡"
    assert "rc-mood-sad" in md, "难过情绪应启用冷色细雨氛围"
    assert "rc-event-card" in md, "应展示叙事事件卡"
    css_now = (ROOT / "assets" / "terminal.css").read_text(encoding="utf-8")
    assert ".rc-mood-ambience" in css_now and "z-index: 1" in css_now, "氛围层必须位于页面底色之上"
    assert "mix-blend-mode: screen" not in css_now, "氛围层不得使用昂贵的全屏混合模式"
    assert "mood-card-sweep" in css_now and "mood-icon-float" in css_now, "情绪卡应有可见动态反馈"
    print("[PASS] 完整编译链路正常")

    # 4. 清空：结果应被重置回待机状态
    at3.button(key="btn_clear").click().run()
    assert any("把今天发生的事写下来" in m.value for m in at3.markdown), "清空后回到待机"
    print("[PASS] 清空恢复待机")

    # 5. v2.2 每日世界观（AI 生成）：页面展示世界观名 + 货币名；生成今日冒险自动编译
    at5 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at5.run()
    md5a = "\n".join(m.value for m in at5.markdown)
    assert "今日世界" in md5a, "应展示今日世界观（只读）"
    assert "赛博纪元" in md5a, "应展示 AI 生成的世界观名称"
    assert "比特币" in md5a, "应展示 AI 生成的货币名"
    # 点击生成今日冒险：自动填充 AI 世界观的 daily_story 并编译
    at5.button(key="btn_daily").click().run()
    md5 = "\n".join(m.value for m in at5.markdown)
    assert "HP" in md5, "生成今日冒险后应有属性面板"
    assert "比特币" in md5, "结算面板可变属性应为 AI 货币名（比特币）"
    print("[PASS] AI 世界观生成 + 生成今日冒险正常")

    # 6. 编译后属性面板常驻；空输入编译只报错、不清空旧面板
    at6 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at6.run()
    at6.text_area[0].set_value("今天加班到凌晨一点，靠两杯美式续命，回家路上还赶上下雨")
    at6.button(key="btn_run").click().run()
    assert any("HP" in m.value for m in at6.markdown), "编译后应有属性面板"
    at6.text_area[0].set_value("")           # 清空输入
    at6.button(key="btn_run").click().run()
    md6 = "\n".join(m.value for m in at6.markdown)
    assert "输入为空" in md6, "空输入应提示错误"
    assert "HP" in md6, "空编译不得清空旧面板（面板常驻）"
    print("[PASS] 编译后面板常驻，空编译不清空")

    # 7. 运行时终端默认折叠；清空回到待机
    at7 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at7.run()
    at7.text_area[0].set_value("早起跑步五公里，喝奶茶，打游戏，十点睡觉")
    at7.button(key="btn_run").click().run()
    # AppTest 的 expander 元素不暴露 key/expanded，这里按 label 确认「运行时·终端」折叠面板存在；
    # 其默认折叠（expanded=False）由 app.py 中 st.expander(..., expanded=False) 保证。
    term = next((e for e in at7.expander if "终端" in e.label), None)
    assert term is not None, "应存在运行时终端折叠面板"
    at7.button(key="btn_clear").click().run()
    assert any("把今天发生的事写下来" in m.value for m in at7.markdown), "清空后回到待机"
    print("[PASS] 运行时终端默认折叠，清空回到待机")

    # 8. v2.1 今日复盘：编译后结算面板下方出现 AI 复盘区域（summary 非空）
    # v2.6 拆分：日志统计 + PDF 导出移到「报告页」，需切换到报告页验证
    at8 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at8.run()
    at8.text_area[0].set_value("今天加班到凌晨一点，靠两杯美式续命，回家路上还赶上下雨")
    at8.button(key="btn_run").click().run()
    md8 = "\n".join(m.value for m in at8.markdown)
    assert "今日复盘" in md8, "结算面板下方应有今日复盘区域"
    assert "疲惫的一天" in md8, "复盘应展示 AI 生成的 summary"
    # 切换到报告页（导航 radio）
    at8.radio(key="nav_page").set_value("📊 报告").run()
    md8b = "\n".join(m.value for m in at8.markdown)
    assert "日志统计" in md8b, "报告页应有日/周/月统计区"
    _btn_labels = [b.label for b in at8.button]
    assert any("导出今日日志" in lb for lb in _btn_labels), "有日志时应出现今日 PDF 导出按钮"
    assert any("导出本周日志" in lb for lb in _btn_labels), "有日志时应出现本周 PDF 导出按钮"
    assert any("导出本月日志" in lb for lb in _btn_labels), "有日志时应出现本月 PDF 导出按钮"
    print("[PASS] 今日复盘 + 日志统计 + PDF 导出按钮渲染")

    # 9. v2.2 离线降级友好报错：AI 不可用（401）时报中文错误 + 旧面板保留（不降级本地词库）
    at9 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at9.run()
    # 先成功编译一次，建立属性面板
    at9.text_area[0].set_value("今天加班到凌晨一点，靠两杯美式续命，回家路上还赶上下雨")
    at9.button(key="btn_run").click().run()
    md9ok = "\n".join(m.value for m in at9.markdown)
    assert "HP" in md9ok, "首次编译应建立属性面板"
    # 切换为无效 Key（fake post 返回 401），再次编译
    os.environ["FORCE_LLM_ERR"] = "401"
    try:
        at9.text_area[0].set_value("再编译一次应该报错但面板保留")
        at9.button(key="btn_run").click().run()
        md9 = "\n".join(m.value for m in at9.markdown)
        assert "API Key 无效" in md9, "应显示中文友好错误（API Key 无效）"
        assert "HP" in md9, "报错后旧属性面板应保留（不被清空）"
    finally:
        os.environ.pop("FORCE_LLM_ERR", None)
    print("[PASS] 离线降级：AI 不可用报中文错误且旧面板保留")

    # 10. v2.5 刷新世界观：点击后强制重新生成（页面不报错、世界观仍展示）
    at10 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at10.run()
    _before = next((m.value for m in at10.markdown if "今日世界" in m.value), "")
    assert "今日世界" in _before, "刷新前应有世界观展示"
    _nonce_before = int(at10.session_state["world_refresh_nonce"])
    at10.button(key="btn_refresh_world").click().run()
    _after = next((m.value for m in at10.markdown if "今日世界" in m.value), "")
    assert "今日世界" in _after, "刷新后仍应展示世界观"
    assert "赛博纪元" in _after, "刷新后世界观可正常重新生成（fake post 固定返回）"
    assert int(at10.session_state["world_refresh_nonce"]) == _nonce_before + 1, "手动刷新应绕过同日缓存"
    print("[PASS] 刷新世界观按钮正常")

    # 11. API Key 清除必须通过 widget 回调完成，且源码不得再走 URL/localStorage 回传。
    at11 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at11.run()
    _fingerprint_before = at11.session_state["world_key_fingerprint"]
    at11.radio(key="nav_page").set_value("⚙️ 设置").run()
    at11.text_input(key="_cfg_api_key_widget").set_value("sk-session-only").run()
    assert at11.text_input(key="_cfg_api_key_widget").value == "sk-session-only", "Key 应进入当前会话"
    at11.button(key="btn_save_api_key").click().run()
    assert at11.session_state["cfg_api_key"] == "sk-session-only", "Widget 值应同步到独立业务配置"
    assert at11.session_state["world_key_fingerprint"] != _fingerprint_before, "更换 Key 应使旧世界观失效"
    assert at11.session_state["api_connection_status"] == "verified", "成功生成世界观后才可标记连接已验证"
    at11.radio(key="nav_page").set_value("🏠 主页").run()
    assert at11.session_state["cfg_api_key"] == "sk-session-only", "切离设置页后 API Key 配置不得被清理"
    at11.text_area[0].set_value("跨页面编译测试")
    at11.button(key="btn_run").click().run()
    _md11 = "\n".join(m.value for m in at11.markdown)
    assert "未配置 API Key" not in _md11, "切到主页编译时必须继续使用已配置的 Key"
    at11.radio(key="nav_page").set_value("⚙️ 设置").run()
    at11.button(key="btn_clear_api_key").click().run()
    assert at11.text_input(key="_cfg_api_key_widget").value in ("", None), "清除按钮应安全清空 Key"
    assert at11.session_state["cfg_api_key"] == "", "清除按钮应同时清空业务配置"
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    settings_source = (ROOT / "ui" / "pages" / "settings.py").read_text(encoding="utf-8")
    assert "reality_api_key" not in app_source + settings_source, "Key 不得写 localStorage"
    assert 'query_params.get("k")' not in app_source, "Key 不得通过 URL 参数回传"
    print("[PASS] API Key 仅存会话且可安全清除")

    # 11.5 通用模型配置：服务、地址、模型、Key 均使用业务键跨页面保持并进入调用链。
    at11b = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at11b.run()
    at11b.radio(key="nav_page").set_value("⚙️ 设置").run()
    at11b.selectbox(key="_cfg_api_provider_widget").set_value("自定义兼容接口").run()
    at11b.text_input(key="_cfg_api_base_widget").set_value("https://gateway.example/v1").run()
    at11b.text_input(key="_cfg_api_model_widget").set_value("compatible-model").run()
    at11b.text_input(key="_cfg_api_key_widget").set_value("sk-generic").run()
    at11b.button(key="btn_save_api_key").click().run()
    assert at11b.session_state["cfg_api_provider"] == "自定义兼容接口", "服务类型应保存"
    assert at11b.session_state["cfg_api_base"] == "https://gateway.example/v1", "接口地址应保存"
    assert at11b.session_state["cfg_api_model"] == "compatible-model", "模型名应保存"
    at11b.radio(key="nav_page").set_value("🏠 主页").run()
    assert at11b.session_state["cfg_api_base"] == "https://gateway.example/v1", "接口地址切页后不得丢失"
    assert at11b.session_state["cfg_api_model"] == "compatible-model", "模型名切页后不得丢失"
    home_source = (ROOT / "ui" / "pages" / "home.py").read_text(encoding="utf-8")
    report_source = (ROOT / "ui" / "pages" / "report.py").read_text(encoding="utf-8")
    assert "base_url=st.session_state.get(\"cfg_api_base\")" in home_source, "主页请求应透传接口地址"
    assert "model=st.session_state.get(\"cfg_api_model\")" in home_source, "主页请求应透传模型名"
    assert "base_url=st.session_state.get(\"cfg_api_base\")" in report_source, "报告请求应透传接口地址"
    print("[PASS] 通用模型配置跨页面保持并贯穿全部请求")

    # 12. v3.0 响应式 UI：导航不再依赖侧栏，移动端断点存在，属性卡与报告卡类名隔离。
    css_source = (ROOT / "assets" / "terminal.css").read_text(encoding="utf-8")
    render_source = (ROOT / "ui" / "render.py").read_text(encoding="utf-8")
    assert "with st.sidebar" not in app_source, "移动端导航不得再放入遮屏侧栏"
    assert "horizontal=True" in app_source, "主导航应使用横向布局"
    assert '@media (max-width: 560px)' in css_source, "应提供手机端响应式断点"
    assert '<section class="rc-log-stats">' in render_source, "报告统计应使用独立样式类"
    assert render_source.count('<section class="rc-stats">') == 1, "属性卡类名不得再被报告统计复用"
    print("[PASS] 响应式导航与卡片样式隔离正常")

    # 13. v3.1 情绪互动：手动校准仅切换氛围；设置开关跨页面保留。
    at13 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at13.run()
    at13.text_area[0].set_value("今天加班到很晚，感觉很疲惫")
    at13.button(key="btn_run").click().run()
    _original_mood = at13.session_state["result"].emotion.mood
    at13.radio(key="emotion_override_choice").set_value("joyful").run()
    _md13 = "\n".join(m.value for m in at13.markdown)
    assert "rc-mood-joyful" in _md13, "手动校准应切换当前氛围"
    assert at13.session_state["result"].emotion.mood == _original_mood, "校准不得修改原始情绪结果"
    at13.radio(key="nav_page").set_value("⚙️ 设置").run()
    at13.toggle(key="_enable_emotion_effects_widget").set_value(False).run()
    assert at13.session_state["enable_emotion_effects"] is False, "情绪特效开关应写入业务配置"
    at13.radio(key="nav_page").set_value("🏠 主页").run()
    assert at13.session_state["enable_emotion_effects"] is False, "切换页面后情绪特效配置不得丢失"
    _md13off = "\n".join(m.value for m in at13.markdown)
    assert "data-mood=" not in _md13off, "关闭后不应渲染氛围粒子层"
    assert "EMOTION SIGNAL" in _md13off, "关闭特效不应隐藏情绪结果卡"
    print("[PASS] 情绪校准与跨页特效开关正常")

    # 14. 性能默认值：去掉人为 sleep，AI 深度反思默认关闭且开关跨页保持。
    home_source = (ROOT / "ui" / "pages" / "home.py").read_text(encoding="utf-8")
    assert "time.sleep(" not in home_source, "主页编译成功后不得再人为等待"
    assert "enable_local_reflection=True" in home_source, "主页应保留零网络请求的本地复核"
    at14 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at14.run()
    assert at14.session_state["enable_ai_reflection"] is False, "AI 深度反思默认应关闭"
    at14.radio(key="nav_page").set_value("⚙️ 设置").run()
    assert at14.toggle(key="_enable_ai_reflection_widget").value is False, "设置页应展示快速模式默认值"
    at14.toggle(key="_enable_ai_reflection_widget").set_value(True).run()
    at14.radio(key="nav_page").set_value("🏠 主页").run()
    assert at14.session_state["enable_ai_reflection"] is True, "AI 反思开关切页后不得丢失"
    print("[PASS] 快速模式与深度反思开关正常")

    # 清理界面测试产生的临时日志目录（不污染项目 logs/）
    _shutil.rmtree(_TEST_LOGS_DIR, ignore_errors=True)

    print("\n全部界面层自检通过 ✔")


if __name__ == "__main__":
    run()
