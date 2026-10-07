"""Start the background Docker image pre-downloader."""

import os
import subprocess
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

os.environ["PYTHONUTF8"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "my-pi-eval" / "scripts" / "pull_all_images.py"
LOG_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.log"
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.pid"


def main() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            check = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            if str(pid) in check.stdout:
                print(f"[INFO] 镜像拉取器已经在运行中 (PID: {pid})。")
                print(f"查看日志: Get-Content -Wait -Tail 30 {LOG_FILE}")
                return
        except Exception:
            pass

    try:
        log_handle = open(LOG_FILE, "a", encoding="utf-8")
        log_handle.write("\n\n=== 启动镜像预下载会话 ===\n")
        log_handle.flush()
    except Exception as e:
        print(f"[ERROR] Failed to open log file {LOG_FILE}: {e}")
        return

    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    py_bin = str(venv_python) if venv_python.exists() else sys.executable

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [py_bin, str(SCRIPT)],
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )

    PID_FILE.write_text(str(proc.pid))
    print("================================================================================")
    print("🚀 Terminal-Bench 2.0 镜像批量下载器已在后台启动！")
    print(f"进程 PID: {proc.pid}")
    print(f"下载日志: {LOG_FILE}")
    print("查看状态: uv run python my-pi-eval/scripts/status_pull.py")
    print("================================================================================")


if __name__ == "__main__":
    main()
