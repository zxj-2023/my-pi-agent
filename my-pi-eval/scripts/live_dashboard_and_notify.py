"""Live monitoring dashboard for Terminal-Bench 2.0 evaluation with Herdr auto-trigger."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

os.environ["PYTHONUTF8"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "official_pi_progress.json"
LEFT_PANE_ID = "w8:p1"  # Current conversation pane


def trigger_left_pane() -> None:
    msg = "Terminal-Bench 2.0 全部 89 题（含 65 题精准补考）评测已正式完工！请为我整理汇总最终完整评测结果、生成高保真 Markdown 战报与全任务分析。"
    try:
        subprocess.run(
            ["herdr", "pane", "send-text", LEFT_PANE_ID, msg],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        time.sleep(0.5)
        subprocess.run(
            ["herdr", "pane", "send-keys", LEFT_PANE_ID, "enter"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        print(f"\n[INFO] 已成功向左侧 Pi ({LEFT_PANE_ID}) 发送完工通知与总结指令！")
    except Exception as e:
        print(f"[WARN] 触发左侧面板异常: {e}")


def render_dashboard() -> tuple[int, int, int]:
    if not PROGRESS_FILE.exists():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 等待评测数据初始化...")
        return 0, 0, 89

    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return 0, 0, 89

    tasks = data.get("tasks", {})
    total = data.get("total_tasks", 89)

    passed_list = []
    active_failed_list = []
    zero_token_list = []

    total_tokens = 0
    total_cost = 0.0

    for name, t in tasks.items():
        status = t.get("status")
        tok = t.get("tokens", 0)
        cost = t.get("cost_usd", 0.0)
        dur = t.get("duration_sec", 0)
        total_tokens += tok
        total_cost += cost
        if status == "PASSED":
            passed_list.append((name, tok, dur))
        elif tok > 0 and dur >= 30:
            active_failed_list.append((name, tok, dur))
        else:
            zero_token_list.append((name, tok, dur))

    passed = len(passed_list)
    active_failed = len(active_failed_list)
    zero_tokens = len(zero_token_list)
    genuine_attempts = passed + active_failed

    real_win_rate = (passed / genuine_attempts * 100) if genuine_attempts > 0 else 0.0
    overall_win_rate = (passed / total * 100) if total > 0 else 0.0

    # Clear screen with ANSI escape codes
    print("\033[2J\033[H", end="")

    print("=" * 80)
    print("  🚀 Terminal-Bench 2.0 评测与补考全景实时监控看板 (Official Pi + DeepSeek)")
    print("=" * 80)
    print(f"  📅 刷新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(
        f"  📊 赛题总数: {total:<3} | 🏆 满分通过: {passed:<3} | ❌ 真实失败: {active_failed:<3} | ⏳ 待补考: {zero_tokens:<3}"
    )
    print(
        f"  🎯 真实参赛胜率: {real_win_rate:.2f}% ({passed}/{genuine_attempts}) | 整体绝对胜率: {overall_win_rate:.2f}%"
    )
    print(f"  🪙 Token总消耗: {total_tokens:>10,} | 💵 API预估费用: ${total_cost:.4f}")
    print("-" * 80)

    # Progress bar for genuine completed vs zero tokens
    bar_width = 40
    completed_ratio = genuine_attempts / total if total > 0 else 0
    filled_len = int(bar_width * completed_ratio)
    bar = "█" * filled_len + "░" * (bar_width - filled_len)
    print(f"  总进度: [{bar}] {completed_ratio * 100:.1f}% ({genuine_attempts}/{total})")
    print("-" * 80)

    print("  🏆 最近通过赛题 (Top 10):")
    for name, tok, dur in passed_list[-10:]:
        print(f"    ✅ {name:<32} | 耗时: {dur:>4}s | Tokens: {tok:>8,}")

    print("\n  ⚠️ 正在补考/待补考赛题 (剩余 {} 题):".format(zero_tokens))
    for name, _, _ in zero_token_list[:5]:
        print(f"    ⏳ {name}")
    if zero_tokens > 5:
        print(f"    ... 还有 {zero_tokens - 5} 道待补考")

    print("=" * 80)
    print("  💡 提示: 待补考全部归零时，将自动向左侧 Pi 发送完工通知生成最终战报。")
    print("=" * 80)

    return passed, genuine_attempts, zero_tokens


def main() -> None:
    notified = False
    while True:
        try:
            passed, genuine, zero_tokens = render_dashboard()
            if zero_tokens == 0 and genuine >= 89 and not notified:
                print("\n🎉 全部 89 题已全部完成真实做题与评测！正在触发左侧报告生成...")
                trigger_left_pane()
                notified = True
                break
        except Exception as e:
            print(f"[ERROR] 监控看板异常: {e}")
        time.sleep(4)


if __name__ == "__main__":
    main()
