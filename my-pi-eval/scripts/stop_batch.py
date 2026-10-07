"""Stop the background batch evaluation runner."""

import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "batch_run.pid"


def main() -> None:
    if not PID_FILE.exists():
        print("[INFO] 没有找到正在运行的 PID 文件。")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        print(f"正在终止调度器进程树 (PID: {pid})...")
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True)
        print("[SUCCESS] 评测调度器已成功终止。")
    except Exception as e:
        print(f"[ERROR] 终止进程失败: {e}")
    finally:
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
