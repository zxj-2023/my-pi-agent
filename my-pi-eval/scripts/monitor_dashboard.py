"""Live Terminal Dashboard & Notifier for Docker Image Downloads."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

os.environ["PYTHONUTF8"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull_progress.json"
LOG_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.log"
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.pid"
READY_FLAG = REPO_ROOT / "my-pi-eval" / "results" / "images_ready.flag"


def is_puller_running() -> tuple[bool, str]:
    if not PID_FILE.exists():
        return False, "无"
    try:
        pid = int(PID_FILE.read_text().strip())
        check = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        if str(pid) in check.stdout:
            return True, str(pid)
    except Exception:
        pass
    return False, "已退出"


def send_herdr_notification(title: str, body: str, sound: str = "done") -> None:
    try:
        subprocess.run(
            ["herdr", "notification", "show", title, "--body", body, "--sound", sound],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as e:
        print(f"\a[Notification fallback] {title}: {body} ({e})")


def render_bar(current: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return "[" + " " * width + "]"
    fraction = min(1.0, max(0.0, current / total))
    filled = int(fraction * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = fraction * 100
    return f"[{bar}] {current}/{total} ({pct:.1f}%)"


def main() -> None:
    print("\033[2J\033[H", end="", flush=True)  # Clear screen

    while True:
        running, pid_str = is_puller_running()
        now_str = datetime.now().strftime("%H:%M:%S")

        total = 89
        cached = 0
        downloaded = 0
        failed = 0
        failed_images: list[dict[str, str]] = []

        if PROGRESS_FILE.exists():
            try:
                data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
                total = data.get("total", 89)
                cached = data.get("cached", 0)
                downloaded = data.get("downloaded", 0)
                failed = data.get("failed", 0)
                failed_images = data.get("failed_images", [])
            except Exception:
                pass

        done = cached + downloaded
        progress_bar = render_bar(done, total, width=32)

        # Get recent lines from log
        recent_log: list[str] = []
        current_task_info = "等待中..."
        if LOG_FILE.exists():
            try:
                lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
                recent_log = lines[-6:] if len(lines) >= 6 else lines
                for line in reversed(lines):
                    if line.startswith("[") and "任务:" in line:
                        current_task_info = line.strip()
                        break
            except Exception:
                pass

        # Check completion
        if done >= total and total > 0:
            READY_FLAG.write_text(f"COMPLETED at {datetime.now().isoformat()}\n", encoding="utf-8")
            print("\033[H", end="", flush=True)
            print("================================================================================")
            print("  🎉🎉🎉 Terminal-Bench 2.0 全部 89 个 Docker 镜像下载完成！ 🎉🎉🎉")
            print("================================================================================")
            print(f"完成时间: {now_str}")
            print(f"总计: {total} | 原始缓存: {cached} | 新下载: {downloaded} | 失败: {failed}")
            print("\n正在通过 Herdr 发送桌面完成提醒...")
            send_herdr_notification(
                "🎉 Docker 镜像下载完成！",
                f"Terminal-Bench 2.0 全部 {total} 个镜像已全部就绪，可以随时启动 5 并发评测！",
                sound="done",
            )
            print("\a\a\a已发出通知与提示音！按 Ctrl+C 退出监控。")
            break

        if not running and done > 0 and done < total:
            # Puller stopped prematurely
            status_text = f"⚠️ 进程已中断 (PID: {pid_str})"
        else:
            status_text = f"🟢 正在拉取中 (PID: {pid_str})"

        # Render dashboard
        header = [
            "================================================================================",
            f"  🐳 Terminal-Bench 2.0 镜像下载实时大盘监控 [{now_str}]",
            "================================================================================",
            f" 运行状态: {status_text}",
            f" 下载进度: {progress_bar}",
            f" 数据统计: 已就绪 {done}/{total} | 初始缓存 {cached} | 新拉取 {downloaded} | 失败 {failed}",
            "--------------------------------------------------------------------------------",
            f" 当前正在拉取: {current_task_info}",
            "--------------------------------------------------------------------------------",
            " [实时日志 (最新)]: ",
        ]

        for log_line in recent_log:
            header.append(f"   {log_line[:75]}")

        if failed_images:
            header.append("--------------------------------------------------------------------------------")
            header.append(
                f" ⚠️ 失败镜像 ({len(failed_images)} 个): " + ", ".join(x["task_name"] for x in failed_images[:3])
            )

        header.append("================================================================================")
        header.append(" (按 Ctrl+C 可退出看板，后台下载不受影响)")

        print("\033[2J\033[H", end="", flush=True)
        print("\n".join(header), flush=True)

        time.sleep(3)


if __name__ == "__main__":
    main()
