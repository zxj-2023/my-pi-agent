"""Real-time live dashboard for the 4-worker 19-task rescue run and global Terminal-Bench 2.1 status."""

import json
import subprocess
import sys
from pathlib import Path

# Safe encoding configuration
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = Path("D:/code/python/agent-eval/pi-terminal-bench")
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "official_pi_progress.json"

TARGET_19_TASKS = [
    "bn-fit-modify",
    "build-pov-ray",
    "caffe-cifar-10",
    "configure-git-webserver",
    "constraints-scheduling",
    "custom-memory-heap-crash",
    "dna-assembly",
    "extract-moves-from-video",
    "gpt2-codegolf",
    "make-doom-for-mips",
    "model-extraction-relu-logits",
    "overfull-hbox",
    "path-tracing-reverse",
    "pypi-server",
    "pytorch-model-recovery",
    "qemu-alpine-ssh",
    "qemu-startup",
    "torch-pipeline-parallelism",
    "tune-mjcf",
]


def main() -> None:
    print("=" * 80)
    print("🏆 Terminal-Bench 2.1 (DeepSeek-V4.1 + Pi) 4 并发大营救实时看板")
    print("=" * 80)

    # 1. Check active docker containers
    active_tasks = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.RunningFor}}"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout.splitlines():
            if "__env-main-" in line:
                cname, uptime = line.split("\t", 1)
                tname = cname.split("__")[0]
                if tname in TARGET_19_TASKS:
                    active_tasks.append((tname, uptime.strip()))
    except Exception:
        pass

    print("🔥 当前 4 并发正在实战攻坚中的赛题:")
    active_now = []
    if active_tasks:
        for tname, uptime in active_tasks:
            if "hour" not in uptime and "day" not in uptime:
                active_now.append((tname, uptime))
                print(f"   ▶ [{tname:<30}] 已活跃运行: {uptime}")
    if not active_now:
        print("   (正在调度轮换或准备启动新容器...)")

    # 2. Check Global Progress
    prog_data = {}
    if PROGRESS_FILE.exists():
        try:
            prog_data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    tasks = prog_data.get("tasks", {})
    passed = [k for k, v in tasks.items() if v.get("status") == "PASSED"]
    failed = [k for k, v in tasks.items() if v.get("status") == "FAILED"]
    total = 89
    win_rate = (len(passed) / total * 100) if total else 0.0

    print("\n" + "-" * 80)
    print(
        f"📊 全局 89 题大盘战况: 满分通过 {len(passed)} / {total} 道 "
        f"| 胜率: {win_rate:.2f}% | 剩余未过: {len(failed)} 道"
    )
    print("-" * 80)

    # 3. Check 19-task rescue status
    print("\n🎯 19 道受害赛题营救矩阵 (Rescue Status):")
    rescued_count = 0
    active_names = {t[0] for t in active_tasks}
    for i, tname in enumerate(TARGET_19_TASKS, start=1):
        info = tasks.get(tname, {})
        status = info.get("status", "PENDING")
        reward = info.get("reward", 0.0)
        dur = info.get("duration_sec", 0)
        tok = info.get("tokens", 0)

        if tname in active_names:
            badge = "⏳ [RUNNING 正在攻坚]"
            extra = "4并发执行中..."
        elif status == "PASSED":
            rescued_count += 1
            badge = "✅ [PASSED 满分营救!]"
            extra = f"耗时: {dur}s | 消耗: {tok:,} tok"
        elif status == "FAILED" and dur > 0:
            badge = "❌ [FAILED 待救/已跑]"
            extra = f"前次得分: {reward} | {dur}s"
        else:
            badge = "💤 [WAITING 排队等待]"
            extra = "等待空闲线程..."

        print(f"   {i:02d}. {badge:<22} {tname:<30} {extra}")

    print("\n" + "=" * 80)
    print(f"💡 本轮已确认营救成功: {rescued_count} 道 | 目标冲刺胜率: {(len(passed)) / total * 100:.2f}%")
    print("=" * 80)


if __name__ == "__main__":
    main()
