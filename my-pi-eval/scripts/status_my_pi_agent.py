"""Real-time live status dashboard for self-developed MyPiAgent on Terminal-Bench 2.1."""

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
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "my_pi_agent_progress.json"
TB2_TASKS_DIR = Path("D:/code/python/agent-eval/terminal-bench-2")

PHYSICAL_EXCLUDED = {
    "make-doom-for-mips",
    "caffe-cifar-10",
    "extract-moves-from-video",
    "sam-cell-seg",
}


def get_85_tasks() -> list[str]:
    all_dirs = [d.name for d in TB2_TASKS_DIR.iterdir() if d.is_dir() and (d / "task.toml").exists()]
    return [t for t in sorted(all_dirs) if t not in PHYSICAL_EXCLUDED]


def main() -> None:
    print("=" * 80)
    print("🏆 自研 MyPiAgent @ Terminal-Bench 2.1 (85 赛题) 实时看板")
    print("=" * 80)

    tasks_85 = get_85_tasks()

    # 1. Active docker containers
    active_now = []
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
                if tname in tasks_85 and "hour" not in uptime:
                    active_now.append((tname, uptime.strip()))
    except Exception:
        pass

    print("🔥 当前 4 并发正在实战攻坚中的赛题:")
    if active_now:
        for tname, uptime in active_now:
            print(f"   ▶ [{tname:<32}] 已活跃运行: {uptime}")
    else:
        print("   (暂无活跃容器，或正在调度轮换中)")

    # 2. Check Progress File
    prog_data = {}
    if PROGRESS_FILE.exists():
        try:
            prog_data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    tasks = prog_data.get("tasks", {})
    passed = [k for k, v in tasks.items() if v.get("status") == "PASSED"]
    failed = [k for k, v in tasks.items() if v.get("status") == "FAILED"]
    total = len(tasks_85)
    completed = len(passed) + len(failed)
    win_rate = (len(passed) / total * 100) if total else 0.0

    print("\n" + "-" * 80)
    print(
        f"📊 全局 85 题进度: 已完成 {completed}/{total} 道 "
        f"| 满分通过: {len(passed)} 道 | 胜率: {win_rate:.2f}% | 剩余未过: {len(failed)} 道"
    )
    print("-" * 80)

    # 3. Task matrix tail
    active_names = {t[0] for t in active_now}
    print("\n🎯 赛题矩阵实况 (前 15 道样例展示):")
    for i, tname in enumerate(tasks_85[:15], start=1):
        info = tasks.get(tname, {})
        status = info.get("status")
        reward = info.get("reward", 0.0)
        dur = info.get("duration_sec", 0)
        tok = info.get("tokens", 0)

        if tname in active_names:
            badge = "⏳ [RUNNING 正在攻坚]"
            extra = "4并发执行中..."
        elif status == "PASSED":
            badge = "✅ [PASSED 满分通过!]"
            extra = f"耗时: {dur}s | 消耗: {tok:,} tok"
        elif status == "FAILED":
            badge = "❌ [FAILED 未获满分]"
            extra = f"得分: {reward} | {dur}s"
        else:
            badge = "💤 [WAITING 排队等待]"
            extra = "等待空闲线程..."

        print(f"   {i:02d}. {badge:<22} {tname:<32} {extra}")

    print("\n" + "=" * 80)
    print(f"💡 对标原厂 Pi 官方基准: 72 胜 / 80.90% | 当前 MyPiAgent 满分通过: {len(passed)} 道")
    print("=" * 80)


if __name__ == "__main__":
    main()
