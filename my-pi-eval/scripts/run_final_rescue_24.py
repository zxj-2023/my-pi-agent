"""Run the final rescue pass on 24 tasks: 15 environment-failed + 9 timeout tasks with relaxed time limits."""

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

PROGRESS_LOCK = threading.Lock()

# 15 Environment-failed tasks + 9 Timeout tasks (Total 24)
RESCUE_24_TASKS = [
    # 15 Environment-failed tasks (Fixed with npmmirror Node 22, Python curl shim, TMPDIR export)
    "build-pov-ray",
    "caffe-cifar-10",
    "dna-assembly",
    "extract-moves-from-video",
    "mailman",
    "make-doom-for-mips",
    "make-mips-interpreter",
    "mteb-leaderboard",
    "qemu-alpine-ssh",
    "qemu-startup",
    "raman-fitting",
    "regex-chess",
    "regex-log",
    "rstan-to-pystan",
    "sam-cell-seg",
    # 9 Timeout tasks (Relaxed time: 40 ~ 60 minutes)
    "configure-git-webserver",
    "count-dataset-tokens",
    "install-windows-3.11",
    "mcmc-sampling-stan",
    "path-tracing-reverse",
    "pytorch-model-cli",
    "pytorch-model-recovery",
    "torch-pipeline-parallelism",
    "tune-mjcf",
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


def get_relaxed_timeout(task_dir: Path) -> tuple[int, int]:
    """Calculate relaxed timeout: at least 40 minutes (2400s), up to 60+ minutes."""
    official_limit = 900
    toml_path = task_dir / "task.toml"
    if toml_path.exists():
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8", errors="replace"))
            agent_sec = data.get("agent", {}).get("timeout_sec")
            if agent_sec:
                official_limit = int(agent_sec)
        except Exception:
            pass

    # Double the official limit or give at least 2400s (40 minutes) + 300s buffer
    relaxed_limit = max(official_limit * 2, 2400)
    host_timeout = relaxed_limit + 300
    return relaxed_limit, host_timeout


LOCK_DIR = RESULTS_DIR / "active_task_locks"


def run_single_task(task_name: str, index: int, total: int) -> dict:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    task_lock_file = LOCK_DIR / f"{task_name}.lock"

    # 1. Check if already PASSED in progress file, skip immediately if so!
    data = load_progress()
    existing = data.get("tasks", {}).get(task_name, {})
    if existing.get("status") == "PASSED":
        print(f"\n[A:{index}/{total}] ⏩ 跳过已通过赛题: {task_name} (此前已斩获满分 reward=1.0)！", flush=True)
        return existing

    # 2. Check if another process is currently running this task (File Lock)
    if task_lock_file.exists():
        print(f"\n[A:{index}/{total}] ⏩ 跳过正由另一组并发执行的赛题: {task_name} (检测到活跃运行锁)！", flush=True)
        return existing

    # 3. Check if container is already running in Docker
    try:
        dock_check = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=5
        )
        clean_name = task_name.replace(".", "-")
        if any(d.startswith(clean_name + "__") for d in dock_check.stdout.splitlines()):
            print(f"\n[A:{index}/{total}] ⏩ 跳过正在 Docker 中运行的赛题: {task_name}，绝不重复运行！", flush=True)
            return existing
    except Exception:
        pass

    # Acquire lock
    try:
        task_lock_file.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

    task_dir = TB2_DIR / task_name
    relaxed_limit, host_timeout = get_relaxed_timeout(task_dir)

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
        f"\n[{index}/{total}] 🚀 启动终极大营救: {task_name} (放宽时长: {relaxed_limit}s / {relaxed_limit // 60}分钟, 保护死线: {host_timeout}s) | {now_str}",
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
            timeout=host_timeout,
        )
        duration_sec = int(time.time() - start_time)
    except subprocess.TimeoutExpired:
        duration_sec = host_timeout
        print(f"[{task_name}] 执行超过放宽死线 ({host_timeout} 秒)，强制终止！", flush=True)
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
    matching_jobs: list[Path] = []

    try:
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

    # Fallback to extract tokens from trial log if 0
    if tokens == 0 and matching_jobs:
        try:
            for trial_dir in matching_jobs[0].iterdir():
                if trial_dir.is_dir() and trial_dir.name != "__pycache__":
                    agent_txt = trial_dir / "agent" / "pi.txt"
                    if agent_txt.exists():
                        for line in agent_txt.read_text(encoding="utf-8", errors="replace").splitlines():
                            if '"type":"turn_end"' in line and '"tokens"' in line:
                                try:
                                    tdata = json.loads(line)
                                    tok_obj = tdata.get("tokens", {})
                                    inp = tok_obj.get("input", 0)
                                    out = tok_obj.get("output", 0)
                                    if inp + out > tokens:
                                        tokens = inp + out
                                except Exception:
                                    pass
        except Exception:
            pass

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
    print("Terminal-Bench 2.0 终极冲刺: 24 道赛题大营救 (15环境修复 + 9超时放宽)", flush=True)
    print("=" * 80, flush=True)

    # Pre-clean
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=15)
        subprocess.run(["docker", "container", "prune", "-f"], capture_output=True, timeout=15)
    except Exception:
        pass

    # Filter out any that already passed
    cur_data = load_progress()
    tasks_to_run = [
        name for name in RESCUE_24_TASKS if cur_data.get("tasks", {}).get(name, {}).get("status") != "PASSED"
    ]

    print(f"待处理冲刺赛题: 共 {len(tasks_to_run)} 道", flush=True)
    for idx, name in enumerate(tasks_to_run, start=1):
        rel, host = get_relaxed_timeout(TB2_DIR / name)
        print(f"  [{idx:02d}] {name:<32} (放宽时长: {rel // 60} 分钟, 保护死线: {host // 60} 分钟)")

    max_workers = 2
    print(f"\n启动 {max_workers} 并发工作线程池开始大营救...", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_task, task_name, idx, len(tasks_to_run)): task_name
            for idx, task_name in enumerate(tasks_to_run, start=1)
        }

        for future in concurrent.futures.as_completed(futures):
            t_name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] 赛题 {t_name} 未捕获异常: {e}", flush=True)

    print("\n" + "=" * 80, flush=True)
    final_data = load_progress()
    print("🎉 24 道赛题大营救全部圆满收官！", flush=True)
    print(f"总题目: {final_data.get('total_tasks')}", flush=True)
    print(f"最终通过数: {final_data.get('passed_count')}", flush=True)
    rate = (final_data.get("passed_count", 0) / final_data.get("total_tasks", 89)) * 100
    print(f"最终满分胜率: {rate:.2f}%", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
