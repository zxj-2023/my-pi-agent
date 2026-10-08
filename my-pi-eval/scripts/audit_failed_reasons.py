import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")

prog_file = Path("my-pi-eval/results/official_pi_progress.json")
data = {}
if prog_file.exists():
    try:
        data = json.loads(prog_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        data = {}
tasks = data.get("tasks", {})

jobs_dir = Path("D:/code/python/agent-eval/pi-terminal-bench/jobs")

# Map of task_name -> list of job dirs
task_jobs = {}
if jobs_dir.exists():
    for p in jobs_dir.iterdir():
        if p.is_dir():
            cfg_file = p / "config.json"
            if cfg_file.exists():
                try:
                    cfg = json.loads(cfg_file.read_text(encoding="utf-8", errors="replace"))
                    t_list = cfg.get("tasks", [])
                    if t_list:
                        t_name = Path(t_list[0].get("path", "")).name
                        task_jobs.setdefault(t_name, []).append(p)
                except Exception:
                    pass

timeouts = []
env_fails = []
code_fails = []

for name, t in sorted(tasks.items()):
    if t.get("status") == "PASSED":
        continue

    tok = t.get("tokens", 0)
    dur = t.get("duration_sec", 0)

    # Inspect the job logs for this task
    matched = task_jobs.get(name, [])
    matched.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    reason_found = False
    is_timeout = False
    is_env = False
    details = ""

    if matched:
        latest = matched[0]
        # Check trial.log
        for td in latest.iterdir():
            if td.is_dir() and td.name != "__pycache__":
                tl = td / "trial.log"
                ex = td / "exception.txt"
                if tl.exists():
                    txt = tl.read_text(encoding="utf-8", errors="replace")
                    if "timed out" in txt.lower() or "timeout" in txt.lower():
                        is_timeout = True
                    if "setup" in txt.lower() and ("failed" in txt.lower() or "error" in txt.lower()):
                        is_env = True
                        details = "Setup / Installation error"
                if ex.exists():
                    ex_txt = ex.read_text(encoding="utf-8", errors="replace")
                    if "timeout" in ex_txt.lower():
                        is_timeout = True
                    elif "docker" in ex_txt.lower() or "network" in ex_txt.lower() or "connection" in ex_txt.lower():
                        is_env = True
                        details = ex_txt.strip().splitlines()[-1] if ex_txt.strip().splitlines() else "Docker exception"

    if dur >= 890:
        timeouts.append((name, dur, tok, "执行达到 15 分钟 (900s) 硬超时门槛"))
    elif tok == 0 or dur < 120 or is_env:
        desc = details if details else "Agent 未能进场 (环境安装/网络/拦截失败)"
        env_fails.append((name, dur, tok, desc))
    else:
        code_fails.append((name, dur, tok, "Agent 真实做题完成，但未能通过官方全部测试用例"))

print(f"=== 失败任务总数: {len(timeouts) + len(env_fails) + len(code_fails)} 道 ===")
print(f"1. 物理超时失败 (Timeout 15m): {len(timeouts)} 道")
print(f"2. 环境/未跑/拦截失败 (Environment / Interrupted): {len(env_fails)} 道")
print(f"3. 真实算法逻辑未过 (Genuine Logic Fail): {len(code_fails)} 道\n")

print("--- 1. 物理超时失败题目清单 (15分钟时间不够用) ---")
for i, (name, dur, tok, d) in enumerate(timeouts, 1):
    print(f"  {i:>2}. {name:<32} | 耗时: {dur:>3}s | Tokens: {tok:>8,} | {d}")

print("\n--- 2. 环境未进场/暂停拦截题目清单 (可补考) ---")
for i, (name, dur, tok, d) in enumerate(env_fails, 1):
    print(f"  {i:>2}. {name:<32} | 耗时: {dur:>3}s | Tokens: {tok:>8,} | {d}")

print("\n--- 3. 真实做题未满分题目清单 (模型能力正常体现) ---")
for i, (name, dur, tok, d) in enumerate(code_fails, 1):
    print(f"  {i:>2}. {name:<32} | 耗时: {dur:>3}s | Tokens: {tok:>8,} | {d}")
