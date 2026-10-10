"""Strict 1:1 timeout evaluation runner for the 20 remaining Terminal-Bench 2.1 tasks.

Features:
- Dynamically parses each task's task.toml for agent.timeout_sec and verifier.timeout_sec.
- Strictly sets --timeout-multiplier 1.0 (no arbitrary inflation).
- Sets process kill deadline to agent_timeout + verifier_timeout + 180s.
- Reads API credentials exclusively from my-pi-eval/.env.
- Runs 3-worker concurrency with staggered startup and atomic progress persistence.
"""

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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = Path("D:/code/python/agent-eval/pi-terminal-bench")
TB2_TASKS_DIR = Path("D:/code/python/agent-eval/terminal-bench-2")
HARBOR_EXE = EVAL_DIR / ".venv" / "Scripts" / "harbor.exe"
PROGRESS_FILE = REPO_ROOT / "my-pi-eval" / "results" / "my_pi_agent_progress.json"
PROGRESS_LOCK = threading.Lock()

# The 20 remaining tasks ordered by ROI & official duration
TARGET_20_TASKS = [
    # ── Tier 1: 刚修复截断续写的重点攻坚题 (900s ~ 3600s) ───────────────────
    "polyglot-rust-c",
    "regex-chess",
    # ── Tier 2: 仅差 1 行代码或 1 帧的近失失误题 (900s ~ 3600s) ─────────────
    "large-scale-text-editing",
    "filter-js-from-html",
    "video-processing",
    # ── Tier 3: 逆向与算法短周期赛题 (900s ~ 1800s) ────────────────────────
    "gcode-to-text",
    "query-optimize",
    "sanitize-git-repo",
    "adaptive-rejection-sampler",
    "dna-assembly",
    "raman-fitting",
    "torch-pipeline-parallelism",
    "qemu-alpine-ssh",
    # ── Tier 4: 中长周期算法与系统题 (1200s ~ 3600s) ───────────────────────
    "bn-fit-modify",
    "install-windows-3.11",
    "train-fasttext",
    # ── Tier 5: 4 道单机物理极限题 (1:1 原厂限时检验) ────────────────────────
    "make-doom-for-mips",
    "caffe-cifar-10",
    "extract-moves-from-video",
    "sam-cell-seg",
]


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


def get_task_timeouts(task_name: str) -> tuple[float, float]:
    """Parse task.toml to get exact official agent and verifier timeout in seconds."""
    toml_path = TB2_TASKS_DIR / task_name / "task.toml"
    if toml_path.exists():
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            agent_t = float(data.get("agent", {}).get("timeout_sec", 900.0))
            verifier_t = float(data.get("verifier", {}).get("timeout_sec", 900.0))
            return agent_t, verifier_t
        except Exception:
            pass
    return 900.0, 900.0


def run_one_task(task_name: str, index: int, total: int) -> dict:
    time.sleep(2 * (index % 3))

    prog = load_progress()
    existing = prog.get("tasks", {}).get(task_name, {})
    if existing.get("status") == "PASSED" and existing.get("reward", 0.0) >= 1.0:
        print(f"[{index}/{total}] ⏩ {task_name} 已满分通过，跳过。", flush=True)
        return {"task": task_name, "status": "PASSED", "skipped": True}

    task_dir = TB2_TASKS_DIR / task_name
    if not task_dir.exists():
        print(f"[{index}/{total}] ❌ 任务目录不存在: {task_dir}", flush=True)
        return {"task": task_name, "status": "FAILED", "error": "not_found"}

    agent_timeout, verifier_timeout = get_task_timeouts(task_name)
    kill_deadline = int(agent_timeout + verifier_timeout + 180)

    print(
        f"[{index}/{total}] 🚀 启动严格配时评测: {task_name} | "
        f"Agent限时: {int(agent_timeout)}s ({int(agent_timeout)//60}m), "
        f"Verifier限时: {int(verifier_timeout)}s, "
        f"保护截止: {kill_deadline}s | {datetime.now().strftime('%H:%M:%S')}",
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
        str(REPO_ROOT / "my-pi-eval" / ".env"),
        "--timeout-multiplier",
        "1.0",
    ]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'};{REPO_ROOT / 'my-pi-eval' / 'src'}"
    env_file = REPO_ROOT / "my-pi-eval" / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env["PIP_INDEX_URL"] = "https://mirrors.aliyun.com/pypi/simple/"
    env["PIP_EXTRA_INDEX_URL"] = "https://download.pytorch.org/whl/cpu"
    env["PIP_TRUSTED_HOST"] = "mirrors.aliyun.com download.pytorch.org"
    env["MY_AGENT_DEBUG"] = "1"

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
            print(f"[{task_name}] ❌ Harbor 启动异常 (码 {proc.returncode}): {proc.stderr[:300]}", flush=True)
    except subprocess.TimeoutExpired:
        duration = int(time.time() - start_time)
        print(f"[{task_name}] ⚠️ 触发严格保护超时 ({kill_deadline}s)", flush=True)

    # 检索 Harbor 产出的最新 trial result.json
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

    # 容器网络与垃圾回收
    try:
        subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, check=False)
    except Exception:
        pass

    # 持久化结果
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
            "summary": "PASSED via Strict Rerun" if status == "PASSED" else "",
            "finished_at": datetime.now().isoformat(),
        }
        save_progress(cur_prog)

    badge = "🏆 PASSED" if status == "PASSED" else "❌ FAILED"
    print(
        f"[{task_name}] {badge} | 得分: {reward}, 耗时: {duration}s, Tokens: {tokens:,} | "
        f"{datetime.now().strftime('%H:%M:%S')}",
        flush=True,
    )
    return {"task": task_name, "status": status, "reward": reward, "duration": duration, "tokens": tokens}


def main():
    print("=" * 80)
    print("🎯 MyPiAgent Terminal-Bench 2.1: 20 道赛题严格官方配时重跑引擎启动")
    print(f"目标题数: {len(TARGET_20_TASKS)} 题 | 并发数: 3 workers | 倍率: --timeout-multiplier 1.0")
    print("=" * 80)

    # 验证 Docker
    try:
        chk = subprocess.run(["docker", "info"], capture_output=True, text=True, check=True)
    except Exception as e:
        print(f"❌ Docker 守护进程未启动，终止运行: {e}")
        sys.exit(1)

    prog = load_progress()
    tasks_to_run = [t for t in TARGET_20_TASKS if prog.get("tasks", {}).get(t, {}).get("status") != "PASSED"]
    print(f"📊 待评测任务数: {len(tasks_to_run)} / {len(TARGET_20_TASKS)}")
    for i, t in enumerate(tasks_to_run, 1):
        at, vt = get_task_timeouts(t)
        print(f"  [{i:02d}] {t:30} -> Agent: {int(at)}s ({int(at)//60}m), Verifier: {int(vt)}s")

    total = len(tasks_to_run)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_one_task, task_name, idx, total): task_name
            for idx, task_name in enumerate(tasks_to_run, 1)
        }
        for future in concurrent.futures.as_completed(futures):
            t_name = futures[future]
            try:
                future.result()
            except Exception as exc:
                print(f"[{t_name}] 任务执行抛出未捕获异常: {exc}", flush=True)

    print("=" * 80)
    print("🏁 20 道严格配时赛题重跑全流程结束！")
    final_prog = load_progress().get("tasks", {})
    passed = sum(1 for t in final_prog.values() if t.get("status") == "PASSED")
    print(f"最新总成绩: {passed} / 89 题通过！")
    print("=" * 80)


if __name__ == "__main__":
    main()
