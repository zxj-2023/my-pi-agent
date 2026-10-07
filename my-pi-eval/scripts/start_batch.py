"""Start the background batch evaluation runner."""

import os
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "my-pi-eval" / "scripts" / "run_official_pi_tb2.py"
LOG_FILE = REPO_ROOT / "my-pi-eval" / "results" / "batch_run.log"
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "batch_run.pid"


def main() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if running
            check = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            if str(pid) in check.stdout:
                print(f"[INFO] 评测调度器已经在运行中 (PID: {pid})。")
                print(f"查看日志: Get-Content -Wait -Tail 30 {LOG_FILE}")
                return
        except Exception:
            pass

    try:
        log_handle = open(LOG_FILE, "a", encoding="utf-8")
        log_handle.write(f"\n\n=== 启动新评测会话: {sys.executable} ===\n")
        log_handle.flush()
    except Exception as e:
        print(f"[ERROR] Failed to open log file {LOG_FILE}: {e}")
        return

    # Use python executable from root .venv or current sys.executable
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    py_bin = str(venv_python) if venv_python.exists() else sys.executable

    # Launch detached process on Windows
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    # Concurrency argument
    concurrency = 5
    if len(sys.argv) > 1:
        try:
            concurrency = int(sys.argv[1])
        except ValueError:
            pass

    proc = subprocess.Popen(
        [py_bin, str(SCRIPT), "-c", str(concurrency)],
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )

    PID_FILE.write_text(str(proc.pid))
    print("================================================================================")
    print(f"[SUCCESS] Official Pi Terminal-Bench 2.0 全量挂机评测已启动（并发数: {concurrency}）！")
    print(f"进程 PID: {proc.pid}")
    print(f"日志输出: {LOG_FILE}")
    print("实时状态: uv run python my-pi-eval/scripts/status_batch.py")
    print("终止挂机: uv run python my-pi-eval/scripts/stop_batch.py")
    print("================================================================================")


if __name__ == "__main__":
    main()
