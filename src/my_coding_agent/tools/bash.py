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
    wrap_tool_executor,
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


def _is_wsl_bash(path: str) -> bool:
    """检查给定的 bash 路径是否为 WSL 存根 (System32 或 WindowsApps)。

    WSL 存根为 Linux 虚拟机入口，在非 WSL 宿主环境下无法直接运行 Windows 虚拟环境中的 python/uv，
    且文件系统与进程上下文互不相通，必须在 Windows 环境下排除以防误入 WSL。
    """
    norm = os.path.normpath(str(path)).lower()
    # 1. 过滤 System32 / Sysnative 下的旧版 WSL 存根
    if norm.endswith((r"\system32\bash.exe", r"\sysnative\bash.exe")):
        return True
    system_root = (os.environ.get("SystemRoot") or r"C:\Windows").lower()
    if norm.startswith(
        (
            os.path.join(system_root, "system32", "bash.exe").lower(),
            os.path.join(system_root, "sysnative", "bash.exe").lower(),
        )
    ):
        return True

    # 2. 过滤 Microsoft Store 版 WSL 存根 (WindowsApps 位置)
    if r"\microsoft\windowsapps\bash.exe" in norm or norm.endswith(r"\windowsapps\bash.exe"):
        return True

    return False


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

        # 2. 优先通过 PATH 上的 git.exe 动态推导 Git 安装根目录
        # Git 安装器默认将 Git\cmd 加入 PATH；根据 git.exe 向上反推 bin\bash.exe 或 usr\bin\bash.exe，
        # 可完美覆盖用户任意自定义安装路径（如 D:\Git、E:\Tools\Git、Scoop、Chocolatey 等），彻底消灭生硬的路径硬编码。
        git_executable = shutil.which("git") or shutil.which("git.exe")
        if git_executable:
            git_path = Path(git_executable).resolve()
            for parent in [git_path.parent, *git_path.parents]:
                for rel in ("bin/bash.exe", "usr/bin/bash.exe", "bash.exe"):
                    candidate = parent / rel
                    if os.path.exists(str(candidate)):
                        return str(candidate), True

        # 3. 探查 Git Bash 常见系统安装路径 (基于标准系统环境变量，绝无固定盘符写死)
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Git\bin\bash.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Git\bin\bash.exe"),
            os.path.expandvars(r"%LocalAppData%\Programs\Git\bin\bash.exe"),
            os.path.expandvars(r"%USERPROFILE%\scoop\apps\git\current\bin\bash.exe"),
            os.path.expandvars(r"%ProgramData%\chocolatey\bin\bash.exe"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c, True

        # 4. 探查 PATH 上的 bash.exe / bash，严格排除 WSL 存根
        found = shutil.which("bash.exe") or shutil.which("bash")
        if found and not _is_wsl_bash(found):
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
        description="Execute a bash command in the workspace (POSIX / Git Bash syntax; do not use cmd.exe syntax like 'dir' or 'cd /d'). Returns stdout and stderr.",
        prompt_snippet="Execute bash commands (ls, grep, find, etc.)",
        prompt_guidelines=["You can inspect PI_* environment variables for current model and session details."],
        is_parallel_safe=False,
    )
    async def bash(
        command: str,
        timeout: int = 120,
        run_in_background: bool = False,
        on_update: Callable[[Any], None] | None = None,
        signal: Any | None = None,
    ) -> Any:
        def _is_cancelled() -> bool:
            if signal is None:
                return False
            check = getattr(signal, "is_cancelled", None)
            if callable(check):
                return bool(check())
            return bool(getattr(signal, "cancelled", False))

        if _is_cancelled():
            return BashResult(
                ok=False,
                data="Tool call interrupted by user",
                error="Tool call interrupted by user",
            )

        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                msg = f"Error: Blocked dangerous command pattern '{blocked}'."
                return BashResult(ok=False, data=msg, error=msg)

        if run_in_background:
            runner = background_runner() if callable(background_runner) else background_runner
            if runner is None:
                msg = "Error: Background task execution not configured on this agent."
                return BashResult(ok=False, data=msg, error=msg)
            res = runner.run_process(command, cwd=workspace)
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
                "limit": 10 * 1024 * 1024,
            }
            if sys.platform != "win32":
                kwargs["preexec_fn"] = os.setsid

            shell_path, is_bash = _resolve_shell()
            env = dict(os.environ)
            if is_bash:
                env.setdefault("LANG", "C.UTF-8")
                env.setdefault("LC_ALL", "C.UTF-8")
                resolved_cmd = f"set -o pipefail\n{command}"
                proc = await asyncio.create_subprocess_exec(
                    shell_path,
                    "-c",
                    resolved_cmd,
                    env=env,
                    **kwargs,
                )
            else:
                proc = await asyncio.create_subprocess_shell(command, env=env, **kwargs)

            def _abort_proc() -> None:
                if proc.pid:
                    _kill_process_tree(proc.pid)

            if signal is not None and hasattr(signal, "add_callback"):
                signal.add_callback(_abort_proc)

            output_chunks: list[str] = []
            loop = asyncio.get_running_loop()
            last_update_time = loop.time()

            async def _read_stream() -> None:
                nonlocal last_update_time
                if proc.stdout is None:
                    return
                while True:
                    if _is_cancelled():
                        _abort_proc()
                        break
                    chunk = await proc.stdout.read(64 * 1024)
                    if not chunk:
                        break
                    text = _decode_stream_bytes(chunk)
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
                _abort_proc()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                msg = f"Error: Command timed out after {timeout} seconds: {command}"
                return BashResult(ok=False, data=msg, error=msg)
            except (asyncio.CancelledError, GeneratorExit):
                _abort_proc()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                raise

            if _is_cancelled():
                _abort_proc()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                return BashResult(
                    ok=False,
                    data="Tool call interrupted by user",
                    error="Tool call interrupted by user",
                )

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

    return wrap_tool_executor(
        bash,
        aliases={"command": ("cmd", "script")},
    )
