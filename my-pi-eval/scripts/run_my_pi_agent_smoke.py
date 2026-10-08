"""Run smoke test evaluating MyPiAgent on build-cython-ext via Harbor."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = Path("D:/code/python/agent-eval/pi-terminal-bench")
HARBOR_EXE = EVAL_DIR / ".venv" / "Scripts" / "harbor.exe"
TASK_DIR = Path("D:/code/python/agent-eval/terminal-bench-2/build-cython-ext")


def main() -> None:
    print("=" * 80)
    print("🧪 启动 MyPiAgent 单题冒烟验证: build-cython-ext")
    print("=" * 80)

    cmd = [
        str(HARBOR_EXE),
        "run",
        "-p", str(TASK_DIR),
        "-a", "my_pi_eval.agent:MyPiAgent",
        "-m", "deepseek/deepseek-chat",
        "--env-file", str(EVAL_DIR / ".env"),
        "--timeout-multiplier", "2.0",
    ]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'};{REPO_ROOT / 'my-pi-eval' / 'src'}"
    env["DEEPSEEK_API_KEY"] = "sk-0ecbb64201d441119f6a6b57e7eb15e3"

    start_time = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(EVAL_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    dur = int(time.time() - start_time)

    print(f"Harbor 进程退出码: {proc.returncode} (耗时: {dur}s)")
    if proc.stderr:
        print("--- STDERR ---")
        print(proc.stderr[-500:])

    # Find result in jobs/
    jobs_dir = EVAL_DIR / "jobs"
    latest_result = None
    if jobs_dir.exists():
        matching = []
        for jd in jobs_dir.iterdir():
            for sub in jd.iterdir():
                if sub.is_dir() and sub.name.startswith("build-cython-ext__"):
                    rf = sub / "result.json"
                    if rf.exists():
                        matching.append(rf)
        if matching:
            latest_result = max(matching, key=lambda x: x.stat().st_mtime)

    if latest_result:
        try:
            rdata = json.loads(latest_result.read_text(encoding="utf-8", errors="replace"))
            vr = rdata.get("verifier_result") or {}
            rew = vr.get("rewards", {}).get("reward", 0.0) if isinstance(vr, dict) else 0.0
            ar = rdata.get("agent_result") or {}
            tok = (ar.get("n_input_tokens") or 0) + (ar.get("n_output_tokens") or 0)
            print("=" * 80)
            print(f"🎉 冒烟验证战报: build-cython-ext -> 得分: {rew} | 耗时: {dur}s | Tokens: {tok:,}")
            print("=" * 80)
        except Exception as e:
            print(f"解析结果失败: {e}")
    else:
        print("❌ 未在 jobs/ 找到评测结果文件")


if __name__ == "__main__":
    main()
