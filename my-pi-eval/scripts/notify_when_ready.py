"""Background watcher that sends Herdr toast notification when all 89 images are pulled."""

import json
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull_progress.json"
PID_FILE = REPO_ROOT / "my-pi-eval" / "results" / "image_pull.pid"
READY_FLAG = REPO_ROOT / "my-pi-eval" / "results" / "images_ready.flag"


def main() -> None:
    while True:
        if PROGRESS_FILE.exists():
            try:
                data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
                total = data.get("total", 89)
                cached = data.get("cached", 0)
                downloaded = data.get("downloaded", 0)
                done = cached + downloaded
                if done >= total and total > 0:
                    READY_FLAG.write_text("DONE", encoding="utf-8")
                    subprocess.run(
                        [
                            "herdr",
                            "notification",
                            "show",
                            "🎉 Docker 镜像全部下载完成！",
                            "--body",
                            f"Terminal-Bench 2.0 全部 {total} 个镜像已就绪，可以启动 5 并发评测！",
                            "--sound",
                            "done",
                        ],
                        capture_output=True,
                    )
                    break
            except Exception:
                pass
        time.sleep(5)


if __name__ == "__main__":
    main()
