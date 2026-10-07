"""Query progress of Docker image pre-downloading."""

import json
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
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull_progress.json"
LOG_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.log"
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.pid"


def main() -> None:
    is_running = False
    pid_str = "无"
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            pid_str = str(pid)
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="replace",
            )
            if str(pid) in check.stdout:
                is_running = True
        except Exception:
            pass

    status_icon = "🟢 正在高速拉取中" if is_running else "⚪ 已停止或已完成"
    print("================================================================================")
    print(f"Docker 镜像下载状态: {status_icon} (PID: {pid_str})")
    print("================================================================================")

    if PROGRESS_FILE.exists():
        try:
            data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            total = data.get("total", 89)
            cached = data.get("cached", 0)
            downloaded = data.get("downloaded", 0)
            failed = data.get("failed", 0)
            done = cached + downloaded
            pct = (done / total) * 100 if total else 0

            print(f"总体进度: {done}/{total} ({pct:.1f}%)")
            print(f"  - 原本已有缓存: {cached}")
            print(f"  - 新下载成功:   {downloaded}")
            print(f"  - 跳过/待后置:   {failed}")
            print(f"  - 剩余待下载:   {total - done}")

            failed_images = data.get("failed_images", [])
            if failed_images:
                print(f"\n⚠️ 跳过/待后置镜像列表 ({len(failed_images)} 个):")
                for item in failed_images:
                    print(f"  - {item['task_name']}: {item['image']}")
        except Exception as e:
            print(f"[WARN] 无法解析进度文件: {e}")
    else:
        print("[INFO] 尚未生成进度文件。")

    if LOG_FILE.exists():
        print("\n--- 最近 15 行下载日志 ---")
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-15:]:
            print(line)
        print("--------------------------")


if __name__ == "__main__":
    main()
