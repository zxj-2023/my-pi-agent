"""Show status of the background batch evaluation runner."""

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
LOG_FILE = REPO_ROOT / "my-pi-eval" / "results" / "batch_run.log"
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "batch_run.pid"
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "official_pi_progress.json"


def main() -> None:
    print("================================================================================")
    print("Terminal-Bench 2.0 Official Pi 评测运行状态看板")
    print("================================================================================")

    # 1. Check process
    is_running = False
    pid_val = None
    if PID_FILE.exists():
        try:
            pid_val = int(PID_FILE.read_text().strip())
            check = subprocess.run(["tasklist", "/FI", f"PID eq {pid_val}"], capture_output=True, text=True)
            if str(pid_val) in check.stdout:
                is_running = True
        except Exception:
            pass

    status_str = f"[RUNNING] 运行中 (PID: {pid_val})" if is_running else "[STOPPED] 已停止 / 未运行"
    print(f"调度器进程状态: {status_str}")

    # 2. Check progress
    if PROGRESS_FILE.exists():
        try:
            prog = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            tasks = prog.get("tasks", {})
            total = prog.get("total_tasks", 89)
            completed = len(tasks)
            passed = sum(1 for t in tasks.values() if t.get("status") == "PASSED")
            failed = sum(1 for t in tasks.values() if t.get("status") == "FAILED")
            rate = (passed / completed * 100) if completed > 0 else 0.0

            print(f"总任务数: {total}")
            print(f"已完成: {completed} / {total} (通过: {passed}, 失败: {failed})")
            print(f"当前通过率: {rate:.1f}%")
            print("\n已完成任务列表:")
            for name, d in sorted(tasks.items()):
                st = "[PASS]" if d.get("status") == "PASSED" else "[FAIL]"
                print(f"  - [{st}] {name:<35} 耗时: {d.get('duration_sec', 0)}s, Tokens: {d.get('tokens', 0)}")
        except Exception as e:
            print(f"[WARN] 无法读取进度文件: {e}")

    # 3. Show log tail
    if LOG_FILE.exists():
        print("\n---------------- 最近 15 行运行日志 ----------------")
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line_item in lines[-15:]:
                print(line_item)
        except Exception as e:
            print(f"[WARN] 无法读取日志: {e}")
    print("================================================================================")


if __name__ == "__main__":
    main()
