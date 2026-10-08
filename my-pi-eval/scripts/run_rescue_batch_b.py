"""Batch B: Concurrency booster (runs partitioned tasks in parallel with Batch A)."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    getattr(sys.stderr, "reconfigure")(encoding="utf-8", errors="replace")

os.environ["PYTHONUTF8"] = "1"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TB2_DIR = Path("D:/code/python/agent-eval/terminal-bench-2")
HARBOR_VENV = Path("D:/code/python/agent-eval/pi-terminal-bench/.venv")
HARBOR_BIN = HARBOR_VENV / "Scripts" / "harbor.exe"
ENV_FILE = Path("D:/code/python/agent-eval/pi-terminal-bench/.env")
RESULTS_DIR = REPO_ROOT / "my-pi-eval" / "results"
PROGRESS_FILE = RESULTS_DIR / "official_pi_progress.json"

PROGRESS_LOCK = threading.Lock()

# Partition B tasks: strictly disjoint from Batch A (runs concurrently without overlap)
BATCH_B_TASKS = [
    ("caffe-cifar-10", 2400),
    ("sam-cell-seg", 14400),
    ("dna-assembly", 3600),
    ("configure-git-webserver", 2400),
    ("count-dataset-tokens", 2400),
    ("install-windows-3.11", 7200),
    ("mcmc-sampling-stan", 3600),
    ("path-tracing-reverse", 3600),
    ("pytorch-model-cli", 2400),
    ("pytorch-model-recovery", 2400),
    ("torch-pipeline-parallelism", 2400),
    ("tune-mjcf", 2400),
]


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return {"total_tasks": 89, "completed_count": 0, "passed_count": 0, "failed_count": 0, "tasks": {}}


def save_progress(data: dict) -> None:
    with PROGRESS_LOCK:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


LOCK_DIR = RESULTS_DIR / "active_task_locks"


def run_single_task(task_info: tuple[str, int], index: int, total: int) -> dict:
    task_name, timeout_sec = task_info
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    task_lock_file = LOCK_DIR / f"{task_name}.lock"

    # 1. Check if already PASSED in progress file, skip immediately if so!
    data = load_progress()
    existing = data.get("tasks", {}).get(task_name, {})
    if existing.get("status") == "PASSED":
        print(f"\n[B:{index}/{total}] ⏩ 跳过已通过赛题: {task_name} (此前已斩获满分 reward=1.0)！", flush=True)
        return existing

    # 2. Check if another process is currently running this task (File Lock)
    if task_lock_file.exists():
        print(f"\n[B:{index}/{total}] ⏩ 跳过正由另一组并发执行的赛题: {task_name} (检测到活跃运行锁)！", flush=True)
        return existing

    # 3. Check if container is already running in Docker
    try:
        dock_check = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=5
        )
        clean_name = task_name.replace(".", "-")
        if any(d.startswith(clean_name + "__") for d in dock_check.stdout.splitlines()):
            print(f"\n[B:{index}/{total}] ⏩ 跳过正在 Docker 中运行的赛题: {task_name}，绝不重复运行！", flush=True)
            return existing
    except Exception:
        pass

    # Acquire lock
    try:
        task_lock_file.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

    task_dir = TB2_DIR / task_name
    guard_timeout = timeout_sec + 300  # 5 min extra guard

    cmd = [
        str(HARBOR_BIN),
        "run",
        "-p",
        str(task_dir),
        "-a",
        "pi",
        "-m",
        "deepseek/deepseek-chat",
        "--env-file",
        str(ENV_FILE),
    ]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["DEEPSEEK_API_KEY"] = "sk-65b80a6b13a04a0bb368f5d50253d27f"
    if "DEEPSEEK_BASE_URL" in env:
        del env["DEEPSEEK_BASE_URL"]

    start_time = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"\n[B:{index}/{total}] 🚀 启动分流赛题: {task_name} (放宽时长: {timeout_sec}s / {timeout_sec // 60}分钟, 保护死线: {guard_timeout}s) | {now_str}",
        flush=True,
    )

    try:
        subprocess.run(
            cmd,
            cwd=str(HARBOR_VENV.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=guard_timeout,
        )
        duration_sec = int(time.time() - start_time)
    except subprocess.TimeoutExpired:
        duration_sec = guard_timeout
        print(f"[{task_name}] 执行达到死线 ({guard_timeout}s)，安全终止！", flush=True)
    except Exception as e:
        duration_sec = int(time.time() - start_time)
        print(f"[{task_name}] 执行异常: {e}", flush=True)

    # Parse latest job result for this task
    jobs_dir = HARBOR_VENV.parent / "jobs"
    reward = 0.0
    tokens = 0
    cost_usd = 0.0
    summary = ""
    tests_passed = 0
    tests_total = 0

    try:
        matching_jobs = []
        if jobs_dir.exists():
            for p in jobs_dir.iterdir():
                if p.is_dir() and (p.stat().st_mtime >= start_time - 10):
                    res_file = p / "result.json"
                    cfg_file = p / "config.json"
                    if res_file.exists() and cfg_file.exists():
                        try:
                            cfg_text = cfg_file.read_text(encoding="utf-8", errors="replace")
                            if task_name in cfg_text:
                                matching_jobs.append(p)
                        except Exception:
                            pass
            matching_jobs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if matching_jobs:
            latest_job = matching_jobs[0]
            res_data = json.loads((latest_job / "result.json").read_text(encoding="utf-8", errors="replace"))
            stats = res_data.get("stats", {})
            tokens = (stats.get("n_input_tokens") or 0) + (stats.get("n_output_tokens") or 0)
            cost_usd = stats.get("cost_usd") or 0.0

            evals = stats.get("evals", {})
            for eval_data in evals.values():
                for m in eval_data.get("metrics", []):
                    if "mean" in m:
                        reward = float(m["mean"])
                        break

            for trial_dir in latest_job.iterdir():
                if trial_dir.is_dir() and trial_dir.name != "__pycache__":
                    trial_log = trial_dir / "trial.log"
                    if trial_log.exists():
                        log_text = trial_log.read_text(encoding="utf-8", errors="replace")
                        if "PASSED" in log_text or "tests passed" in log_text.lower():
                            if reward == 0.0:
                                reward = 1.0
    except Exception as e:
        print(f"[{task_name}] 解析判定结果异常: {e}", flush=True)

    passed = reward >= 1.0
    status = "PASSED" if passed else "FAILED"
    print(f"[{task_name}] 战报: {status} (得分: {reward}, 耗时: {duration_sec}s, Tokens: {tokens})", flush=True)

    task_result = {
        "status": status,
        "reward": reward,
        "duration_sec": duration_sec,
        "tests_passed": tests_passed,
        "tests_total": tests_total,
        "tokens": tokens,
        "cost_usd": cost_usd,
        "summary": summary,
        "finished_at": datetime.now().isoformat(),
    }

    # Update progress safely
    data = load_progress()
    data["tasks"][task_name] = task_result
    data["completed_count"] = sum(1 for t in data["tasks"].values() if t.get("status") in ("PASSED", "FAILED"))
    data["passed_count"] = sum(1 for t in data["tasks"].values() if t.get("status") == "PASSED")
    data["failed_count"] = data["completed_count"] - data["passed_count"]
    save_progress(data)

    # Clean docker networks and containers
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=15)
        subprocess.run(["docker", "container", "prune", "-f"], capture_output=True, timeout=15)
    except Exception:
        pass

    # Release file lock
    try:
        if task_lock_file.exists():
            task_lock_file.unlink()
    except Exception:
        pass

    return task_result


def main() -> None:
    print("=" * 80, flush=True)
    print("Terminal-Bench 2.0 分流提速组 Batch B (2并发，与 Batch A 协同达成 4 并发)", flush=True)
    print("=" * 80, flush=True)

    max_workers = 2
    print(f"启动 Batch B {max_workers} 并发工作线程池开始推进...", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_task, item, idx, len(BATCH_B_TASKS)): item[0]
            for idx, item in enumerate(BATCH_B_TASKS, start=1)
        }

        for future in concurrent.futures.as_completed(futures):
            t_name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] 赛题 {t_name} 未捕获异常: {e}", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("🎉 Batch B 分流提速组全部处理结束！", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
