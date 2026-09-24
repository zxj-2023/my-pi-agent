from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from my_agent_core.background import BackgroundRunner
from my_agent_core.tools import Tool, tool

from my_coding_agent.tools.base import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    StringCompatibleToolResult,
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


class BashResult(StringCompatibleToolResult):
    """Bash 工具执行结果：继承 StringCompatibleToolResult。"""


def _resolve_shell() -> tuple[str, bool]:
    """解析当前环境最合适的 Shell 执行器。

    Windows 下对齐 Pi 原厂策略：优先探测 Git Bash，获得一致的 Linux 工具链 (ls/find/head/grep/cat)；
    若未安装则降级为系统默认 cmd.exe。
    返回 (shell_path, is_bash)。
    """
    if sys.platform == "win32":
        # 1. 优先检查用户自定义环境变量
        custom = os.environ.get("PI_BASH_PATH") or os.environ.get("SHELL_PATH")
        if custom and os.path.exists(custom):
            return custom, True

        # 2. 探查 Git Bash 常见安装路径
        candidates = [
            r"D:\gitbash\Git\bin\bash.exe",
            os.path.expandvars(r"%ProgramFiles%\Git\bin\bash.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Git\bin\bash.exe"),
            os.path.expandvars(r"%LocalAppData%\Programs\Git\bin\bash.exe"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c, True

        # 3. 探查 PATH 上的 bash
        found = shutil.which("bash.exe") or shutil.which("bash")
        if found:
            norm = found.replace("/", "\\").lower()
            if not norm.endswith(r"\windows\system32\bash.exe"):
                return found, True

        return "cmd.exe", False

    # POSIX 平台
    found = shutil.which("bash") or "/bin/sh"
    return found, True


def _decode_stream_bytes(data: bytes) -> str:
    """健壮解码子进程字节流，优先 UTF-8，自动防御性回退本地 OEM/GBK 编码，消灭乱码。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        import locale

        enc = locale.getpreferredencoding(False) or "gbk"
        return data.decode(enc, errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")



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
        on_update: Callable[[Any], None] | None = None,
    ) -> Any:
        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                msg = f"Error: Blocked dangerous command pattern '{blocked}'."
                return BashResult(ok=False, data=msg, error=msg)

        if run_in_background:
            if background_runner is None:
                msg = "Error: Background task execution not configured on this agent."
                return BashResult(ok=False, data=msg, error=msg)
            res = background_runner.run_process(command, cwd=workspace)
            task_id = await res if inspect.isawaitable(res) else res
            return BashResult(
                ok=True,
                data=f"Background task started with ID: {task_id}",
                error=None,
            )

        try:
            kwargs: dict[str, Any] = {
                "cwd": str(workspace),
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.STDOUT,
                "stdin": asyncio.subprocess.DEVNULL,
            }
            if sys.platform != "win32":
                kwargs["preexec_fn"] = os.setsid

            shell_path, is_bash = _resolve_shell()
            env = dict(os.environ)
            if is_bash:
                env.setdefault("LANG", "C.UTF-8")
                env.setdefault("LC_ALL", "C.UTF-8")
                proc = await asyncio.create_subprocess_exec(
                    shell_path,
                    "-c",
                    command,
                    env=env,
                    **kwargs,
                )
            else:
                proc = await asyncio.create_subprocess_shell(command, env=env, **kwargs)

            output_chunks: list[str] = []
            loop = asyncio.get_running_loop()
            last_update_time = loop.time()

            async def _read_stream() -> None:
                nonlocal last_update_time
                if proc.stdout is None:
                    return
                while True:
                    line_bytes = await proc.stdout.readline()
                    if not line_bytes:
                        break
                    text = _decode_stream_bytes(line_bytes)
                    output_chunks.append(text)
                    now = loop.time()
                    if on_update is not None and (now - last_update_time >= 0.1):
                        last_update_time = now
                        tail_preview = "".join(output_chunks[-5:]).strip()
                        if tail_preview:
                            on_update(tail_preview)

            try:
                await asyncio.wait_for(_read_stream(), timeout=timeout)
                await proc.wait()
                output = "".join(output_chunks)
            except asyncio.TimeoutError:
                if proc.pid:
                    _kill_process_tree(proc.pid)
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
                msg = f"Error: Command timed out after {timeout} seconds: {command}"
                return BashResult(ok=False, data=msg, error=msg)
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
            is_overflow = total_lines > DEFAULT_MAX_LINES or len(encoded) > DEFAULT_MAX_BYTES

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
                msg = f"Command failed with exit code {exit_code}:\n{output}"
                return BashResult(ok=False, data=msg, error=msg)

            return BashResult(
                ok=True,
                data=output or "(Command executed with no output)",
                error=None,
            )
        except Exception as e:
            msg = f"Error: {e}"
            return BashResult(ok=False, data=msg, error=msg)

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
        if isinstance(res, BashResult):
            return res
        if isinstance(res.data, BashResult):
            return res.data
        return BashResult(
            ok=res.ok,
            data=res.data,
            error=res.error,
            meta=res.meta,
            terminate=res.terminate,
        )

    bash.execute = execute
    return bash
