"""Pre-pull all 89 Docker images for Terminal-Bench 2.0 with retry and progress tracking."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

os.environ["PYTHONUTF8"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TB2_DIR = Path("D:/code/python/agent-eval/terminal-bench-2")
RESULTS_DIR = REPO_ROOT / "my-pi-eval" / "results"
PROGRESS_FILE = RESULTS_DIR / "image_pull_progress.json"


def get_local_images() -> set[str]:
    try:
        proc = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    except Exception as e:
        print(f"[WARN] Failed to query local docker images: {e}")
        return set()


def discover_task_images() -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    if not TB2_DIR.exists():
        print(f"[ERROR] TB2_DIR not found: {TB2_DIR}")
        return tasks

    for d in sorted(TB2_DIR.iterdir()):
        toml_path = d / "task.toml"
        if toml_path.exists():
            try:
                data = tomllib.loads(toml_path.read_text(encoding="utf-8", errors="replace"))
                img = data.get("environment", {}).get("docker_image")
                if img:
                    clean_img = img.replace("docker.io/", "")
                    tasks.append({"task_name": d.name, "image": clean_img})
            except Exception as e:
                print(f"[WARN] Failed to read {toml_path}: {e}")
    return tasks


BIG_IMAGES = {
    "mteb-retrieve": 1800,  # 8.24 GB -> 30 minutes timeout
    "pytorch-model-recovery": 900,  # 5.76 GB -> 15 minutes timeout
}


def pull_single_image(image: str, max_retries: int = 2, timeout: int = 360) -> bool:
    env = os.environ.copy()
    env["HTTP_PROXY"] = "http://127.0.0.1:7897"
    env["HTTPS_PROXY"] = "http://127.0.0.1:7897"
    env["ALL_PROXY"] = "socks5://127.0.0.1:7897"

    timeout_min = timeout // 60
    for attempt in range(1, max_retries + 1):
        print(f"  -> [尝试 {attempt}/{max_retries}] 正在拉取: {image} (单次超时: {timeout_min}分钟) ...", flush=True)
        start = time.time()
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                ["docker", "pull", image],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )

            def _stream_output(pipe: Any) -> None:
                try:
                    for line in iter(pipe.readline, ""):
                        clean = line.strip()
                        if clean:
                            print(f"     [docker] {clean}", flush=True)
                except Exception:
                    pass

            t = threading.Thread(target=_stream_output, args=(proc.stdout,), daemon=True)
            t.start()

            proc.wait(timeout=timeout)
            elapsed = int(time.time() - start)
            if proc.returncode == 0:
                print(f"  -> ✅ 成功完成: {image} (耗时 {elapsed}s)", flush=True)
                return True
            else:
                print(f"  -> ⚠️ 拉取失败 (code {proc.returncode})", flush=True)
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                except Exception:
                    proc.kill()
            print(f"  -> ⚠️ 拉取超时 ({timeout_min}分钟)！已强制切断并重试断点续传...", flush=True)
        except Exception as e:
            print(f"  -> ⚠️ 拉取异常: {e}", flush=True)

        if attempt < max_retries:
            time.sleep(3)  # Short pause before retry

    return False


def main() -> None:
    print("================================================================================", flush=True)
    print("Terminal-Bench 2.0 Docker 镜像批量预下载工具 (代理保障)", flush=True)
    print("================================================================================", flush=True)

    task_images = discover_task_images()
    print(f"共发现 {len(task_images)} 道任务镜像。", flush=True)

    local_images = get_local_images()
    cached: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []

    for item in task_images:
        img = item["image"]
        if img in local_images or f"docker.io/{img}" in local_images:
            cached.append(item)
        else:
            missing.append(item)

    print(f"本地已缓存: {len(cached)} 个镜像 (无需重新下载)", flush=True)
    print(f"待下载镜像: {len(missing)} 个镜像\n", flush=True)

    results: dict[str, Any] = {
        "updated_at": datetime.now().isoformat(),
        "total": len(task_images),
        "cached": len(cached),
        "downloaded": 0,
        "failed": 0,
        "failed_images": [],
    }

    if not missing:
        print("🎉 全部 89 个 Docker 镜像已在本地就绪！可以随时全并发评测！", flush=True)
        return

    # 田忌赛马策略：先冲刺常规轻量镜像，最后攻坚超大巨无霸镜像
    normal_missing: list[dict[str, str]] = []
    big_missing: list[dict[str, str]] = []

    for item in missing:
        if item["task_name"] in BIG_IMAGES or any(k in item["image"] for k in ["mteb-retrieve"]):
            big_missing.append(item)
        else:
            normal_missing.append(item)

    ordered_missing = normal_missing + big_missing

    print(
        f"👉 策略分配: [轻量镜像冲刺队列] {len(normal_missing)} 个 | [巨无霸攻坚队列] {len(big_missing)} 个\n",
        flush=True,
    )

    for i, item in enumerate(ordered_missing, start=1):
        task_name = item["task_name"]
        image = item["image"]
        task_timeout = BIG_IMAGES.get(task_name, 360)
        category = "巨无霸" if task_name in BIG_IMAGES else "常规"

        print(f"\n[{i}/{len(ordered_missing)}] [{category}] 任务: {task_name} | 镜像: {image}", flush=True)

        success = pull_single_image(image, max_retries=2, timeout=task_timeout)
        if success:
            results["downloaded"] += 1
        else:
            print("  -> ⏭️ 两次尝试均超时或失败，已主动跳过，继续下一个任务！", flush=True)
            results["failed"] += 1
            results["failed_images"].append({"task_name": task_name, "image": image})

        # Save progress
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n================================================================================", flush=True)
    print(
        f"预下载流程结束！成功: {results['downloaded']}, 失败: {results['failed']}, 之前已存在: {len(cached)}",
        flush=True,
    )
    print("================================================================================", flush=True)


if __name__ == "__main__":
    main()
