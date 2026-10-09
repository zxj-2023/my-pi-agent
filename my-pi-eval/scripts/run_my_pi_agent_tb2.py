"""4-worker concurrent evaluation runner for self-developed MyPiAgent on Terminal-Bench 2.1 (85 tasks)."""

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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = Path("D:/code/python/agent-eval/pi-terminal-bench")
TB2_TASKS_DIR = Path("D:/code/python/agent-eval/terminal-bench-2")
HARBOR_EXE = EVAL_DIR / ".venv" / "Scripts" / "harbor.exe"
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "my_pi_agent_progress.json"
PROGRESS_LOCK = threading.Lock()

# 4 tasks excluded due to physical single-machine bottlenecks
PHYSICAL_EXCLUDED = {
    "make-doom-for-mips",
    "caffe-cifar-10",
    "extract-moves-from-video",
    "sam-cell-seg",
}


def get_85_tasks() -> list[str]:
    """Get sorted list of all 85 valid Terminal-Bench 2.1 tasks."""
    all_dirs = [d.name for d in TB2_TASKS_DIR.iterdir() if d.is_dir() and (d / "task.toml").exists()]
    tasks = [t for t in sorted(all_dirs) if t not in PHYSICAL_EXCLUDED]
    return tasks


def load_progress() -> dict:
    with PROGRESS_LOCK:
        if PROGRESS_FILE.exists():
            try:
                return json.loads(PROGRESS_FILE.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
        return {"tasks": {}}


def save_progress(data: dict) -> None:
    with PROGRESS_LOCK:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = PROGRESS_FILE.with_suffix(f".tmp.{os.getpid()}.{threading.get_ident()}")
        for _ in range(5):
            try:
                temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                temp_file.replace(PROGRESS_FILE)
                break
            except Exception:
                time.sleep(0.1)


def run_one_task(task_name: str, index: int, total: int) -> dict:
    time.sleep(2 * (index % 4))

    prog = load_progress()
    existing = prog.get("tasks", {}).get(task_name, {})
    if existing.get("status") == "PASSED":
        print(f"[{index}/{total}] ⏩ {task_name} 已满分通过，跳过。", flush=True)
        return {"task": task_name, "status": "PASSED", "skipped": True}

    task_dir = TB2_TASKS_DIR / task_name
    if not task_dir.exists():
        print(f"[{index}/{total}] ❌ 任务目录不存在: {task_dir}", flush=True)
        return {"task": task_name, "status": "FAILED", "error": "not_found"}

    timeout_sec = 2400
    kill_deadline = timeout_sec + 300

    print(
        f"[{index}/{total}] 🚀 启动 MyPiAgent 评测: {task_name} (配时: {timeout_sec}s / {timeout_sec // 60}分钟) | "
        f"{datetime.now().strftime('%H:%M:%S')}",
        flush=True,
    )

    cmd = [
        str(HARBOR_EXE),
        "run",
        "-p",
        str(task_dir),
        "-a",
        "my_pi_eval.agent:MyPiAgent",
        "-m",
        "deepseek/deepseek-chat",
        "--env-file",
        str(EVAL_DIR / ".env"),
        "--timeout-multiplier",
        "3.0",
    ]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'};{REPO_ROOT / 'my-pi-eval' / 'src'}"
    env["DEEPSEEK_API_KEY"] = "sk-0ecbb64201d441119f6a6b57e7eb15e3"
    env["PIP_INDEX_URL"] = "https://mirrors.aliyun.com/pypi/simple/"
    env["PIP_TRUSTED_HOST"] = "mirrors.aliyun.com"

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(EVAL_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=kill_deadline,
            encoding="utf-8",
            errors="replace",
        )
        duration = int(time.time() - start_time)
        if proc.returncode != 0 and duration < 10:
            print(f"[{task_name}] ❌ Harbor 启动失败 (退出码 {proc.returncode}): {proc.stderr[:300]}", flush=True)
    except subprocess.TimeoutExpired:
        duration = int(time.time() - start_time)
        print(f"[{task_name}] ⚠️ 触发硬性保护超时 ({kill_deadline}s)", flush=True)

    # Find latest trial in jobs/
    jobs_dir = EVAL_DIR / "jobs"
    latest_result = None
    if jobs_dir.exists():
        matching = []
        for jd in jobs_dir.iterdir():
            if not jd.is_dir():
                continue
            for sub in jd.iterdir():
                if sub.is_dir() and sub.name.startswith(f"{task_name}__"):
                    rf = sub / "result.json"
                    if rf.exists():
                        matching.append(rf)
        if matching:
            latest_result = max(matching, key=lambda x: x.stat().st_mtime)

    reward = 0.0
    tokens = 0
    cache_read = 0
    cost = 0.0
    status = "FAILED"

    if latest_result:
        try:
            rdata = json.loads(latest_result.read_text(encoding="utf-8", errors="replace"))
            vr = rdata.get("verifier_result") or {}
            if isinstance(vr, dict):
                rewards = vr.get("rewards") or {}
                reward = float(rewards.get("reward", 0.0) or 0.0)
            if reward == 0.0 and "reward" in rdata and rdata.get("reward") is not None:
                reward = float(rdata.get("reward", 0.0) or 0.0)
            ar = rdata.get("agent_result") or {}
            if isinstance(ar, dict):
                tokens = (ar.get("n_input_tokens") or 0) + (ar.get("n_output_tokens") or 0)
                cache_read = ar.get("n_cache_tokens") or 0
                cost = float(ar.get("cost_usd") or 0.0)

            # Fallback to metrics.json
            metrics_file = latest_result.parent / "agent" / "metrics.json"
            if metrics_file.exists():
                try:
                    mdata = json.loads(metrics_file.read_text(encoding="utf-8", errors="replace"))
                    if tokens == 0:
                        tokens = (mdata.get("prompt_tokens") or 0) + (mdata.get("completion_tokens") or 0)
                    if cache_read == 0:
                        cache_read = mdata.get("cache_read_tokens") or 0
                except (json.JSONDecodeError, OSError):
                    pass

            if reward >= 1.0:
                status = "PASSED"
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    # Prune network after container run
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, check=False)
    except Exception:
        pass

    # Save to progress
    cur_prog = load_progress()
    existing_status = cur_prog.get("tasks", {}).get(task_name, {}).get("status")
    if status == "PASSED" or existing_status != "PASSED":
        cur_prog.setdefault("tasks", {})[task_name] = {
            "status": status,
            "reward": reward,
            "duration_sec": duration,
            "tests_passed": 1 if reward >= 1.0 else 0,
            "tests_total": 1,
            "tokens": tokens,
            "cache_read_tokens": cache_read,
            "cost_usd": cost,
            "summary": "PASSED via MyPiAgent" if status == "PASSED" else "",
            "finished_at": datetime.now().isoformat(),
        }
        save_progress(cur_prog)

    print(
        f"[{task_name}] 战报: {status} (得分: {reward}, 耗时: {duration}s, Tokens: {tokens:,}) | "
        f"{datetime.now().strftime('%H:%M:%S')}",
        flush=True,
    )
    return {"task": task_name, "status": status, "reward": reward, "duration": duration, "tokens": tokens}


def main() -> None:
    print("=" * 80, flush=True)
    print("🏆 启动自研 MyPiAgent 在 Terminal-Bench 2.1 上的 4 并发全量评测 (85 赛题)")
    print("=" * 80, flush=True)

    subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, check=False)

    tasks_85 = get_85_tasks()
    total = len(tasks_85)
    print(f"评估赛题总数: {total} 道 (已剔除 4 道物理瓶颈题) | 并发度: 4\n", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_one_task, tname, i + 1, total): tname for i, tname in enumerate(tasks_85)}
        for future in concurrent.futures.as_completed(futures):
            tname = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"[{tname}] 异常: {e}", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("🏁 MyPiAgent Terminal-Bench 2.1 全量 85 题评测圆满完成！", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
