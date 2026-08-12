# -*- coding: utf-8 -*-
"""带超时的全量测试核查（v3.0 记忆系统）。

逐个运行全部测试套件，每个设置 60 秒硬超时：
    - 正常结束 → 记录 FAIL 数与结束标记
    - 超时 → 强杀进程并标记 HANG（说明有卡住问题，需定位死锁/阻塞）

由来：test_memory.py 曾因 SQLite 锁不可重入（普通 threading.Lock + wipe 内嵌
self.conn 取锁）导致死锁卡住；修复为 RLock 后，本工具用于一劳永逸地验证
「任何套件都不会挂起」，并打印挂起前的最后输出辅助定位。

用法：
    python tests/run_all.py
"""
import subprocess
import sys
import time
from pathlib import Path

# Windows 中文环境常默认为 GBK；测试输出含 Unicode 状态符号，强制 UTF-8 可避免
# 启动器在真正执行测试前因 UnicodeEncodeError 提前退出。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SUITES = [
    ("tests/test_core.py", "引擎层"),
    ("tests/test_emotion.py", "情绪系统"),
    ("tests/test_agent.py", "Agent 层"),
    ("tests/test_memory.py", "记忆系统"),
    ("tests/test_simulation.py", "世界模拟"),
    ("tests/test_app.py", "界面层"),
]
TIMEOUT = 60          # 每套件硬超时（秒）
PY = sys.executable
ROOT = Path(__file__).resolve().parent.parent

print("=" * 56)
print("带超时的全量测试核查（每套件 %s 秒硬超时）" % TIMEOUT)
print("=" * 56)

all_ok = True
for script, label in SUITES:
    t0 = time.time()
    print(f"\n▶ {label}（{script}）...", flush=True)
    try:
        proc = subprocess.Popen(
            [PY, "-X", "utf8", "-u", script],
            cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        out, _ = proc.communicate(timeout=TIMEOUT)
        elapsed = time.time() - t0
        fails = out.count("✘ FAIL")
        ok_line = "自检通过" in out
        print(
            f"  ✅ 结束（{elapsed:.1f}s） EXIT={proc.returncode} "
            f"FAIL={fails} END_OK={ok_line}",
            flush=True,
        )
        if proc.returncode != 0 or fails or not ok_line:
            tail = out[-1500:] if out else "（无输出）"
            print(f"  [最后输出]\n{tail}", flush=True)
            all_ok = False
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        elapsed = time.time() - t0
        print(f"  ❌ 超时挂起（{elapsed:.1f}s）—— 存在卡住问题！", flush=True)
        # 打印挂起前的最后输出，帮助定位
        tail = out[-1500:] if out else "（无输出）"
        print(f"  [最后输出]\n{tail}", flush=True)
        all_ok = False

print("\n" + "=" * 56)
if all_ok:
    print("核查结论：全部测试正常结束，无卡住 ✔")
else:
    print("核查结论：存在失败或超时，需修复 ✘")
print("=" * 56)
sys.exit(0 if all_ok else 1)
