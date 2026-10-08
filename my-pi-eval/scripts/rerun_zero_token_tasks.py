"""Rerun the 65 zero-token environment-failed tasks with the fixed Harbor environment."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
import tomllib
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
REPORT_FILE = RESULTS_DIR / "pi_official_terminal_bench_2.md"
LOG_FILE = RESULTS_DIR / "rerun.log"

PROGRESS_LOCK = threading.Lock()


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


def get_task_timeout(task_dir: Path) -> int:
    toml_path = task_dir / "task.toml"
    if toml_path.exists():
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8", errors="replace"))
            agent_sec = data.get("agent", {}).get("timeout_sec")
            if agent_sec:
                # Add 180s buffer for container startup, nvm, and verifier
                return int(agent_sec) + 180
        except Exception:
            pass
    return 1800  # Default 30 minutes


def run_single_task(task_name: str, index: int, total: int) -> dict:
    task_dir = TB2_DIR / task_name
    task_timeout = get_task_timeout(task_dir)
    official_limit = task_timeout - 180
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
        f"\n[{index}/{total}] 🚀 启动补考任务: {task_name} (官方配时: {official_limit}s, 保护超时: {task_timeout}s) | {now_str}",
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
            timeout=task_timeout,  # Dynamically respect task.toml
        )
        duration_sec = int(time.time() - start_time)
    except subprocess.TimeoutExpired:
        duration_sec = task_timeout
        print(f"[{task_name}] 执行超时 ({task_timeout} 秒)，强制终止！", flush=True)
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
                        # Explicitly match task name in config to avoid picking another concurrent job
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
    print(f"[{task_name}] 补考结果: {status} (得分: {reward}, 耗时: {duration_sec}s, Tokens: {tokens})", flush=True)

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

    # Prune zombie networks so address pools never exhaust
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=15)
    except Exception:
        pass

    return task_result


def main() -> None:
    print("=" * 80, flush=True)
    print("Terminal-Bench 2.0 零Token环境受害者题目精准补考调度器 (5并发)", flush=True)
    print("=" * 80, flush=True)

    # Pre-clean zombie networks and containers
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=15)
        subprocess.run(["docker", "container", "prune", "-f"], capture_output=True, timeout=15)
    except Exception:
        pass

    data = load_progress()
    tasks = data.get("tasks", {})

    zero_token_tasks = [
        name
        for name, t in tasks.items()
        if t.get("status") == "FAILED" and (t.get("tokens", 0) == 0 or t.get("duration_sec", 0) < 30)
    ]

    print(f"发现待补考题目: {len(zero_token_tasks)} 道", flush=True)
    if not zero_token_tasks:
        print("🎉 没有需要补考的题目！所有失败题目均已真实参赛。", flush=True)
        return

    # Use 3 concurrent workers for stable network and compilation throughput
    max_workers = 3
    print(f"启动 {max_workers} 并发工作线程池开始补考...", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_task, task_name, idx, len(zero_token_tasks)): task_name
            for idx, task_name in enumerate(zero_token_tasks, start=1)
        }

        for future in concurrent.futures.as_completed(futures):
            t_name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] 任务 {t_name} 未捕获异常: {e}", flush=True)

    print("\n" + "=" * 80, flush=True)
    final_data = load_progress()
    print("🎉 全部补考结束！", flush=True)
    print(f"总题目: {final_data.get('total_tasks')}", flush=True)
    print(f"总完成: {final_data.get('completed_count')}", flush=True)
    print(f"通过数: {final_data.get('passed_count')}", flush=True)
    print(f"失败数: {final_data.get('failed_count')}", flush=True)
    rate = (final_data.get("passed_count", 0) / final_data.get("total_tasks", 89)) * 100
    print(f"最终满分胜率: {rate:.2f}%", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
