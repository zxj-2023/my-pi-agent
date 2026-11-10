from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from my_agent_core.tools.core import ToolResult

__all__ = [
    "CodemodeBridge",
    "ScriptResult",
]


def _kill_process_tree(pid: int) -> None:
    """递归杀死指定 PID 的进程树，兼容 Windows 与 POSIX。"""
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
    else:
        import signal as _posix_signal

        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, _posix_signal.SIGKILL)
        except Exception:
            with contextlib.suppress(Exception):
                os.kill(pid, _posix_signal.SIGKILL)


@dataclass
class ScriptResult:
    """Codemode JavaScript 脚本执行结果。"""

    ok: bool
    wall_time: float = 0.0
    text_items: list[str] = field(default_factory=list)
    console_lines: list[str] = field(default_factory=list)
    store_writes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class CodemodeBridge:
    """Python 宿主与 Node.js 沙箱 (runner.mjs) 之间的双向 IPC 驱动桥梁。"""

    def __init__(
        self,
        runner_path: str | Path | None = None,
        node_bin: str | None = None,
    ) -> None:
        self.runner_path = Path(runner_path) if runner_path is not None else Path(__file__).parent / "runner.mjs"
        self.node_bin = node_bin or shutil.which("node") or "node"

    async def execute_script(
        self,
        code: str,
        *,
        store: dict[str, Any] | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        timeout_ms: int | None = None,
        max_output_tokens: int | None = None,
        signal: Any | None = None,
    ) -> ScriptResult:
        """启动隔离的 Node.js 沙箱子进程，执行指定的 JS 代码并通过标准输入/输出进行交互。"""

        def _is_cancelled() -> bool:
            if signal is None:
                return False
            check = getattr(signal, "is_cancelled", None)
            if callable(check):
                return bool(check())
            return bool(getattr(signal, "cancelled", False))

        if _is_cancelled():
            return ScriptResult(ok=False, error="Execution interrupted by user")

        spawn_kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if sys.platform != "win32":
            spawn_kwargs["preexec_fn"] = os.setsid

        try:
            proc = await asyncio.create_subprocess_exec(
                self.node_bin,
                "--max-old-space-size=256",
                str(self.runner_path),
                **spawn_kwargs,
            )
        except Exception as exc:
            return ScriptResult(ok=False, error=f"Failed to spawn runner process: {exc}")

        def _abort_proc() -> None:
            if proc.returncode is None:
                if proc.pid:
                    _kill_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.kill()

        if signal is not None and hasattr(signal, "add_callback"):
            signal.add_callback(_abort_proc)

        async def _run_inner() -> ScriptResult:
            init_payload = {
                "action": "execute",
                "code": code,
                "store": store or {},
                "timeout_ms": timeout_ms,
                "max_output_tokens": max_output_tokens,
            }
            if proc.stdin is None or proc.stdout is None:
                return ScriptResult(ok=False, error="Process stdio pipes unavailable")

            proc.stdin.write((json.dumps(init_payload) + "\n").encode("utf-8"))
            await proc.stdin.drain()

            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break

                line_str = line_bytes.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    msg = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                action = msg.get("action")
                if action == "completed":
                    return ScriptResult(
                        ok=bool(msg.get("ok", False)),
                        wall_time=float(msg.get("wall_time", 0.0)),
                        text_items=list(msg.get("text_items", [])),
                        console_lines=list(msg.get("console_lines", [])),
                        store_writes=dict(msg.get("store_writes", {})),
                        error=msg.get("error"),
                    )

                if action == "tool_call":
                    call_id = msg.get("call_id")
                    name = msg.get("name", "")
                    args = msg.get("args") or {}

                    tool_ok = False
                    tool_result = None
                    tool_error = None

                    if tool_executor is None:
                        tool_ok = False
                        tool_error = f"No tool executor provided for tool '{name}'"
                    else:
                        try:
                            res = await tool_executor(name, args)
                            if isinstance(res, ToolResult):
                                tool_ok = bool(res.ok)
                                tool_result = res.data
                                tool_error = res.error if not tool_ok else None
                            elif (
                                isinstance(res, dict)
                                and "ok" in res
                                and ("error" in res or "result" in res or "data" in res)
                            ):
                                tool_ok = bool(res["ok"])
                                tool_result = res.get("result", res.get("data"))
                                tool_error = res.get("error") if not tool_ok else None
                            else:
                                tool_ok = True
                                tool_result = res
                                tool_error = None
                        except Exception as exc:
                            tool_ok = False
                            tool_error = str(exc) or type(exc).__name__

                    resp = {
                        "action": "tool_result",
                        "call_id": call_id,
                        "ok": tool_ok,
                        "result": tool_result,
                        "error": tool_error,
                    }
                    try:
                        proc.stdin.write((json.dumps(resp) + "\n").encode("utf-8"))
                        await proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break

            if _is_cancelled():
                return ScriptResult(ok=False, error="Execution interrupted by user")

            stderr_msg = ""
            if proc.stderr:
                with contextlib.suppress(Exception):
                    stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                    stderr_msg = stderr_bytes.decode("utf-8", errors="replace").strip()

            if stderr_msg:
                return ScriptResult(ok=False, error=f"Process exited prematurely: {stderr_msg}")
            return ScriptResult(ok=False, error="Process exited prematurely without result")

        try:
            if timeout_ms is not None and timeout_ms > 0:
                timeout_sec = timeout_ms / 1000.0
                return await asyncio.wait_for(_run_inner(), timeout=timeout_sec)
            return await _run_inner()
        except asyncio.TimeoutError:
            _abort_proc()
            return ScriptResult(ok=False, error=f"Execution timed out after {timeout_ms}ms")
        except asyncio.CancelledError:
            _abort_proc()
            if _is_cancelled():
                return ScriptResult(ok=False, error="Execution interrupted by user")
            raise
        except Exception as exc:
            _abort_proc()
            if _is_cancelled():
                return ScriptResult(ok=False, error="Execution interrupted by user")
            return ScriptResult(ok=False, error=str(exc) or type(exc).__name__)
        finally:
            _abort_proc()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
