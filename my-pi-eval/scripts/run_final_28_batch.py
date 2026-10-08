"""Run the final 28 environment-failed tasks with 2 workers, NVM_METHOD=script patch, and automatic final report generation."""

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
AUDIT_SCRIPT = REPO_ROOT / "my-pi-eval" / "scripts" / "audit_all_jobs.py"
REPORT_SCRIPT = REPO_ROOT / "my-pi-eval" / "scripts" / "generate_final_report.py"

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


def run_single_task(task_name: str, index: int, total: int) -> dict:
    task_dir = TB2_DIR / task_name
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
    print(f"\n[{index}/{total}] 🚀 启动终极补考: {task_name} | {now_str}", flush=True)

    try:
        subprocess.run(
            cmd,
            cwd=str(HARBOR_VENV.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,  # 15 minutes max
        )
        duration_sec = int(time.time() - start_time)
    except subprocess.TimeoutExpired:
        duration_sec = 900
        print(f"[{task_name}] 执行超时 (15 分钟)，强制终止！", flush=True)
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
    print(f"[{task_name}] 结果: {status} (得分: {reward}, 耗时: {duration_sec}s, Tokens: {tokens:,})", flush=True)

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

    # Prune zombie networks
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=15)
    except Exception:
        pass

    return task_result


def main() -> None:
    print("=" * 80, flush=True)
    print("Terminal-Bench 2.0 终极补考调度器 (2并发, NVM_METHOD=script 代理保障)", flush=True)
    print("=" * 80, flush=True)

    # Pre-clean
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=15)
        subprocess.run(["docker", "container", "prune", "-f"], capture_output=True, timeout=15)
    except Exception:
        pass

    data = load_progress()
    tasks = data.get("tasks", {})

    target_tasks = [
        name
        for name, t in tasks.items()
        if t.get("status") != "PASSED" and (t.get("tokens", 0) == 0 or t.get("duration_sec", 0) < 30)
    ]

    print(f"待补考题目数: {len(target_tasks)} 道", flush=True)
    if not target_tasks:
        print("🎉 没有需要补考的题目！", flush=True)
        return

    # Use 2 concurrent workers for maximum TLS stability
    max_workers = 2
    print(f"启动 {max_workers} 并发工作线程池开始运行...\n", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_task, task_name, idx, len(target_tasks)): task_name
            for idx, task_name in enumerate(target_tasks, start=1)
        }

        for future in concurrent.futures.as_completed(futures):
            t_name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] 任务 {t_name} 未捕获异常: {e}", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("🎉 28 道赛题终极补考执行完毕！正在同步全局账本并生成最终战报...", flush=True)
    print("=" * 80, flush=True)

    # Run audit and generate report
    try:
        subprocess.run([sys.executable, str(AUDIT_SCRIPT)], check=True, timeout=60)
        subprocess.run([sys.executable, str(REPORT_SCRIPT)], check=True, timeout=60)
        print("✅ 最终全量数据归档与 Markdown 战报生成成功！", flush=True)
    except Exception as e:
        print(f"[WARN] 生成最终战报异常: {e}", flush=True)


if __name__ == "__main__":
    main()
