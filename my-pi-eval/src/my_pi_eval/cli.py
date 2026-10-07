"""CLI runner and environment doctor for my-pi-eval."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    _eval_root = Path(__file__).resolve().parent.parent.parent
    _eval_env = _eval_root / ".env"
    if _eval_env.exists():
        load_dotenv(_eval_env, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass


def check_docker_environment() -> bool:
    """Check whether the Docker engine is running and accessible."""
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return res.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def build_harbor_command(
    task_path: str,
    model: str = "deepseek/deepseek-chat",
    concurrency: int = 1,
    agent_path: str = "my_pi_eval.agent:MyPiAgent",
) -> list[str]:
    """Assemble the official Harbor CLI execution command."""
    return [
        "harbor",
        "run",
        "-p",
        task_path,
        "--agent-import-path",
        agent_path,
        "-m",
        model,
        "-n",
        str(concurrency),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="my-pi-eval",
        description="Harbor-based evaluation runner for my-pi-agent against Terminal-Bench 2.0",
    )
    parser.add_argument(
        "-p",
        "--path",
        "--task-path",
        dest="task_path",
        required=False,
        help="Path to the benchmark task directory or dataset directory",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="deepseek/deepseek-chat",
        help="Model identifier (default: deepseek/deepseek-chat)",
    )
    parser.add_argument(
        "-n",
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent task evaluations (default: 1)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run environment preflight check only without launching tasks",
    )

    args = parser.parse_args(argv)

    print("=== My-Pi-Agent Evaluation Preflight ===")
    docker_ok = check_docker_environment()
    if docker_ok:
        print("[✓] Docker Engine is running and responsive.")
    else:
        print("[✗] Docker Engine is NOT running or accessible.")
        print("    Please launch Docker Desktop or start the Docker daemon before running evaluations.")
        if args.check or not args.task_path:
            return 1

    if args.check:
        return 0 if docker_ok else 1

    if not args.task_path:
        parser.print_help()
        return 0

    cmd = build_harbor_command(
        task_path=args.task_path,
        model=args.model,
        concurrency=args.concurrency,
    )
    print("\nExecuting Harbor command:")
    print("  " + " ".join(cmd))

    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except FileNotFoundError:
        print("\n[!] 'harbor' CLI not found on PATH.")
        print("    Install harbor with: pip install harbor")
        return 1


if __name__ == "__main__":
    sys.exit(main())
