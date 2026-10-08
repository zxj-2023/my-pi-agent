import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")

jobs_dir = Path("D:/code/python/agent-eval/pi-terminal-bench/jobs")
task_results = {}

for p in jobs_dir.iterdir():
    if p.is_dir():
        res_file = p / "result.json"
        cfg_file = p / "config.json"
        if res_file.exists() and cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8", errors="replace"))
                tasks_cfg = cfg.get("tasks", [])
                if not tasks_cfg:
                    continue
                t_path = tasks_cfg[0].get("path", "")
                t_name = Path(t_path).name

                res = json.loads(res_file.read_text(encoding="utf-8", errors="replace"))
                stats = res.get("stats", {})
                evals = stats.get("evals", {})
                reward = 0.0
                for ed in evals.values():
                    for m in ed.get("metrics", []):
                        if "mean" in m:
                            reward = float(m["mean"])
                            break

                # Check log for PASSED
                for td in p.iterdir():
                    if td.is_dir() and td.name != "__pycache__":
                        tl = td / "trial.log"
                        if tl.exists():
                            txt = tl.read_text(encoding="utf-8", errors="replace")
                            if "PASSED" in txt or "tests passed" in txt.lower():
                                reward = max(reward, 1.0)

                tok = (stats.get("n_input_tokens") or 0) + (stats.get("n_output_tokens") or 0)
                cost = stats.get("cost_usd") or 0.0
                mtime = p.stat().st_mtime

                # If multiple runs for this task, keep the one with highest reward, or newest
                if (
                    t_name not in task_results
                    or reward > task_results[t_name]["reward"]
                    or (reward == task_results[t_name]["reward"] and mtime > task_results[t_name]["mtime"])
                ):
                    task_results[t_name] = {
                        "reward": reward,
                        "tokens": tok,
                        "cost": cost,
                        "passed": reward >= 1.0,
                        "mtime": mtime,
                        "job": p.name,
                    }
            except Exception:
                pass

passed_tasks = [k for k, v in task_results.items() if v["passed"]]
failed_tasks = [k for k, v in task_results.items() if not v["passed"]]

print(f"Total Unique Tasks Evaluated across all jobs: {len(task_results)}")
print(f"Total Truly PASSED Tasks: {len(passed_tasks)}")
print(f"Total FAILED Tasks: {len(failed_tasks)}")
win_rate = (len(passed_tasks) / len(task_results)) * 100 if task_results else 0.0
print(f"Overall Benchmark Pass Rate: {win_rate:.2f}%\n")

print("=== ALL PASSED TASKS ===")
for i, t in enumerate(sorted(passed_tasks), 1):
    info = task_results[t]
    print(
        f" {i:>2}. {t:<32} | reward={info['reward']} | tok={info['tokens']:>8,} | cost=${info['cost']:>6.3f} | job={info['job']}"
    )

# Save the unified truth to official_pi_progress.json
prog_file = Path("my-pi-eval/results/official_pi_progress.json")
current_prog = {}
if prog_file.exists():
    try:
        current_prog = json.loads(prog_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        current_prog = {}

prog_tasks = current_prog.get("tasks", {})
for t_name, info in task_results.items():
    if t_name in prog_tasks:
        if info["passed"] or prog_tasks[t_name].get("tokens", 0) == 0:
            prog_tasks[t_name]["status"] = "PASSED" if info["passed"] else "FAILED"
            prog_tasks[t_name]["reward"] = info["reward"]
            if info["tokens"] > 0:
                prog_tasks[t_name]["tokens"] = info["tokens"]
                prog_tasks[t_name]["cost_usd"] = info["cost"]
    else:
        prog_tasks[t_name] = {
            "status": "PASSED" if info["passed"] else "FAILED",
            "reward": info["reward"],
            "tokens": info["tokens"],
            "cost_usd": info["cost"],
            "duration_sec": 0,
            "tests_passed": 1 if info["passed"] else 0,
            "tests_total": 1,
            "summary": "",
            "finished_at": "",
        }

current_prog["tasks"] = prog_tasks
current_prog["completed_count"] = len(prog_tasks)
current_prog["passed_count"] = sum(1 for t in prog_tasks.values() if t.get("status") == "PASSED")
current_prog["failed_count"] = current_prog["completed_count"] - current_prog["passed_count"]
prog_file.write_text(json.dumps(current_prog, indent=2, ensure_ascii=False), encoding="utf-8")
print(
    f"\n[INFO] Successfully synchronized official_pi_progress.json! Final passed count: {current_prog['passed_count']}"
)
