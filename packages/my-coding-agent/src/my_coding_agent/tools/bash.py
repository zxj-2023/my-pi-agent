from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import signal
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from my_agent_core.background import BackgroundRunner
from my_agent_core.tools import Tool, ToolResult, tool

from my_coding_agent.tools.base import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
)

BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero",
    ":(){ :|:& };:",
    "shutdown",
    "reboot",
    "init 0",
}


def _kill_process_tree(pid: int) -> None:
    """递归杀死指定 PID 的进程树，兼容 Windows 与 POSIX。"""
    if sys.platform == "win32":
        import subprocess

        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            with contextlib.suppress(Exception):
                os.kill(pid, signal.SIGKILL)


@dataclass
class BashResult(ToolResult):
    """Bash 工具执行结果：继承 ToolResult，兼容字符串直接比较与包含操作。"""

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            val = self.data if self.data is not None else self.error
            return str(val) == other
        return super().__eq__(other)

    def __contains__(self, item: Any) -> bool:
        content = self.data if self.data is not None else (self.error or "")
        return str(item) in str(content)

    def __str__(self) -> str:
        return str(self.data if self.data is not None else self.error)

    def __repr__(self) -> str:
        return repr(self.data if self.data is not None else self.error)


def make_bash_tool(
    workspace: Path | str,
    background_runner: BackgroundRunner | None = None,
) -> Tool:
    """创建 bash 工具工厂，绑定 workspace 目录并支持超时终结、日志外溢与后台运行。"""
    workspace = Path(workspace).resolve()

    @tool(
        name="bash",
        description="Execute a bash/shell command in the workspace with timeout protection and process tree killing.",
        is_parallel_safe=False,
    )
    async def bash(
        command: str,
        timeout: int = 120,
        run_in_background: bool = False,
    ) -> str:
        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                return f"Error: Blocked dangerous command pattern '{blocked}'."

        if run_in_background:
            if background_runner is None:
                return "Error: Background task execution not configured on this agent."
            res = background_runner.run_process(command, cwd=workspace)
            task_id = await res if inspect.isawaitable(res) else res
            return f"Background task started with ID: {task_id}"

        try:
            kwargs: dict[str, Any] = {
                "cwd": str(workspace),
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.STDOUT,
                "stdin": asyncio.subprocess.DEVNULL,
            }
            if sys.platform != "win32":
                kwargs["preexec_fn"] = os.setsid

            proc = await asyncio.create_subprocess_shell(command, **kwargs)

            try:
                stdout_data, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                output = (
                    stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
                )
            except asyncio.TimeoutError:
                if proc.pid:
                    _kill_process_tree(proc.pid)
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                return f"Error: Command timed out after {timeout} seconds: {command}"
            except (asyncio.CancelledError, GeneratorExit):
                if proc.pid:
                    _kill_process_tree(proc.pid)
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                raise

            exit_code = proc.returncode

            # 处理尾部截断与外溢至临时日志文件
            lines = output.splitlines()
            total_lines = len(lines)
            encoded = output.encode("utf-8")
            is_overflow = (
                total_lines > DEFAULT_MAX_LINES or len(encoded) > DEFAULT_MAX_BYTES
            )

            if is_overflow:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    prefix="pi-bash-",
                    suffix=".log",
                    delete=False,
                    encoding="utf-8",
                ) as f:
                    f.write(output)
                    temp_log_path = f.name

                truncated_lines = lines[-DEFAULT_MAX_LINES:]
                truncated_text = "\n".join(truncated_lines)
                trunc_bytes = truncated_text.encode("utf-8")
                if len(trunc_bytes) > DEFAULT_MAX_BYTES:
                    tail_bytes = trunc_bytes[-DEFAULT_MAX_BYTES:]
                    nl_pos = tail_bytes.find(b"\n")
                    if nl_pos != -1 and nl_pos + 1 < len(tail_bytes):
                        tail_bytes = tail_bytes[nl_pos + 1 :]
                    truncated_text = tail_bytes.decode("utf-8", errors="ignore")
                    truncated_lines = truncated_text.splitlines()

                output = (
                    f"[Output truncated: showing last {len(truncated_lines)} lines of {total_lines}. "
                    f"Full output saved to: {temp_log_path}]\n\n{truncated_text}"
                )

            if exit_code != 0:
                return f"Command failed with exit code {exit_code}:\n{output}"

            return output or "(Command executed with no output)"
        except Exception as e:
            return f"Error: {e}"

    orig_execute = bash.execute

    async def execute(
        args: dict[str, Any] | None = None,
        signal: Any | None = None,
        on_update: Callable[[Any], None] | None = None,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> BashResult:
        call_args = dict(args) if isinstance(args, dict) else {}
        call_args.update(kwargs)
        res = await orig_execute(
            call_args,
            signal=signal,
            on_update=on_update,
            tool_call_id=tool_call_id,
        )
        return BashResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    bash.execute = execute
    return bash
